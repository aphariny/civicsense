"""CivicSense OFFICER portal: sign-in required.

Opened from the landing page in app.py (streamlit run app.py). It can also run alone: streamlit run officer_app.py
Nobody sees any complaint until they sign in with an officer account (create one with `python create_user.py`).
Every sign-in and every action is written to an audit log. Admins can also manage accounts and data.
"""
import datetime as dt

import pandas as pd
import streamlit as st

import auth
import crew_app
import database
import ui
from app_common import get_engine, html, show_html_map
from modules import evaluate, guide, places
from modules.geo import WARD_CENTRES

CATEGORIES = ["Road", "Sanitation", "Electricity", "Water Supply", "Drainage"]
LEVELS = ui.LEVELS
OFFICER_PAGES = ["\U0001F4CA Overview", "\U0001F4CB Complaints", "\U0001F69A Crew schedule", "\U0001F525 Hotspot map",
                 "\U0001F3AF Priority guide", "\U0001F4C8 Insights", "\U0001F9EA Model performance"]
ADMIN_PAGES = ["\U0001F9FE Audit log", "\u2699\uFE0F Admin"]


# ----------------------------------------------------------------------------- sign-in and sessions
def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def current_user(engine):
    """The signed-in user, re-checked against the database on every run, or None."""
    user = st.session_state.get("user")
    if not user:
        return None
    fresh = database.get_user(engine.db, user["username"])
    if not fresh or not fresh["active"]:                      # account removed or deactivated while signed in
        sign_out(engine, "Your account is no longer active.")
        return None
    last = st.session_state.get("last_active")
    if last is None or auth.session_expired(last):
        engine.audit(user["username"], "session_expired")
        sign_out(engine, "Your session expired. Please sign in again.", log=False)
        return None
    st.session_state["last_active"] = now_iso()
    return {"username": fresh["username"], "role": fresh["role"], "crew_id": fresh["crew_id"]}


def sign_out(engine, notice=None, log=True):
    user = st.session_state.pop("user", None)
    st.session_state.pop("last_active", None)
    if user and log and not notice:
        engine.audit(user["username"], "logout")
    if notice:
        st.session_state["notice"] = notice


def page_login(engine, leave=None):
    html(ui.hero("Officer portal", "Authorised staff only. Every action is recorded.", tone="blue", pill="Sign-in required",
                 icon_name="lock"))
    if leave is not None:
        st.button("\u2190 Back to home", key="officer_login_home", on_click=leave)
    if database.user_count(engine.db) == 0:
        st.warning("No officer accounts exist yet. In the project folder run `python create_user.py` to create one.")
        return
    notice = st.session_state.pop("notice", None)
    if notice:
        st.info(notice)
    left, _ = st.columns([2, 3])
    with left:
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in")
        if submitted:
            try:
                user = auth.authenticate(engine.db, username, password)
            except auth.AuthError as err:
                tried = "".join(c for c in (username or "").strip().lower() if c.isprintable())[:40] or "(empty)"
                engine.audit(tried, "login_failed")
                st.error(str(err))
                return
            st.session_state["user"] = {"username": user["username"], "role": user["role"], "crew_id": user.get("crew_id")}
            st.session_state["last_active"] = now_iso()
            engine.audit(user["username"], "login")
            st.rerun()


def denied(user, permission="view"):
    """Refuse a page the signed-in role may not use (a crew account must never see the officer pages)."""
    if auth.can(user, permission):
        return False
    st.error("Your account cannot open this page.")
    return True


# ----------------------------------------------------------------------------- shared pieces
def show_decision(row):
    a, b, c = st.columns(3)
    a.metric("Category", row["category"], f"{row['category_conf']:.0%} confident")
    b.metric("Priority", str(row["priority"]).upper())
    c.metric("Department", row["department"])


def show_photos(engine, cid):
    photos = engine.photos_for(cid)
    if photos:
        st.caption("Photos attached by residents (evidence only; the AI reads the text)")
        for p in photos:
            st.image(p["path"], caption=f"Photo with complaint #{p['id']}")


