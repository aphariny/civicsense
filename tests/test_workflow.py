"""Tests for abuse protection, closing the loop with citizens, and the field-crew workflow.
Run:  python tests/test_workflow.py   (or: pytest tests)"""
import datetime as dt
import io
import os
import sys
import tempfile
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auth
import database
import imgs
import pipeline
from modules import privacy
from pipeline import Engine

LAT, LON = 13.006, 80.206          # more than 150 m from every demo place
PNG, JPG = imgs.png(), imgs.jpg()


class Clock:
    def __init__(self):
        self.now = dt.datetime(2026, 11, 20, 9, 0, 0)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += dt.timedelta(**kw)


def new_engine(clock=None):
    folder = tempfile.mkdtemp()
    return Engine(db_path=os.path.join(folder, "t.db"), upload_dir=os.path.join(folder, "uploads"), clock=clock)


def dump_database(e):
    """Every text value stored anywhere in the database, so tests can prove something was never saved."""
    out = []
    for table in ("complaints", "events", "feedback", "audit_log"):
        for row in e.db.execute(f"SELECT * FROM {table}"):
            out.extend(str(v) for v in tuple(row))
    return "\n".join(out)


# ------------------------------------------------------------------ privacy and abuse
def test_personal_details_are_masked_before_anything_is_stored():
    e = new_engine()
    r = e.submit("Open manhole near the school. Call Ravi on 98765 43210 or ravi.k@example.com, aadhaar 1234 5678 9012", LAT, LON)
    assert "[phone removed]" in r["text"] and "[email removed]" in r["text"] and "[id number removed]" in r["text"]
    assert set(r["pii_removed"]) == {"phone number", "email", "id number"}
    stored = dump_database(e)
    for secret in ("98765", "43210", "ravi.k@example.com", "1234 5678 9012"):
        assert secret not in stored


def test_ordinary_numbers_are_not_mistaken_for_personal_details():
    for text in ("Pothole near 600028 on 12 Gandhi Street ward 12 since 2024, 3 days now", "Pothole at 13.0231, 80.2188 on MG Road",
                 "Complaint number 1234567 is still open after 14 days", "Road damaged for 2 km near plot 45/3"):
        masked, removed = privacy.mask_pii(text)
        assert masked == text and removed == [], text


def test_phone_number_formats_are_all_caught():
    for number in ("9876543210", "98765 43210", "98765-43210", "+91 98765 43210", "+919876543210", "09876543210", "044 2345 6789"):
        masked, removed = privacy.mask_pii(f"call {number} now")
        assert "[phone removed]" in masked and removed == ["phone number"], number


def test_clear_spam_is_refused_and_nothing_is_saved():
    e = new_engine()
    for spam in ("BUY NOW click here http://cheap-deals.xyz free money", "WINNER lottery claim at www.prizes.top", "x" * 1001):
        try:
            e.submit(spam, LAT, LON)
            raise AssertionError(f"expected ValueError for {spam[:30]!r}")
        except ValueError as err:
            assert "spam" in str(err) or "under 1000" in str(err)
    assert e.count() == 0


def test_doubtful_text_is_held_for_an_officer_and_never_scheduled():
    e = new_engine()
    r = e.submit("asdfghjkl qwrtpsd zxcvbnm pothole", LAT, LON)
    assert r["held"] and r["needs_review"] == 1 and r["department"] == "Control Room (manual review)"
    assert any("random typing" in f for f in r["flags"])
    plan = e.plan()
    assert [x["id"] for x in plan["review"]] == [r["id"]] and not plan["jobs"]
    assert e.public_status(r["tracking_code"])["stage"] == 1


def test_a_held_complaint_is_not_merged_into_a_real_one():
    e = new_engine()
    real = e.submit("Pothole on MG Road near the temple junction", LAT, LON)
    held = e.submit("asdfghjkl qwrtpsd zxcvbnm pothole MG Road", LAT, LON)
    assert held["merged_into"] is None and real["id"] != held["id"]


def test_one_visitor_cannot_flood_the_system_but_others_can_still_report():
    clock = Clock()
    e = new_engine(clock)
    for i in range(5):
        e.submit(f"Pothole number {i} near the old market on Nehru Road", LAT + i * 0.002, LON, client_key="visitor-a")
    try:
        e.submit("One pothole too many on Nehru Road", LAT + 0.02, LON, client_key="visitor-a")
        raise AssertionError("the sixth complaint should be refused")
    except privacy.RateLimitError as err:
        assert "wait" in str(err)
    assert e.count() == 5
    e.submit("A different visitor reports a leak on Station Road", LAT + 0.03, LON, client_key="visitor-b")
    clock.advance(minutes=11)
    e.submit("Visitor a is allowed again later, Canal Bank Road drain blocked", LAT + 0.025, LON + 0.02, client_key="visitor-a")


