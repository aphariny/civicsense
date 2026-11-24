"""Tests for the CivicSense engine. Run:  python tests/test_pipeline.py   (or: pytest tests)"""
import datetime as dt
import os
import sys
import tempfile
import threading
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import Engine
from modules.scheduler import NOT_SCHEDULABLE

LAT, LON = 13.006, 80.206
_engines = []


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgs
PNG = imgs.png()
JPG = imgs.jpg()


def new_engine():
    folder = tempfile.mkdtemp()
    eng = Engine(db_path=os.path.join(folder, "test.db"), upload_dir=os.path.join(folder, "uploads"))
    _engines.append(eng)
    return eng


def test_submit_makes_a_complete_decision():
    e = new_engine()
    r = e.submit("Pothole near the temple on MG Road", LAT, LON)
    assert r["category"] == "Road" and r["department"] and r["priority"] in ("low", "medium", "high", "critical")
    assert r["trace"] and r["status"] == "open" and r["merged_into"] is None


def test_empty_text_is_rejected():
    e = new_engine()
    try:
        e.submit("   ", LAT, LON)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_duplicate_is_merged_and_many_duplicates_raise_priority():
    e = new_engine()
    first = e.submit("Garbage not collected near the market on Nehru Road", LAT, LON)
    before = e.get(first["id"])["priority_level"]
    ids = []
    for i in range(4):
        d = e.submit("Garbage not collected near the market, Nehru Road. Please look into it.", LAT + 0.0001 * i / 10, LON)
        assert d["merged_into"] == first["id"]
        ids.append(d["id"])
    after = e.get(first["id"])
    assert after["priority_level"] >= min(3, before + 1)
    assert any("duplicate" in f.lower() for f in after["flags"])
    assert all(e.get(i)["priority"] == after["priority"] for i in ids)       # duplicates share the decision


def test_same_issue_far_away_is_not_a_duplicate():
    e = new_engine()
    e.submit("Garbage not collected near the market on Nehru Road", LAT, LON)
    far = e.submit("Garbage not collected near the market on Nehru Road", LAT + 0.02, LON)
    assert far["merged_into"] is None


def test_low_confidence_goes_to_review_and_officer_can_fix_it():
    e = new_engine()
    r = e.submit("Pls fix it", LAT, LON)
    assert r["needs_review"] == 1 and r["department"] == NOT_SCHEDULABLE
    plan = e.plan()
    assert [x["id"] for x in plan["review"]] == [r["id"]] and not plan["jobs"]
    e.officer_correct(r["id"], "Road", "medium")
    fixed = e.get(r["id"])
    assert fixed["needs_review"] == 0 and fixed["department"] == "Public Works"
    assert len(e.plan()["jobs"]) == 1


def test_resolved_complaints_leave_the_plan():
    e = new_engine()
    a = e.submit("Streetlight not working in Gandhi Street for 3 days now", LAT, LON)
    e.submit("Pothole on Nehru Road near the market", LAT + 0.01, LON + 0.01)
    e.resolve(a["id"])
    assert [j.id for j in e.plan()["jobs"]] and a["id"] not in [j.id for j in e.plan()["jobs"]]


def test_recurring_problem_needs_two_earlier_complaints_at_the_same_place():
    e = new_engine()
    text = "Pothole near the temple on MG Road"
    first = e.submit(text, LAT, LON)
    e.resolve(first["id"])
    second = e.submit(text, LAT, LON)                  # one earlier complaint: not recurring yet (rule R36 needs 2)
    assert second["merged_into"] is None and not any("Recurring" in f for f in second["flags"])
    e.resolve(second["id"])
    third = e.submit(text, LAT, LON)                   # two earlier complaints: recurring
    assert third["merged_into"] is None and any("Recurring" in f for f in third["flags"])


def test_old_complaint_is_escalated():
    e = new_engine()
    created = (e.clock() - dt.timedelta(days=8)).isoformat(timespec="seconds")
    fresh = e.submit("Pothole on Nehru Road near the market", LAT, LON)
    old = e.submit("Pothole on Station Road near the bus stand", LAT + 0.02, LON + 0.02, created_at=created)
    assert any("7 days" in f for f in old["flags"]) and not any("7 days" in f for f in fresh["flags"])
    assert old["score"] > fresh["score"]


