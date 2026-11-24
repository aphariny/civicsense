"""Tests for places and the priority guide. Run:  python tests/test_places.py   (or: pytest tests)"""
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules import guide, places
from modules.geo import in_service_area


def test_every_place_is_valid_and_inside_the_service_area():
    data = places.load_places()
    assert len(data) >= 15 and {p["type"] for p in data} == places.SENSITIVE | places.PUBLIC
    assert all(in_service_area(p["lat"], p["lon"]) for p in data)
    assert len({p["name"] for p in data}) == len(data)


def test_near_finds_places_nearest_first_and_respects_the_radius():
    school = next(p for p in places.all_places() if p["type"] == "school")
    found = places.near(school["lat"] + 0.0003, school["lon"])             # about 33 m away
    assert found[0]["name"] == school["name"] and found[0]["distance_m"] < 60
    assert all(a["distance_m"] <= b["distance_m"] for a, b in zip(found, found[1:]))
    assert places.near(school["lat"] + 0.05, school["lon"]) == []
    assert places.near(school["lat"] + 0.002, school["lon"], radius_m=50) == []       # 220 m away is not near


def test_a_bad_places_file_gives_a_clear_error():
    bad = {"type: bank": "places:\n  - {name: A, type: bank, lat: 13.0, lon: 80.2}\n",
           "outside": "places:\n  - {name: A, type: school, lat: 28.6, lon: 77.2}\n",
           "missing field": "places:\n  - {name: A, type: school, lat: 13.0}\n"}
    for label, text in bad.items():
        path = os.path.join(tempfile.mkdtemp(), "p.yaml")
        open(path, "w").write(text)
        try:
            places.load_places(path)
            raise AssertionError(f"expected ValueError for {label}")
        except ValueError:
            pass


def test_guide_matrix_covers_every_problem_and_place():
    rows = guide.matrix()
    assert [r["problem"] for r in rows] == [p[0] for p in guide.PROBLEMS]
    for r in rows:
        assert set(r) == {"problem", "none", "public", "hospital", "school"}
        assert all(r[k]["priority"] in guide.LEVELS for k in ("none", "public", "hospital", "school"))


def test_guide_examples_match_what_people_expect():
    by = {r["problem"]: r for r in guide.matrix()}
    assert by["Pothole"]["none"]["priority"] == "medium" and by["Pothole"]["school"]["priority"] == "high"
    assert all(by["Open manhole"][k]["priority"] == "critical" for k in ("none", "public", "hospital", "school"))
    assert by["No water supply"]["none"]["priority"] == by["No water supply"]["public"]["priority"] == "high"   # already high:
    assert by["No water supply"]["none"]["score"] < by["No water supply"]["public"]["score"]                    # only the ranking moves
    assert by["Cracks on the road"]["public"]["priority"] == "low"          # no hazard, so a crowd alone does not escalate


def test_guide_decide_explains_itself_and_reacts_to_extras():
    plain = guide.decide("Pothole")
    crowded = guide.decide("Pothole", "market", duplicates=3, children=True)
    assert crowded["score"] > plain["score"] and crowded["priority_level"] > plain["priority_level"]
    assert any(t["rule"] == "R38" for t in crowded["trace"]) and any(t["rule"] == "R34" for t in crowded["trace"])
    try:
        guide.decide("Not a problem")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print("PASS", name)
        except Exception as e:
            failed += 1; print("FAIL", name, type(e).__name__, e)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
