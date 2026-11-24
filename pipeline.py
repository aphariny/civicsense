"""CivicSense engine: ties Module 1 (classify), Module 2 (rules) and Module 3 (schedule) to a database.

The Streamlit dashboard (app.py) only calls this class, so everything here can be tested without a browser.
"""
import csv
import datetime as dt
import json
import os
import random
import sys
from collections import Counter

import pandas as pd

import database
from modules import classifier, places, privacy, rule_engine, scheduler
from modules.duplicates import DuplicateDetector
from modules.geo import in_service_area, nearest_ward

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = database.DEFAULT_PATH
MIN_COMPLAINTS_FOR_FAIRNESS = 30     # below this, ward complaint shares are too noisy to act on
SHIFT_START_HOUR = 8
UPLOAD_DIR = os.path.join(ROOT, "uploads")
SUBMIT_LIMIT = (5, 600)        # complaints per visitor per 10 minutes
FEEDBACK_LIMIT = (5, 600)
ALL_VISITORS_LIMIT = (120, 60)  # complaints from everybody together per minute (flood protection)
STAGES_PUBLIC = ["Received", "Routed to a department", "Work started", "Resolved"]


class Engine:
    def __init__(self, db_path=DB_PATH, clock=None, upload_dir=UPLOAD_DIR):
        self.db = database.connect(db_path)
        self.upload_dir = upload_dir
        self.clock = clock or dt.datetime.now
        self.limiter = privacy.RateLimiter()
        if not os.path.exists(classifier.MODEL_PATH):
            classifier.train()
        corpus = pd.read_csv(os.path.join(ROOT, "data", "complaints.csv"))["text"]
        self.detector = DuplicateDetector().fit(corpus)
        self.rules = rule_engine.load_rules()
        self.ward_pop = rule_engine.load_ward_population()
        self.graph = scheduler.RoadGraph()
        self.crews = scheduler.load_crews(self.graph)

    # ------------------------------------------------------------ helpers
    def _roots(self, status=None):
        """Complaints that are not duplicates of another one.

        'open' means still active (open or being worked on), 'todo' means open and not yet started,
        anything else is an exact status such as 'resolved'.
        """
        if status == "open":
            return database.query(self.db, "duplicate_of IS NULL AND status IN ('open', 'in_progress')")
        if status == "todo":
            return database.query(self.db, "duplicate_of IS NULL AND status='open'")
        if status:
            return database.query(self.db, "duplicate_of IS NULL AND status=?", (status,))
        return database.query(self.db, "duplicate_of IS NULL")

    def _event(self, cid, kind, message):
        """A line in the complaint's public status history."""
        database.add_event(self.db, cid, self.clock().isoformat(timespec="seconds"), kind, message)

    @staticmethod
    def _frame(rows):
        return pd.DataFrame([{"complaint_id": r["id"], "text": r["text"], "lat": r["lat"], "lon": r["lon"]}
                             for r in rows], columns=["complaint_id", "text", "lat", "lon"])

    def get(self, cid):
        return database.get(self.db, cid)

    def _context(self, row):
        """Everything the rules need to know that is not in the complaint text."""
        age = max(0, (self.clock() - dt.datetime.fromisoformat(row["created_at"])).days)
        dups = len(database.query(self.db, "duplicate_of=?", (row["id"],)))
        resolved = self._frame(self._roots("resolved"))
        repeats = [m for m in self.detector.find_all(row["text"], row["lat"], row["lon"], resolved) if m[0] != row["id"]]
        roots = self._roots()
        ratio = 1.0
        if len(roots) >= MIN_COMPLAINTS_FOR_FAIRNESS:
            ratio = rule_engine.ward_reporting_ratio(row["ward"], Counter(r["ward"] for r in roots), self.ward_pop)
        return {"duplicate_count": dups, "repeat_count": len(repeats), "age_days": age, "ward_reporting_ratio": ratio,
                "places_near": places.near(row["lat"], row["lon"]), "reopened_count": row["reopened_count"] or 0}

    # ------------------------------------------------------------ decisions
    def reevaluate(self, cid):
        """Run the rule engine again (new duplicates, a longer wait, an officer correction...)."""
        row = database.get(self.db, cid)
        ctx = self._context(row)
        res = rule_engine.run(rule_engine.extract_facts(row["text"], row["category"], row["ml_priority"],
                                                        bool(row["needs_review"]), ctx), self.rules)
        notes = [f"Near {p['name']} ({places.LABELS[p['type']]}, {p['distance_m']:.0f} m from the pin)"
                 for p in ctx["places_near"][:3]]
        decision = dict(department=res["department"], priority=res["priority"], priority_level=res["priority_level"],
                        score=res["score"], flags=res["flags"] + notes + ([row["screen_note"]] if row["screen_note"] else []),
                        trace=res["trace"])
        database.update(self.db, cid, **decision)
        for dup in database.query(self.db, "duplicate_of=?", (cid,)):     # duplicates share the decision
            database.update(self.db, dup["id"], department=res["department"], priority=res["priority"],
                            priority_level=res["priority_level"], score=res["score"])
        return res

    def reevaluate_all(self):
        for r in self._roots("open"):
            self.reevaluate(r["id"])

    def submit(self, text, lat, lon, ward=None, created_at=None, photo=None, client_key=None):
        """Register a complaint.

        Personal details in the text are masked, spam is refused or held for an officer, photo metadata is stripped,
        and if client_key is given the visitor is rate limited. The photo is kept as evidence; the AI reads the text only.
        """
        if not in_service_area(lat, lon):
            raise ValueError("This location is outside the area CivicSense serves. Please choose a place on the map.")
        screened = privacy.screen(text)
        if not screened["text"]:
            raise ValueError("The complaint text is empty")
        if screened["action"] == "reject":
            raise ValueError(screened["message"])
        photo_bytes, photo_ext = privacy.clean_photo(photo) if photo else (None, None)   # reject bad photos before saving anything
        if client_key is not None:
            now = self.clock()
            self.limiter.hit(client_key, "submit", *SUBMIT_LIMIT, now)
            self.limiter.hit("*", "submit_all", *ALL_VISITORS_LIMIT, now)
        text = screened["text"]
        ml = classifier.predict(text)
        held = screened["action"] == "review"
        match = None if held else self.detector.find(text, lat, lon, self._frame(self._roots("open")))
        root = database.get(self.db, match[0]) if match else None
        cid = database.insert(
            self.db, created_at=created_at or self.clock().isoformat(timespec="seconds"), text=text,
            lat=lat, lon=lon, ward=ward or nearest_ward(lat, lon), category=ml["category"],
            category_conf=ml["category_conf"], ml_priority=ml["priority"], needs_review=int(ml["needs_review"] or held),
            duplicate_of=match[0] if match else None, status=root["status"] if root else "open",
            assigned_crew=root["assigned_crew"] if root else None,
            screen_note=("Held for an officer: " + ", ".join(screened["reasons"])) if held else None)
        if photo:
            os.makedirs(self.upload_dir, exist_ok=True)
            name = f"complaint_{cid}.{photo_ext}"                    # our own file name, never the uploader's
            with open(os.path.join(self.upload_dir, name), "wb") as f:
                f.write(photo_bytes)
            database.update(self.db, cid, photo_path=name)
        self.reevaluate(match[0] if match else cid)
        out = self.get(cid)
        self._event(cid, "received", "Received" + (" and added to an existing report of the same problem" if match else ""))
        self._event(cid, "review" if out["needs_review"] else "routed",
                    "Waiting for an officer to review" if out["needs_review"] else f"Routed to {out['department']}")
        out["merged_into"], out["similarity"] = (match[0], match[1]) if match else (None, None)
        out["pii_removed"], out["held"] = screened["pii_removed"], held
        return out

    def audit(self, actor, action, cid=None, detail=""):
        """Record who did what. Only officer actions have an actor."""
        if actor:
            database.log_audit(self.db, self.clock().isoformat(timespec="seconds"), actor, action, cid, detail)

    def officer_correct(self, cid, category, priority, actor=None):
        """An officer confirms the category and priority. The correction is saved for retraining."""
        row = database.get(self.db, cid)
        database.update(self.db, cid, category=category, category_conf=1.0, ml_priority=priority, needs_review=0)
        database.add_correction(self.db, row["text"], category, priority, self.clock().isoformat(timespec="seconds"))
        self.audit(actor, "correct", cid, f"category={category}, priority={priority}")
        result = self.reevaluate(cid)
        self._event(cid, "review", "An officer reviewed your complaint")
        self._event(cid, "routed", f"Routed to {result['department']}")
        return result

    def export_corrections(self, path=classifier.CORRECTIONS_PATH, actor=None):
        """Write officer corrections to data/corrections.csv; classifier.py includes them when retraining."""
        rows = database.corrections(self.db)
        self.audit(actor, "export_corrections", detail=f"{len(rows)} corrections")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["text", "category", "priority"])
            w.writeheader()
            w.writerows({k: r[k] for k in ("text", "category", "priority")} for r in rows)
        return len(rows)

    def _root_of(self, cid):
        row = database.get(self.db, cid)
        if row is None:
            raise ValueError("Unknown complaint")
        return database.get(self.db, row["duplicate_of"]) if row["duplicate_of"] else row

    def _group(self, root):
        return [root] + database.query(self.db, "duplicate_of=?", (root["id"],))

    def resolve(self, cid, actor=None, note=None, after_photo=None):
        """Close a complaint (and the duplicate reports merged into it), with an optional note and 'after' photo."""
        root = self._root_of(cid)
        if root["status"] == "resolved":
            return
        note = privacy.mask_pii(privacy.clean_text(note))[0][:300] if note else None
        photo_bytes = photo_ext = None
        if after_photo:
            photo_bytes, photo_ext = privacy.clean_photo(after_photo)             # reject a bad photo before changing anything
        now = self.clock().isoformat(timespec="seconds")
        fields = {"status": "resolved", "resolved_at": now}
        if photo_bytes:
            os.makedirs(self.upload_dir, exist_ok=True)
            name = f"after_{root['id']}.{photo_ext}"
            with open(os.path.join(self.upload_dir, name), "wb") as f:
                f.write(photo_bytes)
            fields["after_photo_path"] = name
        self.audit(actor, "resolve", root["id"], note or "")
        for r in self._group(root):
            database.update(self.db, r["id"], **fields, **({"resolution_note": note} if r["id"] == root["id"] else {}))
            self._event(r["id"], "resolved", "Resolved" + (f": {note}" if note else ""))

    def start_work(self, cid, actor=None, crew_id=None):
        """A crew starts on a complaint: it leaves the schedule and shows as 'work started' to the citizen."""
        root = self._root_of(cid)
        if root["status"] != "open":
            raise ValueError("Only an open complaint can be started")
        for r in self._group(root):
            database.update(self.db, r["id"], status="in_progress", assigned_crew=crew_id)
        self._event(root["id"], "in_progress", "Work has started: a crew is dealing with it")
        for r in self._group(root)[1:]:
            self._event(r["id"], "in_progress", "Work has started: a crew is dealing with it")
        self.audit(actor, "start_work", root["id"], f"crew {crew_id}" if crew_id else "")

    def crew_route(self, crew_id):
        """What one crew sees: its scheduled stops (in order) and the jobs it has already started."""
        plan = self.plan()
        todo = []
        for n, stop in enumerate(plan["result"]["routes"].get(crew_id, []), 1):
            job = stop["job"]
            todo.append({"stop": n, "arrive": stop["arrive"], "deadline": job.deadline, "late": stop["late"],
                         "row": self.get(job.id), "minutes_service": job.service})
        started = [r for r in self._roots("open") if r["status"] == "in_progress" and r["assigned_crew"] == crew_id]
        return {"todo": todo, "in_progress": started}

    def _crew_owns(self, cid, crew_id):
        root = self._root_of(cid)
        route = self.crew_route(crew_id)
        if root["id"] not in {t["row"]["id"] for t in route["todo"]} | {r["id"] for r in route["in_progress"]}:
            raise PermissionError("That job is not on your route")
        return root

    def crew_start(self, cid, crew_id, actor):
        root = self._crew_owns(cid, crew_id)
        self.start_work(root["id"], actor=actor, crew_id=crew_id)

    def crew_finish(self, cid, crew_id, actor, note=None, after_photo=None):
        root = self._crew_owns(cid, crew_id)
        self.resolve(root["id"], actor=actor, note=note, after_photo=after_photo)

    # ------------------------------------------------------------ closing the loop with the citizen
    def submit_feedback(self, code, fixed, rating, comment="", client_key=None):
        """The citizen says whether the repair worked. 'Not fixed' reopens the complaint."""
        code = (code or "").strip().upper()
        rows = database.query(self.db, "tracking_code=?", (code,)) if code else []
        if not rows:
            raise ValueError("We could not find that code")
        row = rows[0]
        root = self._root_of(row["id"])
        if root["status"] != "resolved":
            raise ValueError("You can leave feedback once the complaint has been resolved")
        cycle = root["reopened_count"] or 0
        if database.feedback_given(self.db, row["id"], cycle):
            raise ValueError("You have already given feedback on this repair")
        if rating not in (1, 2, 3, 4, 5):
            raise ValueError("Please choose a rating from 1 to 5")
        screened = privacy.screen(comment) if comment else {"text": "", "action": "accept", "message": ""}
        if screened["action"] == "reject":
            raise ValueError(screened["message"])
        if client_key is not None:
            self.limiter.hit(client_key, "feedback", *FEEDBACK_LIMIT, self.clock())
        now = self.clock().isoformat(timespec="seconds")
        database.add_feedback(self.db, row["id"], now, cycle, bool(fixed), rating, screened["text"][:300])
        if not fixed:
            for r in self._group(root):
                database.update(self.db, r["id"], status="open", resolved_at=None, assigned_crew=None)
                self._event(r["id"], "reopened", "Reopened: you told us the problem was not fixed")
            database.update(self.db, root["id"], reopened_count=cycle + 1, resolution_note=None, after_photo_path=None)
            self.reevaluate(root["id"])
        return {"reopened": not fixed}

    def feedback_state(self, code):
        """(can give feedback now, has already given it) for the current repair."""
        rows = database.query(self.db, "tracking_code=?", ((code or "").strip().upper(),))
        if not rows:
            return False, False
        root = self._root_of(rows[0]["id"])
        given = database.feedback_given(self.db, rows[0]["id"], root["reopened_count"] or 0)
        return root["status"] == "resolved" and not given, given

    def feedback_stats(self):
        """Satisfaction figures for officers: ratings, how many said 'fixed', reopen rate, by department."""
        rows = database.feedback_rows(self.db)
        roots = self._roots()
        reopened = sum(1 for r in roots if (r["reopened_count"] or 0) > 0)
        resolved_ever = sum(1 for r in roots if r["status"] == "resolved" or (r["reopened_count"] or 0) > 0)
        by_dept = {}
        for r in rows:
            by_dept.setdefault(r["department"], []).append(r["rating"])
        return {"responses": len(rows), "avg_rating": sum(r["rating"] for r in rows) / len(rows) if rows else None,
                "fixed_pct": sum(r["fixed"] for r in rows) / len(rows) if rows else None,
                "reopened": reopened, "reopen_rate": reopened / resolved_ever if resolved_ever else 0.0,
                "by_department": {d: sum(v) / len(v) for d, v in sorted(by_dept.items())}}

    def public_after_photo(self, code):
        """The 'after' photo of the repair, for the person holding the tracking code (None if there is none)."""
        rows = database.query(self.db, "tracking_code=?", ((code or "").strip().upper(),))
        if not rows:
            return None
        root = self._root_of(rows[0]["id"])
        if root["status"] != "resolved" or not root["after_photo_path"]:
            return None
        path = os.path.join(self.upload_dir, root["after_photo_path"])
        return path if os.path.exists(path) else None

    # ------------------------------------------------------------ scheduling
    def plan(self):
        """Schedule every open complaint with Module 3 and compare with first-come-first-served."""
        jobs, review = [], []
        for r in self._roots("todo"):
            job = scheduler.make_job(r["id"], r["lat"], r["lon"], {"department": r["department"],
                                     "priority_level": r["priority_level"], "score": r["score"]},
                                     self.graph, arrival=r["id"])
            (jobs if job else review).append(job or r)
        mine = scheduler.schedule(self.graph, jobs, self.crews)
        base = scheduler.schedule_fcfs(self.graph, jobs, self.crews)
        return {"result": mine, "baseline": base, "review": review, "jobs": jobs,
                "metrics": scheduler.metrics(self.graph, mine, jobs, self.crews),
                "baseline_metrics": scheduler.metrics(self.graph, base, jobs, self.crews)}

    @staticmethod
    def clock_time(minutes):
        t = dt.datetime(2000, 1, 1, SHIFT_START_HOUR) + dt.timedelta(minutes=round(minutes))
        return t.strftime("%H:%M")

    # ------------------------------------------------------------ demo data and statistics
    def seed_demo(self, n=60, seed=0, actor=None):
        """Fill the database with sample complaints of different ages, some already resolved."""
        self.audit(actor, "load_demo_data", detail=f"{n} complaints")
        rng = random.Random(seed)
        data = pd.read_csv(os.path.join(ROOT, "data", "complaints.csv"))
        roots = data[data["duplicate_of"].isna()].sample(n, random_state=seed)
        items = []
        for r in roots.itertuples():
            age = rng.choice([0, 0, 1, 1, 2, 3, 5, 8, 10])
            created = self.clock() - dt.timedelta(days=age, hours=rng.randint(0, 6))
            items.append((created, r.text, r.lat, r.lon, age))
            for d in data[data["duplicate_of"] == r.complaint_id].head(2).itertuples():   # real duplicate reports
                items.append((created + dt.timedelta(hours=rng.randint(1, 5)), d.text, d.lat, d.lon, age))
        resolved_ids = []
        for created, text, lat, lon, age in sorted(items, key=lambda x: x[0]):
            out = self.submit(text, lat, lon, created_at=created.isoformat(timespec="seconds"))
            if age >= 5 and out["merged_into"] is None and rng.random() < 0.5:
                resolved_ids.append(out["id"])
        for cid in resolved_ids:
            self.resolve(cid)
        self.reevaluate_all()
        return len(database.query(self.db))

    def photos_for(self, cid):
        """Photos attached to a complaint and to the duplicate reports merged into it."""
        found = []
        for r in [database.get(self.db, cid)] + database.query(self.db, "duplicate_of=?", (cid,)):
            if r and r["photo_path"]:
                path = os.path.join(self.upload_dir, r["photo_path"])
                if os.path.exists(path):
                    found.append({"id": r["id"], "path": path})
        return found

    def preview(self, text):
        """What the AI makes of a complaint so far, without saving anything. None if the text is too short to judge."""
        text = (text or "").strip()
        if len(text) < 8:
            return None
        ml = classifier.predict(text)
        res = rule_engine.run(rule_engine.extract_facts(text, ml["category"], ml["priority"], ml["needs_review"], {}), self.rules)
        return {"category": ml["category"], "confidence": ml["category_conf"], "department": res["department"],
                "needs_review": bool(ml["needs_review"])}

    # ------------------------------------------------------------ what the public may see
    STAGES = STAGES_PUBLIC

    def public_status(self, code):
        """Status of one complaint for the person who holds its tracking code.

        Deliberately small: no complaint text, location, photo, priority or internal notes. The history lines are the
        messages written for the citizen (received, routed, work started, resolved with the crew's note).
        """
        code = (code or "").strip().upper()
        rows = database.query(self.db, "tracking_code=?", (code,)) if code else []
        if not rows:
            return None
        row = rows[0]
        root = self._root_of(row["id"])
        if root["status"] == "resolved":
            stage, label = 4, "Resolved"
        elif root["status"] == "in_progress":
            stage, label = 3, "Work has started"
        elif root["needs_review"]:
            stage, label = 1, "Waiting for an officer to review"
        else:
            stage, label = 2, f"Routed to {root['department']}"
        events = database.events_for(self.db, row["id"])
        if root["id"] != row["id"]:                              # a merged reporter also follows the shared repair
            events += [e for e in database.events_for(self.db, root["id"]) if e["kind"] in ("in_progress", "resolved", "reopened")]
        updates = [{"when": e["at"].replace("T", " ")[:16], "message": e["message"]}
                   for e in sorted(events, key=lambda e: (e["at"], e["id"]))]
        can_give, given = self.feedback_state(code)
        return {"code": code, "submitted": row["created_at"][:10], "category": root["category"], "stage": stage,
                "stage_label": label, "resolved_on": (root["resolved_at"] or "")[:10] or None, "updates": updates,
                "has_after_photo": self.public_after_photo(code) is not None, "can_give_feedback": can_give,
                "feedback_given": given}

    def public_stats(self, min_count=3):
        """City-wide figures that are safe to publish. Wards with fewer than min_count complaints are hidden."""
        roots = self._roots()
        resolved = [r for r in roots if r["status"] == "resolved"]
        days = [(dt.datetime.fromisoformat(r["resolved_at"]) - dt.datetime.fromisoformat(r["created_at"])).total_seconds() / 86400
                for r in resolved if r["resolved_at"]]
        wards = Counter(r["ward"] for r in roots)
        return {"reports": len(database.query(self.db)), "issues": len(roots), "resolved": len(resolved),
                "open": len(roots) - len(resolved), "avg_days": sum(days) / len(days) if days else None,
                "by_category": dict(Counter(r["category"] for r in roots)),
                "by_ward": {w: n for w, n in sorted(wards.items()) if n >= min_count},
                "hidden_wards": sum(1 for n in wards.values() if n < min_count)}

    def seed_surge(self, n=40, category="Drainage", seed=1, actor=None):
        """Simulate a monsoon-style surge: n new complaints of one category arrive at once."""
        self.audit(actor, "simulate_surge", detail=f"{n} {category} complaints")
        rng = random.Random(seed)
        data = pd.read_csv(os.path.join(ROOT, "data", "complaints.csv"))
        pool = data[(data["duplicate_of"].isna()) & (data["category"] == category)]
        added = 0
        for r in pool.sample(min(n, len(pool)), random_state=seed).itertuples():
            created = self.clock() - dt.timedelta(minutes=rng.randint(0, 90))
            self.submit(r.text, r.lat, r.lon, created_at=created.isoformat(timespec="seconds"))
            added += 1
        return added

    def reset(self, actor=None):
        self.audit(actor, "reset_database")
        for r in database.query(self.db):                            # delete the photos too
            if r["photo_path"]:
                try:
                    os.remove(os.path.join(self.upload_dir, r["photo_path"]))
                except OSError:
                    pass
        database.reset(self.db)

    def road_lines(self):
        """The road network as ((lat, lon), (lat, lon)) pairs, for drawing the hotspot map."""
        c = self.graph.coords
        return [(c[a], c[b]) for a, b in self.graph.g.edges]

    HOTSPOT_WEIGHT = {"critical": 3.0, "high": 2.0, "medium": 1.0, "low": 0.5}

    def ward_hotspots(self):
        """Wards ranked by how much trouble they have: each open complaint counts more the more urgent it is."""
        table = self.open_table()
        columns = ["ward", "open", "critical", "hotspot score", "near school/hospital", "near public place"]
        if table.empty:
            return pd.DataFrame(columns=columns)
        rows = {}
        for r in table.itertuples():
            kinds = {p["type"] for p in places.near(r.lat, r.lon)}
            w = rows.setdefault(r.ward, {"ward": r.ward, "open": 0, "critical": 0, "hotspot score": 0.0,
                                         "near school/hospital": 0, "near public place": 0})
            w["open"] += 1
            w["critical"] += r.priority == "critical"
            w["hotspot score"] += self.HOTSPOT_WEIGHT[r.priority]
            w["near school/hospital"] += bool(kinds & places.SENSITIVE)
            w["near public place"] += bool(kinds & places.PUBLIC)
        return pd.DataFrame(rows.values(), columns=columns).sort_values("hotspot score", ascending=False).reset_index(drop=True)

    def count(self):
        return len(database.query(self.db))

    def open_table(self):
        """Open complaints as a table for the officer dashboard, most urgent first."""
        now = self.clock()
        dups = Counter(r["duplicate_of"] for r in database.query(self.db, "duplicate_of IS NOT NULL AND status='open'"))
        df = pd.DataFrame([{
            "id": r["id"], "priority": r["priority"], "department": r["department"], "category": r["category"],
            "ward": r["ward"], "score": r["score"], "duplicates": dups.get(r["id"], 0),
            "age_days": max(0, (now - dt.datetime.fromisoformat(r["created_at"])).days),
            "needs_review": bool(r["needs_review"]), "text": r["text"], "lat": r["lat"], "lon": r["lon"],
            "status": r["status"], "crew": r["assigned_crew"] or "", "reopened": r["reopened_count"] or 0}
            for r in self._roots("open")])
        return df.sort_values("score", ascending=False).reset_index(drop=True) if len(df) else df

    def stats(self):
        roots = self._roots()
        frame = pd.DataFrame(roots)
        if frame.empty:
            return {"frame": frame, "ward_ratio": pd.Series(dtype=float)}
        counts = Counter(r["ward"] for r in roots)
        ratio = {w: rule_engine.ward_reporting_ratio(w, counts, self.ward_pop) for w in sorted(self.ward_pop)}
        return {"frame": frame, "ward_ratio": pd.Series(ratio, name="reporting ratio")}


if __name__ == "__main__":
    eng = Engine()
    if "--seed" in sys.argv:
        eng.reset()
        print(f"seeded {eng.seed_demo()} complaints")
    plan = eng.plan()
    m, b = plan["metrics"], plan["baseline_metrics"]
    print(f"open complaints scheduled: {m['served']}/{m['total']} | manual review: {len(plan['review'])}")
    print(f"urgent on time: CivicSense {m['urgent_on_time']}/{m['urgent_total']}  vs  first-come {b['urgent_on_time']}/{b['urgent_total']}")