def test_fairness_is_not_applied_with_too_few_complaints():
    e = new_engine()
    r = e.submit("Pothole on Nehru Road near the market", LAT, LON)
    assert e._context(e.get(r["id"]))["ward_reporting_ratio"] == 1.0


def test_corrections_are_exported_for_retraining():
    e = new_engine()
    r = e.submit("Pls fix it", LAT, LON)
    e.officer_correct(r["id"], "Drainage", "high")
    path = os.path.join(tempfile.mkdtemp(), "corrections.csv")
    assert e.export_corrections(path) == 1
    lines = open(path, encoding="utf-8").read().strip().splitlines()
    assert lines[0] == "text,category,priority" and lines[1].startswith("Pls fix it,Drainage,high")


def test_works_from_another_thread():
    e = new_engine()
    out = {}
    t = threading.Thread(target=lambda: out.update(r=e.submit("Pothole on MG Road", LAT, LON)))
    t.start(); t.join()
    assert out["r"]["id"] == 1


def test_demo_data_and_plan():
    e = new_engine()
    n = e.seed_demo(n=25)
    assert n >= 25
    plan = e.plan()
    m = plan["metrics"]
    assert plan["jobs"] and all(j.department != NOT_SCHEDULABLE for j in plan["jobs"])
    assert 0 <= m["urgent_on_time"] <= m["urgent_total"] and m["served"] <= m["total"]
    assert e.stats()["frame"].shape[0] >= 25


def test_photo_is_saved_and_shown_with_its_complaint():
    e = new_engine()
    r = e.submit("Open manhole near the school", LAT, LON, photo=PNG)
    photos = e.photos_for(r["id"])
    assert len(photos) == 1 and os.path.exists(photos[0]["path"]) and photos[0]["path"].endswith(".png")
    assert open(photos[0]["path"], "rb").read() == PNG


def test_photo_from_a_merged_duplicate_appears_on_the_original():
    e = new_engine()
    first = e.submit("Garbage not collected near the market on Nehru Road", LAT, LON, photo=JPG)
    dup = e.submit("Garbage not collected near the market, Nehru Road. Please look into it.", LAT, LON, photo=PNG)
    assert dup["merged_into"] == first["id"]
    assert {p["id"] for p in e.photos_for(first["id"])} == {first["id"], dup["id"]}


def test_bad_photos_are_rejected_and_nothing_is_saved():
    e = new_engine()
    for bad in (b"not an image at all", b"<script>alert(1)</script>", b"GIF89a" + b"\x00" * 20, PNG + b"\x00" * (5 * 1024 * 1024)):
        try:
            e.submit("Pothole on MG Road", LAT, LON, photo=bad)
            raise AssertionError("expected ValueError")
        except ValueError:
            pass
    assert e.count() == 0


def test_reset_deletes_photos_too():
    e = new_engine()
    r = e.submit("Pothole on MG Road", LAT, LON, photo=JPG)
    path = e.photos_for(r["id"])[0]["path"]
    e.reset()
    assert not os.path.exists(path) and e.count() == 0


def test_old_database_without_photo_column_is_upgraded():
    import sqlite3
    import database
    path = os.path.join(tempfile.mkdtemp(), "old.db")
    old = sqlite3.connect(path)
    old.executescript("CREATE TABLE complaints (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, text TEXT NOT NULL,"
                      " lat REAL, lon REAL, ward INTEGER, category TEXT, category_conf REAL, ml_priority TEXT,"
                      " needs_review INTEGER DEFAULT 0, duplicate_of INTEGER, department TEXT, priority TEXT,"
                      " priority_level INTEGER, score REAL, flags TEXT DEFAULT '[]', trace TEXT DEFAULT '[]',"
                      " status TEXT DEFAULT 'open', resolved_at TEXT);"
                      "INSERT INTO complaints (created_at, text) VALUES ('2026-10-01T09:00:00', 'old complaint');")
    old.commit(); old.close()
    conn = database.connect(path)
    row = database.get(conn, 1)
    assert row["text"] == "old complaint" and row["photo_path"] is None
    assert row["tracking_code"] and row["tracking_code"].startswith("CS-")            # old complaints get a code too


