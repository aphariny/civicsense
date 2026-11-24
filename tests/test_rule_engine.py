"""Tests for Module 2. Run:  python tests/test_rule_engine.py   (or: pytest tests)"""
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules import rule_engine as re_


def go(text, category, ml="medium", review=False, **ctx):
    return re_.run(re_.extract_facts(text, category, ml, review, ctx))


def test_manhole_near_school_is_critical_and_public_works():
    r = go("Open manhole near the government school", "Road")
    assert r["department"] == "Public Works" and r["priority"] == "critical"


def test_low_confidence_goes_to_human_review():
    r = go("Pls fix it", "Electricity", review=True)
    assert r["department"] == "Control Room (manual review)"
    assert any("not confident" in f for f in r["flags"])


def test_default_routing_for_each_category():
    expected = {"Road": "Public Works", "Sanitation": "Sanitation Department", "Electricity": "Electricity Board",
                "Water Supply": "Water Supply Board", "Drainage": "Drainage & Sewerage"}
    for cat, dept in expected.items():
        assert go("something is broken", cat, "low")["department"] == dept


def test_medical_waste_goes_to_health_department():
    r = go("Medical waste dumped openly on Park Avenue", "Sanitation", "high")
    assert r["department"] == "Health Department" and r["priority"] in ("high", "critical")


def test_contaminated_water_flags_health_notification():
    r = go("contaminated water making people ill", "Water Supply")
    assert r["priority"] in ("high", "critical")
    assert any("Health Department" in f for f in r["flags"])


def test_many_duplicates_raise_priority_one_level():
    base = go("Garbage not collected on Nehru Road", "Sanitation", "medium")
    more = go("Garbage not collected on Nehru Road", "Sanitation", "medium", duplicate_count=4)
    assert (base["priority"], more["priority"]) == ("medium", "high")


def test_priority_never_goes_down():
    r = go("Cracks on the road surface", "Road", "critical")
    assert r["priority"] == "critical"


def test_priority_capped_at_critical():
    r = go("Live wire hanging near the hospital, a child almost fell", "Electricity", "critical",
           duplicate_count=9, age_days=30)
    assert r["priority"] == "critical"


def test_fairness_boost_for_under_reporting_ward():
    normal = go("Pothole on MG Road", "Road", ward_reporting_ratio=1.0)
    under = go("Pothole on MG Road", "Road", ward_reporting_ratio=0.5)
    assert under["score"] == normal["score"] + 5 and under["priority"] == normal["priority"]


def test_ward_reporting_ratio():
    pop = {1: 100, 2: 100}
    assert re_.ward_reporting_ratio(1, {1: 30, 2: 70}, pop) < 1 < re_.ward_reporting_ratio(2, {1: 30, 2: 70}, pop)


def test_each_rule_fires_at_most_once():
    r = go("Open manhole near the school", "Road", duplicate_count=5, age_days=10, repeat_count=3)
    ids = [t["rule"] for t in r["trace"]]
    assert len(ids) == len(set(ids))


def test_higher_salience_rule_fires_first():
    r = go("Open manhole near the school", "Road")
    ids = [t["rule"] for t in r["trace"]]
    assert ids.index("R22") < ids.index("R90")


def test_chaining_derived_fact_is_used_by_later_rule():
    r = go("Open manhole near the school", "Road", "low")
    ids = [t["rule"] for t in r["trace"]]
    assert ids.index("R10") < ids.index("R31")           # derived fact before the rule that needs it


def test_trace_explains_every_step():
    r = go("Pothole near the school", "Road")
    assert all(t["why"] and t["name"] for t in r["trace"]) and re_.explain(r)


def test_public_places_raise_priority_but_less_than_schools():
    plain = go("Pothole on Gandhi Street", "Road")
    market = go("Pothole near the market", "Road")
    school = go("Pothole near the government school", "Road")
    assert (plain["priority"], market["priority"], school["priority"]) == ("medium", "high", "high")
    assert plain["score"] < market["score"] < school["score"]                   # ranking among equals


def test_life_safety_risk_in_a_crowd_is_critical():
    for place in ("market", "bus stand", "railway station", "temple", "park"):
        assert go(f"Open manhole near the {place}", "Road")["priority"] == "critical", place
    assert go("Open manhole on Gandhi Street", "Road")["priority"] == "high"       # same hazard, quiet street


def test_low_priority_problems_stay_low_in_public_places_without_a_hazard():
    assert go("Cracks on the road surface near the market", "Road", "low")["priority"] == "low"


def test_street_names_are_not_places():
    for text in ("Garbage not collected at Temple Street", "Pothole at Park Avenue", "Garbage near Station Road"):
        assert go(text, "Sanitation")["priority"] == "medium", text
    assert go("Garbage not collected at the temple", "Sanitation")["priority"] == "high"


def test_a_pin_near_a_place_counts_even_when_the_words_do_not_mention_it():
    near = [{"name": "Lake View School", "type": "school", "distance_m": 60.0}]
    assert go("Pothole on Gandhi Street", "Road", places_near=near)["priority"] == "high"
    assert go("Pothole on Gandhi Street", "Road", places_near=[])["priority"] == "medium"
    crowd = [{"name": "Central Market", "type": "market", "distance_m": 40.0}]
    assert go("Open manhole on Gandhi Street", "Road", places_near=crowd)["priority"] == "critical"


def test_every_problem_ranks_the_same_way_across_places():
    """For any problem: ordinary street <= busy public place <= school, in both priority and score."""
    from modules import guide
    for row in guide.matrix():
        none, public, school = row["none"], row["public"], row["school"]
        assert none["level"] <= public["level"] <= school["level"], row["problem"]
        assert none["score"] < public["score"] < school["score"], row["problem"]


def test_place_type_lists_agree_between_modules():
    from modules import places
    assert re_.PUBLIC_PLACE_TYPES == places.PUBLIC and re_.SCHOOL_TYPES | re_.HOSPITAL_TYPES == places.SENSITIVE


def test_bad_rule_file_gives_clear_error():
    bad = "rules:\n  - {id: X1, name: bad, salience: 1, when: [{fact: a, op: eq, value: 1}], then: {explode: true}}\n"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(bad)
    try:
        re_.load_rules(f.name)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "unknown action" in str(e)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print("PASS", name)
        except AssertionError as e:
            failed += 1; print("FAIL", name, e)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