def pick_row(view, ids):
    """Show the queue. Clicking a row opens that complaint; the most urgent one is open by default."""
    try:
        event = st.dataframe(view, hide_index=True, on_select="rerun", selection_mode="single-row", key="queue")
        rows = event.selection.rows
    except (TypeError, AttributeError):                      # an older Streamlit without clickable rows
        st.dataframe(view, hide_index=True)
        return st.selectbox("Open a complaint", ids, format_func=lambda i: f"#{i}")
    st.caption("Click a row to open it.")
    return ids[rows[0]] if rows and rows[0] < len(ids) else ids[0]


# ----------------------------------------------------------------------------- pages
def page_overview(engine, user):
    if denied(user):
        return
    html(ui.hero("CivicSense officer portal", "Classify, prioritize, route and schedule citizen complaints", tone="blue",
                 pill=f"Signed in as {user['username']} ({user['role']})", icon_name="shield"))
    table = engine.open_table()
    if table.empty:
        st.info("There are no open complaints. An admin can load demo data from the Admin page.")
        html(ui.flow())
        return
    plan = engine.plan()
    m, b = plan["metrics"], plan["baseline_metrics"]
    critical = int((table["priority"] == "critical").sum())
    review = int(table["needs_review"].sum())
    old = int((table["age_days"] >= 7).sum())
    reopened = int((table["reopened"] > 0).sum())
    html(ui.kpis([
        ("Open complaints", len(table), "blue", "", "clipboard"),
        ("Critical", critical, "red", "", "alert"),
        ("Waiting for review", review, "blue", "", "eye"),
        ("Duplicate reports merged", int(table["duplicates"].sum()), "blue", "", "copy"),
        ("Urgent on time", f"{m['urgent_on_time']}/{m['urgent_total']}", "blue",
         f"first-come-first-served: {b['urgent_on_time']}/{b['urgent_total']}", "clock"),
    ]))
    html(ui.section("bell", "Needs attention now"))
    a, b2, c, d = st.columns(4)
    with a:
        html(ui.attention_card("alert", critical, "Critical complaints", "Each needs a crew as soon as possible", "red"))
    with b2:
        html(ui.attention_card("eye", review, "Waiting for an officer", "The AI was not confident: open Complaints to review", "blue"))
    with c:
        html(ui.attention_card("clock", old, "Open for 7+ days", "Escalated automatically by the rules", "amber"))
    with d:
        html(ui.attention_card("send", reopened, "Reopened by citizens", "The citizen says it was not fixed", "red" if reopened else "blue"))
    left, right = st.columns([2, 3])
    with left:
        html(ui.section("chart", "By priority"))
        counts = table["priority"].value_counts().reindex(LEVELS).fillna(0)
        html(ui.donut([(p, int(counts[p]), ui.COLORS[p]) for p in LEVELS], len(table), "open"))
    with right:
        html(ui.section("send", "Most urgent right now"))
        for _, row in table.head(4).iterrows():
            html(ui.mini_card(row.to_dict()))
    html(ui.flow())