def test_location_outside_the_service_area_is_rejected():
    e = new_engine()
    for lat, lon in ((28.6, 77.2), (13.2, 80.22), (13.02, 80.5), (float("nan"), 80.2), (None, None), ("abc", "def")):
        try:
            e.submit("Pothole on MG Road", lat, lon)
            raise AssertionError(f"expected ValueError for {lat},{lon}")
        except ValueError:
            pass
    assert e.count() == 0
    e.submit("Pothole on MG Road", 12.990, 80.190)          # the corners of the service area are inside
    e.submit("Pothole on MG Road", 13.050, 80.250)
    assert e.count() == 2


def test_every_demo_complaint_is_inside_the_service_area():
    import pandas as pd
    from modules.geo import in_service_area
    d = pd.read_csv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "complaints.csv"))
    assert all(in_service_area(a, b) for a, b in zip(d["lat"], d["lon"]))


def test_tracking_codes_are_unique_random_looking_and_readable():
    import re
    e = new_engine()
    codes = [e.submit(f"Pothole number {i} on MG Road", LAT + i * 0.001, LON)["tracking_code"] for i in range(30)]
    assert len(set(codes)) == 30 and all(re.fullmatch(r"CS-[A-HJ-NP-Z2-9]{8}", c) for c in codes)


def test_public_status_reveals_almost_nothing():
    e = new_engine()
    r = e.submit("Open manhole near the school, my name is Ravi and I live at 12 Gandhi Street", LAT, LON, photo=PNG)
    status = e.public_status(r["tracking_code"].lower())              # codes are not case sensitive
    assert set(status) == {"code", "submitted", "category", "stage", "stage_label", "resolved_on", "updates",
                           "has_after_photo", "can_give_feedback", "feedback_given"}
    dump = str(list(status.values()))                          # values only: a key may be called has_after_photo
    for secret in ("Ravi", "Gandhi", "manhole", str(LAT), str(LON), "photo", "complaint_"):
        assert secret not in dump
    assert e.public_status("CS-ZZZZZZZZ") is None and e.public_status("") is None and e.public_status(None) is None
    assert e.public_status("' OR 1=1 --") is None                      # a code is data, never SQL


def test_public_status_follows_the_complaint_through_its_stages():
    e = new_engine()
    vague = e.submit("Pls fix it", LAT, LON)
    assert e.public_status(vague["tracking_code"])["stage"] == 1
    e.officer_correct(vague["id"], "Road", "medium")
    assert e.public_status(vague["tracking_code"])["stage"] == 2
    e.resolve(vague["id"])
    done = e.public_status(vague["tracking_code"])
    assert done["stage"] == 4 and done["resolved_on"]


def test_a_merged_duplicate_reporter_sees_the_status_of_the_shared_issue():
    e = new_engine()
    first = e.submit("Garbage not collected near the market on Nehru Road", LAT, LON)
    dup = e.submit("Garbage not collected near the market, Nehru Road. Please look into it.", LAT, LON)
    assert dup["merged_into"] == first["id"] and dup["tracking_code"] != first["tracking_code"]
    e.resolve(first["id"])
    assert e.public_status(dup["tracking_code"])["stage"] == 4


def test_public_statistics_hide_small_wards_and_contain_no_text():
    e = new_engine()
    for i in range(4):
        e.submit(f"Pothole number {i} on Nehru Road", LAT + i * 0.002, LON)            # one ward, 4 complaints
    e.submit("Streetlight not working on Station Road", 13.04, 80.24)                  # a ward with 1 complaint
    stats = e.public_stats()
    assert stats["issues"] == 5 and stats["hidden_wards"] >= 1
    assert all(n >= 3 for n in stats["by_ward"].values())
    assert "Pothole" not in str(stats) and "Station" not in str(stats)