def test_a_flood_from_many_visitors_is_stopped_for_everyone():
    clock = Clock()
    e = new_engine(clock)
    old = pipeline.ALL_VISITORS_LIMIT
    pipeline.ALL_VISITORS_LIMIT = (4, 60)
    try:
        for i in range(4):
            e.submit(f"Pothole number {i} on Lake View Road", LAT + i * 0.003, LON, client_key=f"v{i}")
        try:
            e.submit("Pothole from yet another visitor on Park Avenue", LAT + 0.03, LON, client_key="v-new")
            raise AssertionError("the flood limit should apply to everybody")
        except privacy.RateLimitError:
            pass
        clock.advance(seconds=61)
        e.submit("After a minute things are back to normal on Park Avenue", LAT + 0.03, LON, client_key="v-new")
    finally:
        pipeline.ALL_VISITORS_LIMIT = old


def test_trusted_callers_without_a_client_key_are_not_limited():
    e = new_engine()
    for i in range(8):
        e.submit(f"Pothole number {i} on Gandhi Street near block {i}", LAT + i * 0.003, LON)
    assert e.count() == 8


def test_keyboard_mashing_is_caught_but_ordinary_complaints_are_not():
    import csv
    for mash in ("asdfghjkl qwrtpsd zxcvbnm", "asdfghjkl qwrtpsd zxcvbnm pothole MG Road", "qwertyuiop sdfghjkl zxcvbnm"):
        assert privacy.screen(mash)["action"] != "accept", mash
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    texts = [r["text"] for r in csv.DictReader(open(os.path.join(root, "data", "complaints.csv"), encoding="utf-8"))]
    texts += [r["text"] for r in csv.DictReader(open(os.path.join(root, "tests", "hard_cases.csv"), encoding="utf-8"))]
    flagged = [x for x in texts if privacy.screen(x)["action"] == "reject"]
    held = [x for x in texts if privacy.screen(x)["action"] == "review"]
    assert not flagged and len(held) <= 0.01 * len(texts), (flagged[:3], held[:3])   # real complaints are not treated as spam


# ------------------------------------------------------------------ photos
def test_photo_metadata_is_removed_before_the_photo_is_stored():
    from PIL import Image
    e = new_engine()
    tagged = imgs.jpg(tagged=True)
    assert b"SecretCameraMaker" in tagged
    r = e.submit("Pothole on MG Road with a photo", LAT, LON, photo=tagged)
    stored = open(e.photos_for(r["id"])[0]["path"], "rb").read()
    assert b"SecretCameraMaker" not in stored and b"SecretPhoneModel" not in stored
    img = Image.open(io.BytesIO(stored))
    assert len(img.getexif()) == 0 and img.size == (8, 8)


def test_png_and_jpeg_both_work_and_keep_their_pixels():
    from PIL import Image
    for data in (imgs.png(color=(10, 200, 30)), imgs.jpg(color=(10, 200, 30))):
        clean, ext = privacy.clean_photo(data)
        img = Image.open(io.BytesIO(clean)).convert("RGB")
        r, g, b = img.getpixel((4, 4))
        assert ext in ("png", "jpg") and g > 150 and r < 80


def test_things_that_are_not_photos_are_refused():
    big = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (5100, 5100), (1, 2, 3)).save(big, "PNG")                 # 26 million pixels
    gif = io.BytesIO()
    Image.new("RGB", (4, 4)).save(gif, "GIF")
    for bad in (b"hello", b"", PNG[:20], b"<script>alert(1)</script>", b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, gif.getvalue(), big.getvalue(),
                PNG + b"\x00" * (5 * 1024 * 1024)):
        try:
            privacy.clean_photo(bad)
            raise AssertionError(f"expected ValueError for {bad[:12]!r}")
        except ValueError:
            pass


# ------------------------------------------------------------------ status history, resolution and feedback
def messages(e, code):
    return [u["message"] for u in e.public_status(code)["updates"]]