def page_complaints(engine, user):
    if denied(user):
        return
    html(ui.page_header("Complaints", "Open complaints, most urgent first."))
    table = engine.open_table()
    if table.empty:
        st.info("No open complaints.")
        return
    html(ui.kpis([
        ("Open complaints", len(table), "blue", ""),
        ("Critical", int((table["priority"] == "critical").sum()), "red", ""),
        ("Waiting for review", int(table["needs_review"].sum()), "blue", ""),
        ("Duplicate reports merged", int(table["duplicates"].sum()), "blue", ""),
    ]))
    f1, f2, f3 = st.columns([3, 3, 2])
    levels = f1.multiselect("Priority", LEVELS, default=LEVELS)
    department = f2.selectbox("Department", ["All departments"] + sorted(table["department"].unique()))
    only_review = f3.checkbox("Waiting for review only")
    shown = table[table["priority"].isin(levels)]
    if department != "All departments":
        shown = shown[shown["department"] == department]
    if only_review:
        shown = shown[shown["needs_review"]]
    if shown.empty:
        st.info("No complaints match these filters.")
        return
    view = shown.assign(priority=shown["priority"].map(lambda p: f"{ui.EMOJI[p]} {p}"),
                        category=shown["category"].map(lambda c: f"{ui.CATEGORY_EMOJI.get(c, '')} {c}"))
    view = view.assign(status=shown["status"].map(lambda x: ui.STATUS_LABEL.get(x, x)))
    cid = pick_row(view[["id", "priority", "status", "crew", "department", "category", "ward", "score", "duplicates", "age_days",
                         "reopened", "needs_review", "text"]], shown["id"].tolist())
    row = engine.get(cid)
    meta = shown[shown["id"] == cid].iloc[0]
    left, right = st.columns([5, 4])
    with left:
        html(ui.complaint_card(row, duplicates=int(meta["duplicates"]), age_days=int(meta["age_days"])))
        show_decision(row)
        show_photos(engine, cid)
        if row["needs_review"] and auth.can(user, "review"):
            st.subheader("Officer review")
            with st.form(f"review_{cid}"):
                category = st.selectbox("Correct category", CATEGORIES)
                priority = st.selectbox("Priority after review", LEVELS, index=1)
                if st.form_submit_button("Confirm and save correction"):
                    auth.require(user, "review")
                    engine.officer_correct(cid, category, priority, actor=user["username"])
                    st.rerun()
        if auth.can(user, "resolve"):
            st.subheader("Resolve")
            with st.form(f"resolve_{cid}"):
                note = st.text_input("Resolution note (the citizen will see this)", key=f"rnote_{cid}")
                after = st.file_uploader("After photo (optional)", type=["jpg", "jpeg", "png"], key=f"rphoto_{cid}")
                if st.form_submit_button("Mark as resolved"):
                    try:
                        auth.require(user, "resolve")
                        engine.resolve(cid, actor=user["username"], note=note, after_photo=after.getvalue() if after else None)
                    except ValueError as err:
                        st.error(str(err))
                    else:
                        st.rerun()
    with right:
        st.subheader("Why this decision?")
        html(ui.trace_html(row["trace"], row["flags"]))


def page_schedule(engine, user):
    if denied(user):
        return
    html(ui.page_header("Crew schedule", "Each bar is one crew's shift. Blocks are jobs, coloured by priority."))
    plan = engine.plan()
    if not plan["jobs"]:
        st.info("Nothing to schedule yet.")
        return
    m, b = plan["metrics"], plan["baseline_metrics"]
    html(ui.kpis([
        ("Urgent on time", f"{m['urgent_on_time']}/{m['urgent_total']}", "blue",
         f"{m['urgent_on_time'] - b['urgent_on_time']:+d} vs first-come-first-served"),
        ("Complaints scheduled", f"{m['served']}/{m['total']}", "blue", ""),
        ("Crew travel", f"{m['km']:.0f} km", "blue", f"{m['km'] - b['km']:+.0f} km vs first-come-first-served"),
        ("Waiting for review", len(plan["review"]), "red" if plan["review"] else "blue", "not scheduled yet"),
    ]))
    result = plan["result"]
    html(ui.legend())
    html(ui.timeline(result["routes"], engine.crews, engine.clock_time))
    if result["deferred"]:
        st.warning("No crew could reach these on time (scheduled late where possible): "
                   + ", ".join(f"#{j.id}" for j in result["deferred"]))
    st.subheader("Details by crew")
    for crew in engine.crews:
        stops = result["routes"][crew.id]
        if not stops:
            continue
        with st.expander(f"{crew.id} ({crew.department}) - {len(stops)} job(s)"):
            rows = []
            for n, s in enumerate(stops, 1):
                job, info = s["job"], engine.get(s["job"].id)
                rows.append({"Stop": n, "Arrive": engine.clock_time(s["arrive"]), "Complaint": f"#{job.id}",
                             "Priority": f"{ui.EMOJI[info['priority']]} {info['priority']}",
                             "Deadline": engine.clock_time(job.deadline),
                             "Status": "LATE" if s["late"] else "On time", "Problem": info["text"]})
            st.dataframe(pd.DataFrame(rows), hide_index=True)
    if result["unassigned"]:
        st.caption("Left for the next shift: " + ", ".join(f"#{j.id}" for j in result["unassigned"]))


