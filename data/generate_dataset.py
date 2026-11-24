"""Generate a synthetic civic-complaint dataset for CivicSense.

Complaints are built from templates with realistic noise (typos, filler text,
vague reports, a little label noise) and ~12% are re-worded duplicates of an
earlier complaint at the same place. Real 311 data should be added later.
"""
import math
import random
import pandas as pd

random.seed(42)

PRIORITIES = ["low", "medium", "high", "critical"]

# (issue phrase, base severity 0-3)
ISSUES = {
    "Road": [("pothole", 1), ("big pothole", 2), ("road caved in after the rain", 3),
             ("broken speed breaker", 1), ("open manhole on the road", 3),
             ("road badly damaged", 2), ("cracks on the road surface", 0)],
    "Sanitation": [("garbage not collected", 1), ("overflowing garbage bin", 1),
                   ("dead animal lying on the road", 2), ("garbage being burnt", 2),
                   ("garbage dump blocking the road", 2), ("foul smell from the dump", 1),
                   ("medical waste dumped openly", 3), ("litter near the bus stop", 0)],
    "Electricity": [("streetlight not working", 1), ("flickering streetlight", 0),
                    ("live wire hanging low", 3), ("transformer sparking", 3),
                    ("power cut since morning", 2), ("electric pole tilted", 2),
                    ("exposed cable on the footpath", 3)],
    "Water Supply": [("no water supply", 2), ("low water pressure", 1), ("pipe leakage", 1),
                     ("burst water pipe", 2), ("dirty water coming from the tap", 2),
                     ("water tanker not arrived", 1), ("contaminated water making people ill", 3)],
    "Drainage": [("blocked drain", 1), ("sewage overflow", 2), ("waterlogging on the street", 2),
                 ("drain cover missing", 3), ("stagnant water breeding mosquitoes", 1),
                 ("flooded road after the rain", 2), ("sewage mixing with drinking water", 3)],
}
PLACES = [("the government school", True), ("the hospital", True), ("the bus stand", False),
          ("the market", False), ("the temple", False), ("the railway bridge", False),
          ("the residential colony", False), ("the park", False), ("the petrol bunk", False)]
STREETS = ["Gandhi Street", "Nehru Road", "MG Road", "Lake View Road", "Anna Main Road",
           "Rose Garden Lane", "Temple Street", "Station Road", "Park Avenue", "Canal Bank Road"]
URGENT = ["a child almost fell in", "an accident happened here yesterday", "this is very dangerous"]
FILLER = ["", "", "", "Please look into it.", "Kindly resolve at the earliest.", "No action taken so far.",
          "Requesting immediate action."]
VAGUE = ["Something is wrong near {place}, please check.", "Big problem in {street}, nobody is helping.",
         "Area is in very bad condition, kindly do something.", "Please come and see the situation at {place}."]

TEMPLATES = [
    "{issue} near {place}",
    "{issue} on {street}",
    "Please fix the {issue} at {place} on {street}",
    "{issue} in {street} for {days} days now",
    "There is a {issue} near {place}, {street}",
    "{issue}!! {street} side, close to {place}",
    "Complaint: {issue} at {street}",
]

WARD_CENTRES = {w: (13.00 + (w // 4) * 0.012, 80.20 + (w % 4) * 0.012) for w in range(12)}

def typo(text):
    chars = list(text)
    for _ in range(random.choice([1, 1, 2])):
        if len(chars) < 6:
            break
        i = random.randrange(1, len(chars) - 1)
        if chars[i].isalpha():
            if random.random() < 0.5:
                chars[i], chars[i + 1] = chars[i + 1], chars[i]
            else:
                del chars[i]
    return "".join(chars)

def jitter(lat, lon, metres):
    dlat = random.uniform(-metres, metres) / 111_000
    dlon = random.uniform(-metres, metres) / (111_000 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon

def render(base, vague=False):
    place = base["place"]
    if vague:
        text = random.choice(VAGUE).format(place=place, street=base["street"])
    else:
        pool = [t for t in TEMPLATES if base["use_place"] or "{place}" not in t]
        text = random.choice(pool).format(issue=base["issue"], place=place,
                                               street=base["street"], days=random.randint(2, 15))
        if base["urgent"]:
            text += ", " + base["urgent"]
        f = random.choice(FILLER)
        text = (text + ". " + f).strip()
    text = text[0].upper() + text[1:]
    return typo(text) if random.random() < 0.15 else text

def new_base():
    cat = random.choice(list(ISSUES))
    issue, sev = random.choice(ISSUES[cat])
    place, sensitive = random.choice(PLACES)
    use_place = random.random() < 0.6          # place is only in the text (and counts) if mentioned
    urgent = random.choice(URGENT) if random.random() < 0.08 else ""
    score = sev + (1 if sensitive and use_place else 0) + (1 if urgent else 0)
    ward = random.randrange(12)
    lat, lon = jitter(*WARD_CENTRES[ward], 600)
    return dict(category=cat, issue=issue, place=place, use_place=use_place, street=random.choice(STREETS), urgent=urgent,
                priority=PRIORITIES[min(score, 3)], ward=ward + 1, lat=lat, lon=lon)

def main(n=1500):
    rows = []
    while len(rows) < n:
        base = new_base()
        vague = random.random() < 0.05
        pri = base["priority"]
        if random.random() < 0.03:  # label noise
            pri = PRIORITIES[max(0, min(3, PRIORITIES.index(pri) + random.choice([-1, 1])))]
        cid = len(rows) + 1
        rows.append(dict(complaint_id=cid, text=render(base, vague), category=base["category"], priority=pri,
                         ward=base["ward"], lat=round(base["lat"], 6), lon=round(base["lon"], 6),
                         duplicate_of=""))
        if not vague and random.random() < 0.12:  # re-worded duplicate at the same spot
            for _ in range(random.choice([1, 1, 2])):
                lat, lon = jitter(base["lat"], base["lon"], 25)
                rows.append(dict(complaint_id=len(rows) + 1, text=render(base), category=base["category"],
                                 priority=pri, ward=base["ward"], lat=round(lat, 6), lon=round(lon, 6),
                                 duplicate_of=cid))
    df = pd.DataFrame(rows)
    df.to_csv("data/complaints.csv", index=False)
    print(f"{len(df)} complaints written; {(df.duplicate_of != '').sum()} are duplicates")
    print(df.category.value_counts().to_string()); print(df.priority.value_counts().to_string())

if __name__ == "__main__":
    main()