def test_the_citizen_sees_the_whole_story_of_their_complaint():
    clock = Clock()
    e = new_engine(clock)
    r = e.submit("Pls fix it", LAT, LON)
    assert messages(e, r["tracking_code"]) == ["Received", "Waiting for an officer to review"]
    clock.advance(hours=1)
    e.officer_correct(r["id"], "Road", "medium", actor="officer")
    clock.advance(hours=2)
    e.resolve(r["id"], actor="officer", note="Filled the pothole and levelled the surface")
    msgs = messages(e, r["tracking_code"])
    assert msgs[:2] == ["Received", "Waiting for an officer to review"]
    assert "An officer reviewed your complaint" in msgs and "Routed to Public Works" in msgs
    assert msgs[-1] == "Resolved: Filled the pothole and levelled the surface"
    times = [u["when"] for u in e.public_status(r["tracking_code"])["updates"]]
    assert times == sorted(times) and times[0] == "2026-11-20 09:00"


def test_resolution_notes_cannot_leak_phone_numbers():
    e = new_engine()
    r = e.submit("Pothole on MG Road near the temple junction", LAT, LON)
    e.resolve(r["id"], actor="officer", note="Spoke to the resident on 98765 43210, fixed")
    assert "98765" not in dump_database(e) and "[phone removed]" in messages(e, r["tracking_code"])[-1]


def test_after_photo_is_shown_only_to_the_holder_of_the_code_and_only_when_resolved():
    e = new_engine()
    r = e.submit("Pothole on MG Road near the temple junction", LAT, LON)
    assert e.public_after_photo(r["tracking_code"]) is None
    e.resolve(r["id"], actor="officer", after_photo=imgs.jpg(tagged=True))
    path = e.public_after_photo(r["tracking_code"])
    assert path and os.path.exists(path) and b"SecretCameraMaker" not in open(path, "rb").read()
    assert e.public_status(r["tracking_code"])["has_after_photo"] is True
    assert e.public_after_photo("CS-ZZZZZZZZ") is None and e.public_after_photo(None) is None and e.public_after_photo("") is None


def test_a_bad_after_photo_leaves_the_complaint_open():
    e = new_engine()
    r = e.submit("Pothole on MG Road near the temple junction", LAT, LON)
    try:
        e.resolve(r["id"], actor="officer", after_photo=b"not an image")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert e.get(r["id"])["status"] == "open" and messages(e, r["tracking_code"])[-1] != "Resolved"


def test_feedback_is_only_possible_once_the_complaint_is_resolved_and_only_once():
    e = new_engine()
    r = e.submit("Pothole on MG Road near the temple junction", LAT, LON)
    code = r["tracking_code"]
    assert e.feedback_state(code) == (False, False)
    for args in ((True, 5), (False, 1)):
        try:
            e.submit_feedback(code, *args)
            raise AssertionError("feedback before resolution must be refused")
        except ValueError as err:
            assert "once the complaint has been resolved" in str(err)
    e.resolve(r["id"], actor="officer")
    assert e.feedback_state(code) == (True, False)
    for bad in (0, 6, 3.5, "5", None):
        try:
            e.submit_feedback(code, True, bad)
            raise AssertionError(f"rating {bad!r} should be refused")
        except ValueError:
            pass
    assert e.submit_feedback(code, True, 5, "Thank you") == {"reopened": False}
    assert e.feedback_state(code) == (False, True)
    try:
        e.submit_feedback(code, True, 4)
        raise AssertionError("a second answer for the same repair must be refused")
    except ValueError as err:
        assert "already" in str(err)
    try:
        e.submit_feedback("CS-ZZZZZZZZ", True, 5)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_saying_not_fixed_reopens_the_complaint_and_escalates_it():
    clock = Clock()
    e = new_engine(clock)
    r = e.submit("Garbage not collected near the old market on Nehru Road", LAT, LON)
    before = e.get(r["id"])
    e.resolve(r["id"], actor="officer", note="Cleared", after_photo=PNG)
    assert e.submit_feedback(r["tracking_code"], False, 1, "Rubbish is back")["reopened"] is True
    after = e.get(r["id"])
    assert after["status"] == "open" and after["reopened_count"] == 1 and after["resolution_note"] is None
    assert after["after_photo_path"] is None and e.public_after_photo(r["tracking_code"]) is None
    assert after["priority_level"] > before["priority_level"] and after["score"] > before["score"]
    assert any("Reopened" in f for f in after["flags"])
    assert e.public_status(r["tracking_code"])["stage"] == 2 and messages(e, r["tracking_code"])[-1].startswith("Reopened")
    assert r["id"] in [x["id"] for x in e.open_table().to_dict("records")] and e.open_table().iloc[0]["reopened"] == 1
    e.resolve(r["id"], actor="officer", note="Cleared again, bins added")           # a new repair, a new chance to give feedback
    assert e.feedback_state(r["tracking_code"]) == (True, False)
    assert e.submit_feedback(r["tracking_code"], True, 4)["reopened"] is False