def page_map(engine, user):
    if denied(user):
        return
    html(ui.page_header("Hotspot map", "Where open complaints are, how urgent they are, and which are near schools or crowded places."))
    table = engine.open_table()
    if table.empty:
        st.info("No open complaints to show.")
        return
    c1, c2, c3 = st.columns([3, 2, 3])
    cats = c1.multiselect("Category", CATEGORIES, default=CATEGORIES)
    density = c2.checkbox("Show density glow", value=True)
    show_places = c3.checkbox("Show schools, hospitals and public places", value=True)
    urgent_only = st.checkbox("Only high and critical complaints")
    view = table[table["category"].isin(cats)]
    if urgent_only:
        view = view[view["priority"].isin(["high", "critical"])]
    points = view[["id", "lat", "lon", "priority", "category"]].to_dict("records")

    street, schematic = st.tabs(["Map of Chennai", "Schematic view"])
    with street:
        page = ui.leaflet_hotspot_html(points, places.all_places(), show_density=density, show_places=show_places)
        if show_html_map(page, height=560):
            html(ui.map_legend(show_places))
            st.caption(f"{len(points)} complaints shown on the street map. It needs an internet connection for the map tiles; "
                       "use the layer button on the map to switch between the light map and OpenStreetMap. "
                       "Hover over a dot or a place for its name.")
        else:
            st.warning("The street map could not be shown here. The schematic view is shown instead.")
            html(ui.hotspot_svg(points, places.all_places(), engine.road_lines(), show_density=density, show_places=show_places))
    with schematic:
        html(ui.hotspot_svg(points, places.all_places(), engine.road_lines(), show_density=density, show_places=show_places))
        html(ui.map_legend(show_places))
        st.caption("A drawing of the demo city that works without internet. Darker red glow means more or more urgent problems close together.")

    html(ui.section("alert", "Which wards need attention first"))
    st.dataframe(engine.ward_hotspots(), hide_index=True)
    st.caption("The hotspot score counts critical complaints 3, high 2, medium 1 and low 0.5. "
               "'Near' means within 150 m of a school, hospital or busy public place.")
    st.subheader("Complaints per ward and category")
    st.dataframe(pd.crosstab(table["ward"], table["category"]))


def page_guide(engine, user):
    if denied(user):
        return
    html(ui.page_header("Priority guide", "How the same problem ranks on an ordinary street, in a crowded place, near a hospital or near a school."))
    st.write("The AI first judges how serious the problem is. The rules then raise the priority when the people affected are "
             "more vulnerable or more numerous: **schools and hospitals first, then busy public places** (markets, bus stands, "
             "railway stations, temples, parks), then ordinary streets. A dangerous problem in a crowd or near a school is always critical.")
    columns = [(k, label) for k, label, _ in guide.PLACES]
    html(ui.priority_matrix(guide.matrix(engine.rules), columns))
    st.caption("Every cell comes from running the real rule engine, so this table cannot disagree with what the system does. "
               "Shaded cells rank higher than the same problem on an ordinary street. Within the same priority, the score "
               "decides who is served first.")
    html(ui.section("search", "Try it yourself"))
    c1, c2 = st.columns(2)
    name = c1.selectbox("Problem", [p[0] for p in guide.PROBLEMS])
    where = c2.selectbox("Where is it?", [label for _, label, _ in guide.PLACES])
    c3, c4 = st.columns(2)
    dups = c3.number_input("Duplicate reports so far", value=0, min_value=0, max_value=20)
    kids = c4.checkbox("Children are affected")
    place_type = next(t for _, label, t in guide.PLACES if label == where)
    result = guide.decide(name, place_type, int(dups), kids, engine.rules)
    html(ui.kpis([("Priority", result["priority"].upper(), "red" if result["priority"] == "critical" else "blue", "", "alert"),
                  ("Score (tie-break)", f"{result['score']:.0f}", "blue", "", "chart"),
                  ("Department", result["department"], "blue", "", "building")]))
    html(ui.section("layers", "Why"))
    html(ui.trace_html(result["trace"], result["flags"]))


