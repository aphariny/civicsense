"""The priority guide: how the same problem ranks on an ordinary street, in a busy public place, near a hospital or a school.

Every cell is produced by running the real rule engine on a made-up complaint, so the guide can never disagree with
what the system actually does.
"""
try:
    from modules import rule_engine
except ImportError:                                  # when run directly
    import rule_engine

# (name shown, category, text, the level the classifier typically gives it: 0 low .. 3 critical)
PROBLEMS = [
    ("Cracks on the road", "Road", "cracks on the road surface", 0),
    ("Flickering streetlight", "Electricity", "flickering streetlight", 0),
    ("Pothole", "Road", "pothole", 1),
    ("Garbage not collected", "Sanitation", "garbage not collected", 1),
    ("Blocked drain", "Drainage", "blocked drain", 1),
    ("No water supply", "Water Supply", "no water supply", 2),
    ("Big pothole", "Road", "big pothole", 2),
    ("Open manhole", "Road", "open manhole on the road", 3),
    ("Live wire hanging low", "Electricity", "live wire hanging low", 3),
]
# (key, label, a place type to pretend the pin is near, or None)
PLACES = [("none", "Ordinary street", None), ("public", "Busy public place", "market"),
          ("hospital", "Near a hospital", "hospital"), ("school", "Near a school", "school")]
LEVELS = rule_engine.LEVELS


def decide(problem_name, place_type=None, duplicates=0, children=False, rules=None):
    """Run the engine for one problem at one kind of place. Returns the full rule-engine result."""
    for name, category, text, level in PROBLEMS:
        if name == problem_name:
            if children:
                text += ", children are affected"
            near = [{"name": "(example)", "type": place_type, "distance_m": 50.0}] if place_type else []
            facts = rule_engine.extract_facts(text, category, LEVELS[level], False,
                                              {"places_near": near, "duplicate_count": duplicates})
            return rule_engine.run(facts, rules)
    raise ValueError(f"unknown problem: {problem_name}")


def matrix(rules=None):
    """Rows of {'problem', 'none'|'public'|'hospital'|'school': {'priority', 'level', 'score'}}."""
    rows = []
    for name, _, _, _ in PROBLEMS:
        row = {"problem": name}
        for key, _, place in PLACES:
            res = decide(name, place, rules=rules)
            row[key] = {"priority": res["priority"], "level": res["priority_level"], "score": res["score"]}
        rows.append(row)
    return rows