def test_a_merged_reporter_can_reopen_the_shared_repair():
    e = new_engine()
    first = e.submit("Garbage not collected near the old market on Nehru Road", LAT, LON)
    dup = e.submit("Garbage not collected near the old market, Nehru Road. Please look into it.", LAT, LON)
    assert dup["merged_into"] == first["id"]
    e.resolve(first["id"], actor="officer")
    assert e.get(dup["id"])["status"] == "resolved"
    e.submit_feedback(dup["tracking_code"], False, 2)
    assert e.get(first["id"])["status"] == "open" and e.get(dup["id"])["status"] == "open" and e.get(first["id"])["reopened_count"] == 1


def test_feedback_comments_are_cleaned_limited_and_spam_checked():
    e = new_engine()
    r = e.submit("Pothole on MG Road near the temple junction", LAT, LON)
    e.resolve(r["id"], actor="officer")
    try:
        e.submit_feedback(r["tracking_code"], True, 5, "visit http://cheap-deals.xyz buy now free money")
        raise AssertionError("spam in a comment must be refused")
    except ValueError:
        pass
    e.submit_feedback(r["tracking_code"], True, 5, "Great work, call me on 98765 43210 " + "x" * 400)
    row = database.feedback_rows(e.db)[0]
    assert "98765" not in row["comment"] and len(row["comment"]) <= 300


def test_feedback_statistics():
    e = new_engine()
    ids = []
    for i, (fixed, rating) in enumerate([(True, 5), (True, 4), (False, 1)]):
        r = e.submit(f"Pothole number {i} on MG Road near gate {i}", LAT + i * 0.004, LON)
        e.resolve(r["id"], actor="officer")
        e.submit_feedback(r["tracking_code"], fixed, rating)
    s = e.feedback_stats()
    assert s["responses"] == 3 and abs(s["avg_rating"] - 10 / 3) < 1e-9 and abs(s["fixed_pct"] - 2 / 3) < 1e-9
    assert s["reopened"] == 1 and abs(s["reopen_rate"] - 1 / 3) < 1e-9 and "Public Works" in s["by_department"]
    assert e.feedback_stats()["responses"] == 3 and new_engine().feedback_stats()["avg_rating"] is None


def test_feedback_is_rate_limited_per_visitor():
    e = new_engine()
    old = pipeline.FEEDBACK_LIMIT
    pipeline.FEEDBACK_LIMIT = (2, 600)
    try:
        codes = []
        for i in range(3):
            r = e.submit(f"Pothole number {i} on MG Road near gate {i}", LAT + i * 0.004, LON)
            e.resolve(r["id"], actor="officer")
            codes.append(r["tracking_code"])
        e.submit_feedback(codes[0], True, 5, client_key="v")
        e.submit_feedback(codes[1], True, 5, client_key="v")
        try:
            e.submit_feedback(codes[2], True, 5, client_key="v")
            raise AssertionError("the third feedback should be limited")
        except privacy.RateLimitError:
            pass
        e.submit_feedback(codes[2], True, 5, client_key="someone-else")
    finally:
        pipeline.FEEDBACK_LIMIT = old


# ------------------------------------------------------------------ field crews
def seeded_engine():
    e = new_engine()
    e.seed_demo(n=30)
    return e


def test_crew_accounts_need_a_crew_id_and_have_narrow_permissions():
    path = os.path.join(tempfile.mkdtemp(), "a.db")
    conn = database.connect(path)
    for bad in (dict(role="crew"), dict(role="crew", crew_id="x"), dict(role="crew", crew_id="PW 1!"), dict(role="officer", crew_id="PW-1")):
        try:
            auth.create_user(conn, "someone", "long-enough-1", **bad)
            raise AssertionError(f"expected ValueError for {bad}")
        except ValueError:
            pass
    auth.create_user(conn, "crew1", "long-enough-1", "crew", crew_id="PW-1")
    user = auth.authenticate(conn, "crew1", "long-enough-1")
    assert user["role"] == "crew" and user["crew_id"] == "PW-1"
    assert auth.can(user, "crew_work")
    for perm in ("view", "review", "resolve", "reset", "seed", "manage_users", "export", "audit"):
        assert not auth.can(user, perm), perm
    assert database.list_users(conn)[0]["crew_id"] == "PW-1"