def page_insights(engine, user):
    if denied(user):
        return
    html(ui.page_header("Insights", "What is being reported, and is every ward being heard?"))
    stats = engine.stats()
    frame = stats["frame"]
    if frame.empty:
        st.info("No data yet.")
        return
    left, right = st.columns(2)
    with left:
        html(ui.section("layers", "By category"))
        counts = frame["category"].value_counts()
        html(ui.bars([(c, int(n), ui.BLUE) for c, n in counts.items()]))
    with right:
        html(ui.section("chart", "By priority"))
        counts = frame["priority"].value_counts().reindex(LEVELS).fillna(0)
        html(ui.donut([(p, int(counts[p]), ui.COLORS[p]) for p in LEVELS], int(counts.sum()), "complaints"))
    st.subheader("Fairness: does every ward get heard?")
    ratio = stats["ward_ratio"]
    html(ui.bars([(f"Ward {w}", float(v), ui.RED if v <= 0.7 else ui.BLUE) for w, v in ratio.items()],
                 maximum=max(1.5, float(ratio.max())), marker=1.0))
    st.caption("The black line is 1.0: a ward reporting in proportion to its population. Red wards (0.7 or below) get a "
               "fairness boost in the priority score, but only once at least 30 complaints exist (fewer is too noisy).")
    html(ui.section("check", "Do citizens say it was really fixed?"))
    fb = engine.feedback_stats()
    if not fb["responses"]:
        st.caption("No feedback yet. Citizens can rate a repair on the Track page once a complaint is resolved.")
    else:
        html(ui.kpis([("Responses", fb["responses"], "blue", "", "users"), ("Average rating", f"{fb['avg_rating']:.1f} / 5", "blue", "", "check"),
                      ("Said it was fixed", f"{fb['fixed_pct']:.0%}", "blue", "", "shield"),
                      ("Reopened complaints", f"{fb['reopened']} ({fb['reopen_rate']:.0%})", "red" if fb["reopened"] else "blue", "", "alert")]))
        if fb["by_department"]:
            html(ui.bars([(d, round(v, 2), ui.BLUE) for d, v in fb["by_department"].items()], maximum=5))
            st.caption("Average rating by department (out of 5).")