def test_officer_actions_are_audited_and_public_actions_are_not():
    import database
    e = new_engine()
    r = e.submit("Pls fix it", LAT, LON)
    assert database.audit_entries(e.db) == []                                          # submitting is public
    e.officer_correct(r["id"], "Road", "high", actor="officer1")
    e.resolve(r["id"], actor="officer1")
    e.resolve(r["id"])                                                                 # no actor: nothing logged
    log = database.audit_entries(e.db)
    assert [x["action"] for x in log] == ["resolve", "correct"] and all(x["username"] == "officer1" for x in log)
    assert log[1]["complaint_id"] == r["id"]


def test_reset_keeps_accounts_and_audit_history():
    import auth, database
    e = new_engine()
    auth.create_user(e.db, "admin", "long-enough-1", "admin")
    e.submit("Pothole on MG Road", LAT, LON)
    e.reset(actor="admin")
    assert e.count() == 0 and database.get_user(e.db, "admin") is not None
    assert [x["action"] for x in database.audit_entries(e.db)] == ["reset_database"]
    assert e.submit("Pothole on MG Road", LAT, LON)["id"] == 1                         # numbering restarts


def test_preview_saves_nothing_and_ignores_short_text():
    e = new_engine()
    assert e.preview("") is None and e.preview("pothole") is None and e.preview(None) is None
    p = e.preview("Open manhole near the government school on Gandhi Street")
    assert p["category"] == "Road" and p["department"] == "Public Works" and not p["needs_review"]
    assert e.preview("Pls fix it please now")["needs_review"] and e.count() == 0


def test_surge_adds_many_complaints_of_one_kind_and_is_audited():
    import database
    e = new_engine()
    e.seed_demo(n=20)
    before = len(e.plan()["jobs"])
    added = e.seed_surge(n=25, actor="admin")
    assert added == 25 and len(e.plan()["jobs"]) > before
    assert database.audit_entries(e.db)[0]["action"] == "simulate_surge"
    assert all(__import__("modules.geo", fromlist=["x"]).in_service_area(r["lat"], r["lon"]) for r in database.query(e.db))


def test_a_pin_next_to_a_school_raises_priority_even_when_the_words_do_not_say_so():
    from modules import places
    e = new_engine()
    school = next(p for p in places.all_places() if p["type"] == "school")
    text = "Pothole on Gandhi Street"
    far = e.submit(text, LAT, LON)                                           # more than 150 m from any place
    near = e.submit(text + " again", school["lat"] + 0.0002, school["lon"])
    assert near["priority_level"] > far["priority_level"] and near["score"] > far["score"]
    assert any(school["name"] in f for f in near["flags"]) and not any("Near " in f for f in far["flags"])


def test_a_busy_public_place_ranks_between_an_ordinary_street_and_a_school():
    from modules import places
    e = new_engine()
    market = next(p for p in places.all_places() if p["type"] == "market")
    school = next(p for p in places.all_places() if p["type"] == "school")
    text = "Garbage not collected for days"
    a = e.submit(text, LAT, LON)
    b = e.submit(text + " near here", market["lat"] + 0.0002, market["lon"])
    c = e.submit(text + " close by", school["lat"] + 0.0002, school["lon"])
    assert a["score"] < b["score"] < c["score"]


def test_ward_hotspots_rank_wards_by_urgency_and_count_places():
    from modules import places
    e = new_engine()
    assert e.ward_hotspots().empty and list(e.ward_hotspots().columns)[:2] == ["ward", "open"]
    school = next(p for p in places.all_places() if p["type"] == "school")
    for i in range(3):
        e.submit(f"Open manhole number {i} on Nehru Road", school["lat"] + 0.0001 * i, school["lon"] + 0.0004 * i)
    e.submit("Pothole on MG Road", 13.045, 80.245)
    table = e.ward_hotspots()
    assert table.iloc[0]["hotspot score"] >= table.iloc[-1]["hotspot score"]
    assert table["near school/hospital"].sum() >= 1 and table["open"].sum() == e.stats()["frame"].shape[0]


def test_road_lines_describe_the_road_network():
    e = new_engine()
    lines = e.road_lines()
    assert len(lines) == e.graph.g.number_of_edges() and all(len(l) == 2 and len(l[0]) == 2 for l in lines)


def test_reset_empties_the_database():
    e = new_engine()
    e.submit("Pothole on MG Road", LAT, LON)
    e.reset()
    assert e.stats()["frame"].empty


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