def test_each_crew_sees_only_its_own_route_and_together_they_cover_the_plan():
    e = seeded_engine()
    plan_ids = [s["job"].id for stops in e.plan()["result"]["routes"].values() for s in stops]
    seen = []
    for crew in e.crews:
        route = e.crew_route(crew.id)
        ids = [t["row"]["id"] for t in route["todo"]]
        assert [t["stop"] for t in route["todo"]] == list(range(1, len(ids) + 1))
        assert all(t["row"]["department"] == crew.department for t in route["todo"])
        seen += ids
    assert sorted(seen) == sorted(plan_ids) and len(seen) == len(set(seen))
    assert e.crew_route("NOPE-1") == {"todo": [], "in_progress": []}


def test_starting_a_job_moves_it_off_the_schedule_and_tells_the_citizen():
    e = seeded_engine()
    crew = next(c for c in e.crews if e.crew_route(c.id)["todo"])
    job = e.crew_route(crew.id)["todo"][0]["row"]
    e.crew_start(job["id"], crew.id, actor="crew1")
    route = e.crew_route(crew.id)
    assert job["id"] not in [t["row"]["id"] for t in route["todo"]] and [r["id"] for r in route["in_progress"]] == [job["id"]]
    assert e.get(job["id"])["status"] == "in_progress" and e.get(job["id"])["assigned_crew"] == crew.id
    assert job["id"] not in [j.id for j in e.plan()["jobs"]]
    assert e.public_status(e.get(job["id"])["tracking_code"])["stage"] == 3
    assert database.audit_entries(e.db)[0]["action"] == "start_work"
    try:
        e.crew_start(job["id"], crew.id, actor="crew1")
        raise AssertionError("a job cannot be started twice")
    except ValueError:
        pass


def test_a_crew_finishes_a_job_with_a_note_and_a_photo():
    e = seeded_engine()
    crew = next(c for c in e.crews if e.crew_route(c.id)["todo"])
    job = e.crew_route(crew.id)["todo"][0]["row"]
    e.crew_start(job["id"], crew.id, actor="crew1")
    e.crew_finish(job["id"], crew.id, actor="crew1", note="Repaired and cleaned", after_photo=JPG)
    row = e.get(job["id"])
    assert row["status"] == "resolved" and row["resolution_note"] == "Repaired and cleaned"
    assert e.public_after_photo(row["tracking_code"]) and e.crew_route(crew.id)["in_progress"] == []
    assert [a["action"] for a in database.audit_entries(e.db)[:2]] == ["resolve", "start_work"]
    assert all(a["username"] == "crew1" for a in database.audit_entries(e.db)[:2])


def test_a_crew_cannot_touch_another_crews_jobs():
    e = seeded_engine()
    busy = [c for c in e.crews if e.crew_route(c.id)["todo"]]
    mine, other = busy[0], busy[1]
    foreign = e.crew_route(other.id)["todo"][0]["row"]
    before = dict(e.get(foreign["id"]))
    for action in (lambda: e.crew_start(foreign["id"], mine.id, "crew1"), lambda: e.crew_finish(foreign["id"], mine.id, "crew1", note="x")):
        try:
            action()
            raise AssertionError("a crew must not act on another crew's job")
        except PermissionError:
            pass
    assert e.get(foreign["id"])["status"] == before["status"] == "open"
    try:
        e.crew_finish(999999, mine.id, "crew1")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_a_new_report_still_merges_into_a_job_that_is_already_in_progress():
    e = new_engine()
    first = e.submit("Garbage not collected near the old market on Nehru Road", LAT, LON)
    crew = next(c for c in e.crews if first["id"] in [t["row"]["id"] for t in e.crew_route(c.id)["todo"]])   # the crew it was given to
    e.crew_start(first["id"], crew.id, actor="crew1")
    dup = e.submit("Garbage not collected near the old market, Nehru Road. Please look into it.", LAT, LON)
    assert dup["merged_into"] == first["id"]
    assert e.get(dup["id"])["status"] == "in_progress" and e.get(dup["id"])["assigned_crew"] == crew.id
    assert e.public_status(dup["tracking_code"])["stage"] == 3


def test_officers_can_still_resolve_any_complaint():
    e = seeded_engine()
    cid = int(e.open_table().iloc[0]["id"])
    e.resolve(cid, actor="officer", note="Handled directly")
    assert e.get(cid)["status"] == "resolved"
    e.resolve(cid, actor="officer", note="again")                                  # resolving twice changes nothing
    assert e.get(cid)["resolution_note"] == "Handled directly"


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