def page_model(engine, user):
    if denied(user):
        return
    html(ui.page_header("Model performance", "How well does the classifier really work? Easy test data versus hand-written hard cases."))
    res = evaluate.load_results()
    if res is None:
        st.info("The evaluation has not been run yet. An admin can run it from the Admin page, or run `python modules/evaluate.py`.")
        return
    st.write("The classifier learned from complaints that were **generated from templates**, so a test on similar data is easy. "
             "We also test it on complaints **written by hand** with typos, shorthand and Tanglish. Always compare with the "
             "**baseline**, which just guesses the most common answer.")
    live = res["production"]["category"]
    cat = res["targets"]["category"]["models"]
    n = res["n_hard"]
    hard_acc = cat[live]["hard"]["accuracy"]
    ci = 1.96 * (hard_acc * (1 - hard_acc) / n) ** 0.5
    html(ui.kpis([("Category, easy test", f"{cat[live]['synthetic']['accuracy']:.0%}", "blue", f"live model: {live}", "check"),
                  ("Category, hard cases", f"{hard_acc:.0%}", "red", f"plus or minus {ci:.0%} ({n} cases)", "alert"),
                  ("Baseline, hard cases", f"{cat['Most common answer (baseline)']['hard']['accuracy']:.0%}", "blue", "always guess the most common", "layers"),
                  ("Vague text sent to a person", f"{res['review']['vague_sent_to_review']:.0%}", "blue", "good: unclear complaints get checked", "eye"),
                  ("Clear text sent to a person", f"{res['review']['clear_sent_to_review']:.0%}", "red", "the cost of being careful", "clock")]))
    target = st.radio("What to look at", ["Category", "Priority"], horizontal=True)
    key = target.lower()
    block = res["targets"][key]
    html(ui.section("chart", f"All models: {target.lower()}"))
    table = evaluate.summary_table(res, key)
    pct = [c for c in table.columns if c not in ("model", "seconds", "in the live system")]
    st.dataframe(table.assign(**{c: table[c].map(lambda v: f"{v:.0%}" if c != "hard-case macro-F1" else f"{v:.2f}") for c in pct}),
                 hide_index=True)
    st.caption(f"With only {n} hard cases a difference of a few points is within the noise (see 'plus or minus'). "
               "The live system picks between Logistic Regression and Decision Tree using the easy test, so it can miss a model "
               "that does better on real complaints.")
    if key == "priority":
        st.caption("'Within one level' is a weak score: always guessing the most common priority already gets about the same. "
                   "Look at exact accuracy and macro-F1 instead.")
    html(ui.section("layers", "Where the mistakes are"))
    c1, c2 = st.columns(2)
    model = c1.selectbox("Model", list(block["models"]), index=list(block["models"]).index(res["production"][key]))
    which = c2.radio("Test set", ["Hard cases", "Easy test"], horizontal=True)
    matrix = block["confusion"]["hard" if which == "Hard cases" else "synthetic"][model]
    html(ui.confusion_matrix(block["labels"], matrix))
    st.caption("Green on the diagonal is correct. Red is a mistake: the row is the right answer, the column is what the model said.")
    per_class = block["per_class"][model]
    st.dataframe(pd.DataFrame([{key: lbl, "precision": f"{v['precision']:.0%}", "recall": f"{v['recall']:.0%}", "f1": f"{v['f1']:.2f}",
                                "cases": v["support"]} for lbl, v in per_class.items()]), hide_index=True)
    errors = block["errors"][model]
    with st.expander(f"The {len(errors)} hard cases this model got wrong"):
        if errors:
            st.dataframe(pd.DataFrame(errors).rename(columns={"true": "right answer", "predicted": "model said"}), hide_index=True)
    st.caption(f"Last run: {res['generated_at'].replace('T', ' ')}. Hard cases were written and labelled by the project team; "
               "adding more of your own, in tests/hard_cases.csv, makes this page more trustworthy.")


def page_audit(engine, user):
    html(ui.page_header("Audit log", "Who signed in and what they did. Newest first."))
    if not auth.can(user, "audit"):
        st.error("Only admins can read the audit log.")
        return
    rows = database.audit_entries(engine.db)
    if not rows:
        st.info("Nothing has been recorded yet.")
        return
    st.dataframe(pd.DataFrame(rows).rename(columns={"at": "time", "username": "user", "complaint_id": "complaint"}),
                 hide_index=True)


def page_admin(engine, user):
    html(ui.page_header("Admin", "Accounts and data. Only admins can use this page."))
    if not auth.can(user, "manage_users"):
        st.error("Only admins can use this page.")
        return
    st.subheader("Accounts")
    st.dataframe(pd.DataFrame(database.list_users(engine.db)), hide_index=True)
    with st.form("new_account"):
        c1, c2, c3, c4 = st.columns(4)
        name = c1.text_input("New username")
        pw = c2.text_input("Password (8+ characters)", type="password")
        role = c3.selectbox("Role", sorted(auth.PERMISSIONS))
        crew = c4.selectbox("Crew (for crew accounts)", [c.id for c in engine.crews])
        if st.form_submit_button("Create account"):
            try:
                auth.require(user, "manage_users")
                auth.create_user(engine.db, name, pw, role, crew_id=crew if role == "crew" else None)
                engine.audit(user["username"], "create_account", detail=f"{name.strip().lower()} ({role})")
                st.success("Account created.")
            except ValueError as err:
                st.error(str(err))

    st.subheader("Data")
    if st.button("Load demo data (60 complaints)"):
        auth.require(user, "seed")
        if engine.count():
            st.warning("The database already has complaints. Reset it first.")
        else:
            with st.spinner("Processing complaints..."):
                engine.seed_demo(60, actor=user["username"])
            st.rerun()
    st.caption("Demo tool: a monsoon-style surge adds 40 drainage complaints at once. Then open Crew schedule to see the scheduler cope.")
    if st.button("Simulate monsoon surge (+40 drainage complaints)"):
        auth.require(user, "seed")
        with st.spinner("Processing complaints..."):
            engine.seed_surge(40, actor=user["username"])
        st.rerun()
    confirm = st.checkbox("I understand that resetting deletes every complaint and photo")
    if st.button("Reset database") and confirm:
        auth.require(user, "reset")
        engine.reset(actor=user["username"])
        st.rerun()

    st.subheader("Model evaluation")
    st.write("Compares seven models on the synthetic test set and on the hand-written hard cases. Takes about half a minute.")
    if st.button("Re-run model evaluation"):
        auth.require(user, "export")
        with st.spinner("Training and testing the models..."):
            evaluate.evaluate()
        engine.audit(user["username"], "run_evaluation")
        st.success("Done. Open Model performance to see the results.")

    st.subheader("Retraining the classifier")
    st.write("Officer corrections are saved when a complaint is reviewed. Export them, then run "
             "`python modules/classifier.py` to retrain with them included.")
    if st.button("Export corrections"):
        auth.require(user, "export")
        n = engine.export_corrections(actor=user["username"])
        st.success(f"Saved {n} corrections to data/corrections.csv")


# ----------------------------------------------------------------------------- entry points
def render(engine, leave=None):
    """Draw the officer portal, or the sign-in page if nobody is signed in.

    leave: a function that returns to the landing page (set by app.py). Leaving also signs the officer out.
    """
    user = current_user(engine)
    if not user:
        page_login(engine, leave)
        return
    if user["role"] == "crew":
        crew_app.render(engine, user, leave=leave, sign_out=lambda: sign_out(engine))
        return
    st.sidebar.title("CivicSense")
    st.sidebar.caption(f"Signed in as {user['username']} ({user['role']})")
    pages = OFFICER_PAGES + (ADMIN_PAGES if auth.can(user, "manage_users") else [])
    page = st.sidebar.radio("Go to", pages)
    st.sidebar.caption(f"{engine.count()} complaints in the database")
    if st.sidebar.button("Sign out"):
        sign_out(engine)
        st.rerun()
    if leave is not None:
        st.sidebar.button("\u2190 Back to home (signs you out)", key="officer_home", on_click=leave)
    routes = {OFFICER_PAGES[0]: page_overview, OFFICER_PAGES[1]: page_complaints, OFFICER_PAGES[2]: page_schedule,
              OFFICER_PAGES[3]: page_map, OFFICER_PAGES[4]: page_guide, OFFICER_PAGES[5]: page_insights,
              OFFICER_PAGES[6]: page_model, ADMIN_PAGES[0]: page_audit, ADMIN_PAGES[1]: page_admin}
    routes.get(page, page_overview)(engine, user)


def main():
    st.set_page_config(page_title="CivicSense - Officer portal", page_icon="\U0001F3D9\uFE0F", layout="wide")
    html(ui.css())
    render(get_engine())


if __name__ == "__main__":
    main()
