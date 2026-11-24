"""Runs the landing page, the citizen portal and the officer portal against a stand-in for Streamlit.

It checks the arguments the apps pass to Streamlit and, more importantly, WHAT EACH VISITOR CAN SEE:
  - the landing page and the citizen portal never show anyone's complaint;
  - the officer portal shows nothing until someone signs in, and enforces roles, sessions and sign-out.
It cannot check how pages look in the real app, and it uses made-up stand-ins for the optional map libraries
(folium, streamlit-folium, streamlit-geolocation), so it proves our logic, not their real behaviour.
Run:  python tests/ui_smoke_test.py
"""
import datetime as dt
import os
import re
import sys
import tempfile
import types
import warnings
from types import SimpleNamespace
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imgs
PNG = imgs.png()
APP_MODULES = ("app_common", "location_picker", "public_app", "crew_app", "officer_app", "app")


class Rerun(Exception):
    pass


class FakeUpload:
    def __init__(self, data, name="photo.png"):
        self.name, self._data = name, data

    def getvalue(self):
        return self._data


class FakeSt:
    """Stand-in for the streamlit module. Records everything shown so tests can inspect it."""

    def __init__(self, answers=None, state=None, selectable=True):
        self.answers = answers or {}
        self.session_state = state if state is not None else {}
        self.selectable = selectable
        self.sidebar = self
        self.log, self.out, self.seen = [], [], set()

    def _show(self, text):
        self.out.append(str(text))

    def output(self):
        return "\n".join(self.out)

    def called(self, name):
        return any(n == name for n, _ in self.log)

    def _widget(self, kind, label, key=None):
        ident = (kind, key if key else label)
        assert ident not in self.seen, f"duplicate widget {ident}: Streamlit would raise DuplicateWidgetID"
        self.seen.add(ident)

    def __getattr__(self, name):
        if name in ("title", "header", "subheader", "caption", "write", "success", "info", "warning", "error"):
            def show(*a, **k):
                self.log.append((name, a[0] if a else None))
                self._show(a[0] if a else "")
            return show
        raise AttributeError(f"stand-in has no st.{name}: add it if it is a real Streamlit function")

    def set_page_config(self, **kw): self.log.append(("set_page_config", None))

    def toast(self, message, icon=None):
        self.log.append(("toast", message)); self._show(message)

    def markdown(self, body, unsafe_allow_html=False):
        if unsafe_allow_html:
            assert "\n" not in body, "HTML passed to markdown must be one line, or Markdown may break it"
            assert "<script" not in body.lower(), "raw <script> in HTML"
        self.log.append(("markdown", body)); self._show(body)

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def columns(self, spec):
        n = spec if isinstance(spec, int) else len(spec)
        assert isinstance(n, int) and n > 0
        return [self] * n

    def expander(self, label, expanded=False): return self
    def tabs(self, labels): return [self] * len(labels)
    def form(self, key): return self
    def spinner(self, text): return self
    def cache_resource(self, fn): return fn

    def metric(self, label, value, delta=None, delta_color="normal"):
        assert isinstance(label, str) and isinstance(value, (str, int, float)), (label, value)
        assert delta is None or isinstance(delta, (str, int, float)), (label, delta)
        self.log.append(("metric", label)); self._show(f"{label} {value} {delta or ''}")

    def dataframe(self, data, hide_index=None, on_select=None, selection_mode=None, key=None):
        assert isinstance(data, (pd.DataFrame, pd.Series)) and not data.empty, "dataframe needs non-empty data"
        self.log.append(("dataframe", None)); self._show(data.to_string())
        if on_select:
            if not self.selectable:
                raise TypeError("this Streamlit has no clickable rows")
            row = self.answers.get("queue_row")
            return SimpleNamespace(selection=SimpleNamespace(rows=[] if row is None else [row]))

    def map(self, data, latitude=None, longitude=None, color=None, zoom=None):
        for col in (latitude or "lat", longitude or "lon", color):
            assert col is None or col in data.columns, f"map column {col} missing"
        assert not data.isna().any().any()
        self.log.append(("map", None))

    def image(self, data, caption=None):
        assert isinstance(data, (str, bytes)) and data, "image needs a path or bytes"
        self.log.append(("image", caption)); self._show(caption or "")

    def radio(self, label, options, horizontal=False):
        self._widget("radio", label)
        return self.answers.get(label, options[0])

    def selectbox(self, label, options, index=0, format_func=str):
        self._widget("selectbox", label)
        for o in options:
            format_func(o)
        return self.answers.get(label, options[index])

    def multiselect(self, label, options, default=None):
        self._widget("multiselect", label)
        return self.answers.get(label, list(default if default is not None else []))

    def checkbox(self, label, value=False):
        self._widget("checkbox", label)
        return self.answers.get(label, value)

    def text_area(self, label, key=None, placeholder=None, max_chars=None):
        self._widget("text_area", label, key)
        return self.answers[label] if label in self.answers else self.session_state.get(key, "")

    def text_input(self, label, key=None, placeholder=None, max_chars=None, type="default"):
        self._widget("text_input", label, key)
        return self.answers.get(label, "")

    def file_uploader(self, label, type=None, key=None):
        self._widget("file_uploader", label, key)
        return self.answers.get(label)

    def number_input(self, label, value=0.0, format=None, min_value=None, max_value=None):
        self._widget("number_input", label)
        return self.answers.get(label, value)

    def form_submit_button(self, label):
        return bool(self.answers.get(label, False))

    def button(self, label, key=None, on_click=None, args=None, type=None):
        self._widget("button", label, key)
        pressed = bool(self.answers.get(label, False))
        if pressed and on_click:
            on_click(*(args or ()))                       # Streamlit runs the callback, then reruns the script
        return pressed

    def rerun(self):
        self.log.append(("rerun", None))
        raise Rerun()


# ---------------------------------------------------------------- fake optional map libraries
def install_map_libs(click=None, fail=False, missing=False):
    for name in ("folium", "streamlit_folium"):
        sys.modules.pop(name, None)
    if missing:
        sys.modules["folium"] = None
        sys.modules["streamlit_folium"] = None
        return
    folium = types.ModuleType("folium")

    class Shape:
        def __init__(self, *a, **k): pass
        def add_to(self, m): return self
    folium.Map = folium.Rectangle = folium.Marker = folium.CircleMarker = Shape
    sf = types.ModuleType("streamlit_folium")

    def st_folium(m, height=None, width=None, returned_objects=None, key=None):
        if fail:
            raise RuntimeError("the library changed")
        return {"last_clicked": click}
    sf.st_folium = st_folium
    sys.modules["folium"], sys.modules["streamlit_folium"] = folium, sf


def install_gps(position=None, missing=False):
    sys.modules.pop("streamlit_geolocation", None)
    if missing:
        sys.modules["streamlit_geolocation"] = None
        return
    mod = types.ModuleType("streamlit_geolocation")
    mod.streamlit_geolocation = lambda: ({"latitude": position[0], "longitude": position[1], "accuracy": 10}
                                         if position else {"latitude": None, "longitude": None})
    sys.modules["streamlit_geolocation"] = mod


def install_components(capture=None, missing=False, fail=False):
    """Stand-in for streamlit.components.v1.html, which shows the Leaflet map pages. capture collects (page, height)."""
    for name in ("streamlit.components", "streamlit.components.v1"):
        sys.modules.pop(name, None)
    if missing:
        sys.modules["streamlit.components"] = None
        sys.modules["streamlit.components.v1"] = None
        return
    pkg, v1 = types.ModuleType("streamlit.components"), types.ModuleType("streamlit.components.v1")

    def html(body, width=None, height=None, scrolling=False):
        if fail:
            raise RuntimeError("components are not available")
        capture.append((body, height))
    v1.html, pkg.v1 = html, v1
    sys.modules["streamlit.components"], sys.modules["streamlit.components.v1"] = pkg, v1


def map_data(page):
    """The DATA object inside a generated map page."""
    return __import__("json").loads(re.search(r"var DATA=(\{.*?\});function tip", page, re.S).group(1))


def load(fake, engine):
    sys.modules["streamlit"] = fake
    for name in APP_MODULES:
        sys.modules.pop(name, None)
    import app, public_app, officer_app, crew_app
    for module in (app, public_app, officer_app):
        module.get_engine = lambda: engine
    return {"app": app, "public": public_app, "officer": officer_app, "crew": crew_app}


class Runner:
    def __init__(self, engine):
        self.engine, self.passed = engine, 0

    def run(self, which, fn, answers=None, state=None, label=None, selectable=True, patch=None, **kw):
        fake = FakeSt(answers, state, selectable)
        modules = load(fake, self.engine)
        module = modules[which]
        if patch:
            patch(modules)
        try:
            target = getattr(module, fn)
            target() if fn == "main" else target(self.engine, **kw)
        except Rerun:
            pass
        self.passed += 1
        print("PASS", label or f"{which}.{fn}")
        return fake

    def pages(self, which):
        return load(FakeSt(), self.engine)[which]


def main():
    import auth, database
    from modules import places
    from pipeline import Engine
    folder = tempfile.mkdtemp()
    engine = Engine(db_path=os.path.join(folder, "ui.db"), upload_dir=os.path.join(folder, "uploads"))
    empty_engine = Engine(db_path=os.path.join(folder, "empty.db"), upload_dir=os.path.join(folder, "u2"))
    r = Runner(engine)
    PUB, OFF = r.pages("public"), r.pages("officer")
    P_HOME, P_REPORT, P_TRACK, P_DASH = PUB.PAGES
    O_OVERVIEW, O_COMPLAINTS, O_SCHEDULE, O_MAP, O_GUIDE, O_INSIGHTS, O_MODEL = OFF.OFFICER_PAGES
    O_AUDIT, O_ADMIN = OFF.ADMIN_PAGES

    # ================================================================ CITIZEN PORTAL
    print("--- citizen portal")
    install_map_libs(missing=True); install_gps(missing=True); install_components(missing=True)
    for fn in ("page_home", "page_track", "page_dashboard"):
        r.run("public", fn, label=f"empty database / {fn}")
    assert "Nothing has been reported" in r.run("public", "page_dashboard", label="empty dashboard says so").output()

    text = "Open manhole near the government school on Gandhi Street, a child almost fell in"
    typed = {"How would you like to give the location?": "Type coordinates"}
    # live AI preview while typing
    f = r.run("public", "page_report", {**typed, "Describe the problem": text}, label="live AI preview appears while typing")
    assert "Looks like a" in f.output() and "Road" in f.output() and engine.count() == 0
    f = r.run("public", "page_report", {**typed, "Describe the problem": "pothole"}, label="no preview for very short text")
    assert "Looks like a" not in f.output() and "Not sure yet" not in f.output()
    f = r.run("public", "page_report", {**typed, "Describe the problem": "Pls fix it please now"}, label="preview says 'not sure' for vague text")
    assert "Not sure yet" in f.output()
    state = {}
    f = r.run("public", "page_report", {**typed, "Open manhole": True}, state, label="example chip fills the text box")
    assert state["complaint_text_0"] == PUB.EXAMPLES["Open manhole"] and "Looks like a" in f.output()
    # submit
    state = {}
    f = r.run("public", "page_report", {**typed, "Describe the problem": text, "Submit complaint": True}, state,
              label="submit a complaint (the page reloads with the result)")
    assert f.called("rerun") and f.called("toast") and engine.count() == 1 and state["form_n"] == 1
    f = r.run("public", "page_report", typed, state, label="the result card shows the tracking code and an empty form")
    codes = re.findall(r"CS-[A-HJ-NP-Z2-9]{8}", f.output())
    assert len(codes) == 1 and "sent it to" in f.output() and "Gandhi" not in f.output() and "manhole" not in f.output().lower()
    code = codes[0]
    assert "Looks like a" not in f.output(), "the text box should be empty after submitting"
    f = r.run("public", "page_report", {**typed, "Report another problem": True}, state, label="'report another problem' clears the card")
    assert "report_result" not in state
    f = r.run("public", "page_report", {**typed, "Describe the problem": "Pothole on MG Road", "Submit complaint": True,
              "Latitude": 28.6, "Longitude": 77.2}, {}, label="location outside the area is refused")
    assert "Please choose a location inside the service area" in f.output() and engine.count() == 1
    state = {}
    r.run("public", "page_report", {"How would you like to give the location?": "Pick a ward", "Ward": 5, "Submit complaint": True,
          "Describe the problem": "Streetlight not working on Station Road for 3 days"}, state, label="report by picking a ward")
    assert engine.count() == 2
    state = {}
    r.run("public", "page_report", {**typed, "Describe the problem": "Garbage not collected near the market",
          "Attach a photo (optional)": FakeUpload(PNG), "Submit complaint": True}, state, label="report with a photo")
    photo_id = max(c["id"] for c in database.query(engine.db))
    assert len(engine.photos_for(photo_id)) == 1
    n = engine.count()
    f = r.run("public", "page_report", {**typed, "Describe the problem": "Pothole on MG Road", "Submit complaint": True,
              "Attach a photo (optional)": FakeUpload(b"not an image")}, {}, label="a fake photo is refused")
    assert "JPEG or PNG" in f.output() and engine.count() == n
    f = r.run("public", "page_report", {**typed, "Submit complaint": True}, {}, label="empty complaint is refused")
    assert "empty" in f.output() and engine.count() == n
    state = {}
    r.run("public", "page_report", {**typed, "Describe the problem": "Pls fix it", "Submit complaint": True}, state, label="a vague complaint")
    f = r.run("public", "page_report", typed, state, label="vague complaint: tells the citizen an officer will review")
    assert "An officer will review" in f.output()

    school = next(p for p in places.all_places() if p["type"] == "school")
    f = r.run("public", "page_report", {**typed, "Latitude": school["lat"] + 0.0002, "Longitude": school["lon"]},
              label="the location card names a nearby school and says it gets extra priority")
    assert school["name"] in f.output() and "extra priority" in f.output()
    f = r.run("public", "page_report", {**typed, "Latitude": 13.006, "Longitude": 80.206}, label="no nearby place: no extra-priority note")
    assert "extra priority" not in f.output()

    # optional map libraries (stand-ins)
    pin = {"How would you like to give the location?": "Pin on the map", "Describe the problem": "Pothole near the temple", "Submit complaint": True}
    f = r.run("public", "page_report", pin, {}, label="pin method without map libraries shows install help")
    assert "pip install folium" in f.output() and "Please choose a location" in f.output()
    install_map_libs(click={"lat": 13.0231, "lng": 80.2188})
    state = {}
    r.run("public", "page_report", pin, state, label="click on the map inside the area")
    assert state["pin"] == (13.0231, 80.2188) and state["report_result"]["tracking_code"].startswith("CS-")
    install_map_libs(click={"lat": 28.6, "lng": 77.2})
    f = r.run("public", "page_report", pin, {}, label="click on the map outside the area is refused")
    assert "Outside the area" in f.output() and "Please choose a location inside" in f.output()
    install_map_libs(click=None)
    f = r.run("public", "page_report", pin, {}, label="no click yet: asks the visitor to click")
    assert "Click on the map" in f.output()
    install_map_libs(fail=True)
    f = r.run("public", "page_report", pin, {}, label="a broken map library does not crash the page")
    assert "could not be loaded" in f.output()
    install_map_libs(missing=True)
    gps = {"How would you like to give the location?": "Use my current location", "Describe the problem": "Pothole on Station Road", "Submit complaint": True}
    assert "pip install streamlit-geolocation" in r.run("public", "page_report", gps, {}, label="my location without the package shows install help").output()
    install_gps(position=(13.03, 80.23))
    state = {}
    r.run("public", "page_report", gps, state, label="my location (device) works")
    assert "report_result" in state
    install_gps(position=(51.5, -0.12))
    assert "Outside the area" in r.run("public", "page_report", gps, {}, label="my location outside the area is refused").output()
    install_gps(position=None)
    assert "allow location access" in r.run("public", "page_report", gps, {}, label="location permission not given yet").output()
    install_map_libs(missing=True); install_gps(missing=True)

    # tracking
    f = r.run("public", "page_track", {"Tracking code": code, "Check status": True}, label="track a complaint with its code")
    assert "cs-track" in f.output() and "Routed to" in f.output() and "Gandhi" not in f.output()
    assert "could not find" in r.run("public", "page_track", {"Tracking code": "CS-AAAAAAAA", "Check status": True}, label="unknown code").output()
    f = r.run("public", "page_track", {"Tracking code": code, "Check status": True}, {"failed_lookups": 10}, label="too many wrong codes blocks lookups")
    assert "Too many" in f.output() and "cs-track" not in f.output()

    # abuse protection
    f = r.run("public", "page_report", {**typed, "Describe the problem": "BUY NOW click here http://cheap-deals.xyz free money",
              "Submit complaint": True}, {}, label="spam is refused with a clear message")
    assert "looks like spam" in f.output()
    state = {}
    r.run("public", "page_report", {**typed, "Describe the problem": "Open manhole on Gandhi Street. Call 98765 43210 or ravi@example.com",
          "Submit complaint": True}, state, label="a phone number and an e-mail address in the text are removed")
    f = r.run("public", "page_report", typed, state, label="the citizen is told what was removed")
    assert "we removed" in f.output() and "phone number" in f.output() and "email" in f.output()
    assert not any("98765" in c["text"] or "ravi@example.com" in c["text"] for c in database.query(engine.db))
    flood = {}
    for i in range(5):
        r.run("public", "page_report", {**typed, "Describe the problem": f"Pothole number {i} near the old market on Lake View Road",
              "Submit complaint": True, "Latitude": 13.0 + 0.002 * i, "Longitude": 80.2}, flood, label=f"one visitor sends complaint {i + 1} of 5")
    f = r.run("public", "page_report", {**typed, "Describe the problem": "One pothole too many on Lake View Road", "Submit complaint": True,
              "Latitude": 13.03, "Longitude": 80.2}, flood, label="the sixth complaint in a few minutes is refused")
    assert "Too many requests" in f.output()

    # closing the loop with the citizen
    mine = engine.submit("Garbage not collected near the old market on Nehru Road", 13.006, 80.206)
    code2 = mine["tracking_code"]
    engine.resolve(mine["id"], actor="officer", note="Cleared the pile and added a bin", after_photo=PNG)
    st = {}
    f = r.run("public", "page_track", {"Tracking code": code2, "Check status": True}, st,
              label="a resolved complaint shows its story, the note and the after photo")
    assert "What has happened so far" in f.output() and "Cleared the pile and added a bin" in f.output()
    assert f.called("image") and "Was it really fixed?" in f.output() and "cs-up" in f.output()
    f = r.run("public", "page_track", {"Send feedback": True, "Was the problem fixed?": "No, it is still a problem",
              "Your rating (5 is best)": 1, "Anything to add? (optional)": "The rubbish is back"}, st, label="the citizen says it is not fixed")
    assert f.called("rerun") and engine.get(mine["id"])["status"] == "open" and engine.get(mine["id"])["reopened_count"] == 1
    f = r.run("public", "page_track", {}, st, label="the page confirms the complaint was reopened")
    assert "reopened" in f.output().lower() and "Was it really fixed?" not in f.output()
    officer_view = {"username": "officer", "role": "officer", "crew_id": None}
    f = r.run("officer", "page_overview", user=officer_view, label="officers see the reopened complaint in the attention panel")
    assert "Reopened by citizens" in f.output() and int((engine.open_table()["reopened"] > 0).sum()) == 1
    engine.resolve(mine["id"], actor="officer", note="Cleared again")
    r.run("public", "page_track", {"Send feedback": True, "Was the problem fixed?": "Yes, it is fixed", "Your rating (5 is best)": 5},
          st, label="the citizen confirms the second repair")
    f = r.run("public", "page_track", {}, st, label="the citizen is thanked")
    assert "Thank you for your feedback" in f.output() and "We have your feedback" in f.output()
    f = r.run("public", "page_track", {}, st, label="after feedback the form is gone")
    assert "Was it really fixed?" not in f.output() and "We have your feedback" in f.output()

    # PRIVACY: with real complaints in the database, nothing public reveals them
    engine.seed_demo(30)
    secrets = [c["text"] for c in database.query(engine.db)][:60]
    places_txt = [f"{c['lat']:.4f}" for c in database.query(engine.db)][:40]
    shown_maps = []
    install_components(shown_maps)
    for page in PUB.PAGES:
        f = r.run("public", "main", {"Go to": page}, {}, label=f"citizen main() -> {page}")
        assert all(t not in f.output() for t in secrets), f"citizen page '{page}' leaked a complaint"
        assert not f.called("image") and not f.called("dataframe"), page
        assert "<title>#" not in f.output() and 'fill="url(#csglow' not in f.output(), f"citizen page '{page}' draws individual complaints"
    assert len(shown_maps) == 1, "only the dashboard shows a map"
    ward_page, height = shown_maps[0]
    data = map_data(ward_page)
    assert data["points"] == [] and data["places"] == [] and len(data["wards"]) >= 1
    for c in database.query(engine.db):
        assert f"{c['lat']:.4f}" not in ward_page and f"{c['lon']:.4f}" not in ward_page and c["text"] not in ward_page
    shown_maps.clear()
    install_components(missing=True)
    f = r.run("public", "page_dashboard", label="citizen dashboard with data")
    assert "hidden" in f.output() and "cs-donut" in f.output() and all(p not in f.output() for p in places_txt)
    assert "Where problems are" in f.output() and "<svg" in f.output() and "never exact places" in f.output()   # drawn map: no internet map here
    f = r.run("public", "page_track", {"Tracking code": database.query(engine.db)[5]["tracking_code"], "Check status": True},
              label="tracking a seeded complaint shows no text")
    assert all(t not in f.output() for t in secrets)

    # ================================================================ LANDING PAGE / ROUTER
    print("--- landing page and the two doors")
    f = r.run("app", "main", {}, {}, label="landing page")
    assert "I am a citizen" in f.output() and "I am city staff" in f.output()
    assert all(t not in f.output() for t in secrets) and not f.called("dataframe") and not f.called("image")
    state = {}
    r.run("app", "main", {"Continue as a citizen": True}, state, label="click 'Continue as a citizen'")
    assert state["portal"] == "citizen"
    f = r.run("app", "main", {}, state, label="citizen portal opens (no login)")
    assert "Citizen portal" in f.output() and "Sign-in required" not in f.output()
    assert all(t not in f.output() for t in secrets)
    r.run("app", "main", {"\u2190 Back to home": True}, state, label="citizen goes back to the landing page")
    assert state["portal"] is None
    state = {}
    r.run("app", "main", {"Continue as city staff": True}, state, label="click 'Continue as city staff'")
    assert state["portal"] == "officer"
    f = r.run("app", "main", {}, state, label="officer door shows ONLY a sign-in page")
    assert "Sign-in required" in f.output() and "user" not in state
    assert all(t not in f.output() for t in secrets) and not f.called("dataframe") and not f.called("metric") and not f.called("image")
    for forced in ("admin", "Officer", "", None, 7, "citizen "):
        f = r.run("app", "main", {}, {"portal": forced}, label=f"tampered portal value {forced!r} shows the landing page")
        assert "I am a citizen" in f.output() and all(t not in f.output() for t in secrets)
    f = r.run("app", "main", {}, {"portal": "citizen", "user": None}, label="citizen portal never contains officer pages")
    assert "Overview" not in f.output() or "Citizen portal" in f.output()

    # ================================================================ OFFICER PORTAL
    print("--- officer portal")
    f = Runner(empty_engine).run("officer", "main", label="no accounts: tells you to run create_user.py")
    assert "create_user.py" in f.output()
    auth.create_user(engine.db, "admin", "admin-password-1", "admin")
    auth.create_user(engine.db, "officer", "officer-password-1", "officer")

    f = r.run("officer", "main", {}, {}, label="signed out: sign-in page only")
    assert not f.called("dataframe") and not f.called("metric") and not f.called("image")
    assert all(t not in f.output() for t in secrets) and "Sign-in required" in f.output()
    for page in OFF.OFFICER_PAGES + OFF.ADMIN_PAGES + ["Complaints", "Admin"]:
        f = r.run("officer", "main", {"Go to": page}, {}, label=f"signed out + forced page '{page}'")
        assert all(t not in f.output() for t in secrets) and not f.called("dataframe")

    state = {}
    f = r.run("officer", "main", {"Username": "officer", "Password": "wrong", "Sign in": True}, state, label="wrong password")
    assert "Wrong username or password" in f.output() and "user" not in state
    assert database.audit_entries(engine.db)[0]["action"] == "login_failed"
    assert "Wrong username or password" in r.run("officer", "main", {"Username": "nobody", "Password": "x", "Sign in": True}, state,
                                                 label="unknown user: same message").output()
    for _ in range(auth.MAX_FAILED):
        r.run("officer", "main", {"Username": "officer", "Password": "wrong", "Sign in": True}, state, label="repeated wrong password")
    f = r.run("officer", "main", {"Username": "officer", "Password": "officer-password-1", "Sign in": True}, state,
              label="locked account refuses even the right password")
    assert "Too many failed attempts" in f.output() and "user" not in state
    database.update_user(engine.db, "officer", locked_until=None, failed_attempts=0)

    # sign in THROUGH the landing page, then use every page
    portal_state = {"portal": "officer"}
    f = r.run("app", "main", {"Username": "officer", "Password": "officer-password-1", "Sign in": True}, portal_state,
              label="officer signs in through the landing page")
    assert f.called("rerun") and portal_state["user"] == {"username": "officer", "role": "officer", "crew_id": None}
    for page in OFF.OFFICER_PAGES:
        f = r.run("app", "main", {"Go to": page}, portal_state, label=f"officer main() -> {page}")
        assert f.called("markdown")
    f = r.run("app", "main", {"Go to": O_OVERVIEW}, portal_state, label="officer overview shows the attention panel")
    assert "Needs attention now" in f.output() and "cs-donut" in f.output()
    f = r.run("app", "main", {"Go to": O_COMPLAINTS}, portal_state, label="officer sees complaint details")
    assert any(t[:25] in f.output() for t in secrets)
    # sign-out when leaving
    leave_state = dict(portal_state)
    r.run("app", "main", {"\u2190 Back to home (signs you out)": True}, leave_state, label="leaving the officer portal signs the officer out")
    assert leave_state["portal"] is None and "user" not in leave_state
    assert database.audit_entries(engine.db)[0]["action"] == "logout"
    f = r.run("app", "main", {}, leave_state, label="after leaving, the landing page shows no complaints")
    assert all(t not in f.output() for t in secrets)
    f = r.run("app", "main", {}, {**leave_state, "portal": "officer"}, label="going back in needs a new sign-in")
    assert "Sign-in required" in f.output() and not f.called("dataframe")

    # clickable rows and the fallback
    officer = {"username": "officer", "role": "officer", "crew_id": None}
    table = engine.open_table()
    photo_row = list(table["id"]).index(photo_id)
    f = r.run("officer", "page_complaints", {"queue_row": photo_row}, user=officer, label="clicking a row opens that complaint (with its photo)")
    assert f.called("image") and "Click a row to open it" in f.output()
    f = r.run("officer", "page_complaints", {}, user=officer, label="no row clicked: the most urgent complaint opens")
    assert f"Complaint #{table.iloc[0]['id']}" in f.output()
    f = r.run("officer", "page_complaints", {"Open a complaint": int(table.iloc[3]["id"])}, user=officer, selectable=False,
              label="older Streamlit without clickable rows falls back to a select box")
    assert f"Complaint #{table.iloc[3]['id']}" in f.output()
    f = r.run("officer", "page_complaints", {"Priority": ["critical"]}, user=officer, label="filter: critical only")
    f = r.run("officer", "page_complaints", {"Priority": []}, user=officer, label="filter: nothing matches")
    assert "No complaints match" in f.output()
    r.run("officer", "page_complaints", {"Department": table["department"].iloc[0]}, user=officer, label="filter: one department")
    r.run("officer", "page_complaints", {"Waiting for review only": True}, user=officer, label="filter: waiting for review")

    # hotspot map and priority guide
    f = r.run("officer", "page_map", user=officer, label="hotspot view: map, places and ward ranking")
    assert "<svg" in f.output() and "Which wards need attention first" in f.output() and f.called("dataframe")
    assert ">S<" in f.output() and 'fill="url(#csglowa)"' in f.output()
    f = r.run("officer", "page_map", {"Show schools, hospitals and public places": False, "Show density glow": False}, user=officer,
              label="hotspot view: places and glow switched off")
    assert ">S<" not in f.output() and 'fill="url(#csglowa)"' not in f.output()
    f = r.run("officer", "page_map", {"Category": ["Road"]}, user=officer, label="hotspot view: one category")
    f = r.run("officer", "page_map", {"Category": []}, user=officer, label="hotspot view: no category shows an empty map, not a crash")
    assert "<svg" in f.output() and "Which wards need attention first" in f.output()          # an empty map, not a crash
    f = r.run("officer", "page_map", {"Only high and critical complaints": True}, user=officer, label="hotspot view: urgent only")
    street = []
    install_components(street)
    f = r.run("officer", "page_map", user=officer, label="the real street map is shown with every open complaint")
    open_count = len(engine.open_table())
    page, height = street[-1]
    assert "leaflet@1.9.4" in page and height == 560 and len(map_data(page)["points"]) == open_count
    assert len(map_data(page)["places"]) == len(places.all_places()) and "street map" in f.output() and "could not be shown" not in f.output()
    f = r.run("officer", "page_map", {"Category": ["Road"]}, user=officer, label="street map: one category only")
    assert {p["category"] for p in map_data(street[-1][0])["points"]} == {"Road"}
    f = r.run("officer", "page_map", {"Show schools, hospitals and public places": False, "Show density glow": False}, user=officer,
              label="street map: places and glow switched off")
    data = map_data(street[-1][0])
    assert data["places"] == [] and data["density"] is False
    f = r.run("officer", "page_map", {"Only high and critical complaints": True}, user=officer, label="street map: urgent only")
    assert {p["priority"] for p in map_data(street[-1][0])["points"]} <= {"high", "critical"}
    install_components(missing=True)
    f = r.run("officer", "page_map", user=officer, label="street map unavailable: falls back to the schematic view")
    assert "could not be shown" in f.output() and "<svg" in f.output()
    install_components([], fail=True)
    f = r.run("officer", "page_map", user=officer, label="a failing map component does not crash the page")
    assert "could not be shown" in f.output() and "<svg" in f.output()
    install_components(missing=True)
    f = r.run("officer", "page_guide", user=officer, label="priority guide shows the matrix")
    assert "cs-mx" in f.output() and "Busy public place" in f.output() and "Near a school" in f.output() and "Open manhole" in f.output()
    f = r.run("officer", "page_guide", {"Problem": "Pothole", "Where is it?": "Near a school", "Duplicate reports so far": 3,
              "Children are affected": True}, user=officer, label="priority guide: try it yourself")
    assert "CRITICAL" in f.output() and "Children at risk" in f.output()
    f = r.run("officer", "page_guide", {"Problem": "Pothole"}, user=officer, label="priority guide: ordinary street stays medium")
    assert "MEDIUM" in f.output()

    # resolving with a note and an after photo
    res = engine.submit("Pothole near the old market on Canal Bank Road", 13.0151, 80.2149)
    idx = list(engine.open_table()["id"]).index(res["id"])
    r.run("officer", "page_complaints", {"queue_row": idx, "Resolution note (the citizen will see this)": "Filled it, call 98765 43210 if it returns",
          "After photo (optional)": FakeUpload(PNG), "Mark as resolved": True}, user=officer, label="officer resolves with a note and an after photo")
    assert engine.get(res["id"])["status"] == "resolved" and engine.public_after_photo(res["tracking_code"])
    assert "98765" not in engine.public_status(res["tracking_code"])["updates"][-1]["message"]
    bad = engine.submit("Streetlight not working on Park Avenue for a week", 13.0301, 80.2301)
    idx = list(engine.open_table()["id"]).index(bad["id"])
    f = r.run("officer", "page_complaints", {"queue_row": idx, "After photo (optional)": FakeUpload(b"not an image"), "Mark as resolved": True},
              user=officer, label="a bad after photo is refused and the complaint stays open")
    assert "could not be read" in f.output() and engine.get(bad["id"])["status"] == "open"

    # field crews
    busy = [c.id for c in engine.crews if engine.crew_route(c.id)["todo"]]
    assert len(busy) >= 2
    crew_id = busy[0]
    auth.create_user(engine.db, "crew_a", "crew-password-1", "crew", crew_id=crew_id)
    crew_user = {"username": "crew_a", "role": "crew", "crew_id": crew_id}
    route = engine.crew_route(crew_id)
    own_ids = {t["row"]["id"] for t in route["todo"]}
    own_text = route["todo"][0]["row"]["text"]
    foreign_texts = [c["text"] for c in engine._roots("open") if c["id"] not in own_ids]
    crew_state = {"portal": "officer"}
    f = r.run("app", "main", {"Username": "crew_a", "Password": "crew-password-1", "Sign in": True}, crew_state, label="a crew member signs in through the staff door")
    assert crew_state["user"] == crew_user
    f = r.run("app", "main", {}, crew_state, label="the crew sees its own route and nothing else")
    assert f"Crew {crew_id}" in f.output() and own_text in f.output() and "Open in Maps" in f.output()
    assert all(t not in f.output() for t in foreign_texts), "a crew saw a job from another crew's route"
    assert "Hotspot map" not in f.output() and "Priority guide" not in f.output() and not f.called("dataframe")
    for page in ("page_overview", "page_complaints", "page_schedule", "page_map", "page_guide", "page_insights", "page_model"):
        f = r.run("officer", page, user=crew_user, label=f"a crew account cannot open {page}")
        assert "cannot open this page" in f.output() and not f.called("dataframe") and not f.called("metric") and "<svg" not in f.output()
    for page in ("page_admin", "page_audit"):
        f = r.run("officer", page, user=crew_user, label=f"a crew account cannot open {page}")
        assert "Only admins" in f.output() and not f.called("dataframe")
    f = r.run("crew", "page_route", user=officer, label="an officer account cannot use the crew page")
    assert "cannot open this page" in f.output() and own_text not in f.output()
    first = route["todo"][0]["row"]
    f = r.run("crew", "page_route", {"Start work": True}, user=crew_user, label="the crew starts its first job")
    assert f.called("rerun") and engine.get(first["id"])["status"] == "in_progress"
    f = r.run("crew", "page_route", user=crew_user, label="the started job shows under 'In progress'")
    assert "In progress" in f.output() and first["text"] in f.output()
    f = r.run("crew", "page_route", {"Mark done": True, "What did you do?": "Patched and cleaned", "After photo (optional)": FakeUpload(PNG)},
              user=crew_user, label="the crew finishes the job with a note and a photo")
    assert engine.get(first["id"])["status"] == "resolved" and engine.get(first["id"])["resolution_note"] == "Patched and cleaned"
    assert database.audit_entries(engine.db)[0]["username"] == "crew_a" and engine.public_after_photo(engine.get(first["id"])["tracking_code"])
    leave = dict(crew_state, last_active=dt.datetime.now().isoformat())
    r.run("app", "main", {"Sign out": True}, leave, label="the crew signs out")
    assert "user" not in leave

    f = r.run("officer", "page_insights", user=officer, label="insights show what citizens say about the repairs")
    assert "Do citizens say it was really fixed?" in f.output() and "Average rating" in f.output() and "Said it was fixed" in f.output()

    # roles
    before = engine.count()
    f = r.run("officer", "page_admin", {"Reset database": True, "I understand that resetting deletes every complaint and photo": True,
              "Simulate monsoon surge (+40 drainage complaints)": True}, user=officer, label="officer cannot use the Admin page")
    assert "Only admins" in f.output() and not f.called("dataframe") and engine.count() == before
    f = r.run("officer", "page_audit", user=officer, label="officer cannot read the audit log")
    assert "Only admins" in f.output() and not f.called("dataframe")
    # officer actions are attributed
    review = engine.open_table().query("needs_review")
    top = int(engine.open_table().iloc[0]["id"])
    r.run("officer", "page_complaints", {"Mark as resolved": True}, user=officer, label="officer resolves the top complaint")
    assert engine.get(top)["status"] == "resolved"
    last = database.audit_entries(engine.db)[0]
    assert last["username"] == "officer" and last["action"] == "resolve"
    if len(review):
        idx = list(engine.open_table()["id"]).index(int(review.iloc[0]["id"]))
        r.run("officer", "page_complaints", {"queue_row": idx, "Correct category": "Road", "Priority after review": "high",
              "Confirm and save correction": True}, user=officer, label="officer reviews a low-confidence complaint")
        assert engine.get(int(review.iloc[0]["id"]))["needs_review"] == 0
    # sessions
    stale = {"user": officer, "last_active": (dt.datetime.now() - dt.timedelta(hours=2)).isoformat()}
    f = r.run("officer", "main", {}, stale, label="an old session expires")
    assert "session expired" in f.output() and "user" not in stale and not f.called("dataframe")
    deactivated = {"user": officer, "last_active": dt.datetime.now().isoformat()}
    database.update_user(engine.db, "officer", active=0)
    f = r.run("officer", "main", {}, deactivated, label="a deactivated account is signed out immediately")
    assert "no longer active" in f.output() and "user" not in deactivated
    database.update_user(engine.db, "officer", active=1)
    demoted = {"user": {"username": "officer", "role": "admin"}, "last_active": dt.datetime.now().isoformat()}
    f = r.run("officer", "main", {"Go to": O_OVERVIEW}, demoted, label="role comes from the database, not the session")
    assert "(officer)" in f.output() and "(admin)" not in f.output()
    out_state = {"user": officer, "last_active": dt.datetime.now().isoformat()}
    r.run("officer", "main", {"Sign out": True}, out_state, label="sign out button")
    assert "user" not in out_state

    # admin
    admin_state = {}
    r.run("officer", "main", {"Username": "Admin", "Password": "admin-password-1", "Sign in": True}, admin_state, label="admin signs in (any case)")
    admin = admin_state["user"]
    for page in (O_AUDIT, O_ADMIN):
        f = r.run("officer", "main", {"Go to": page}, admin_state, label=f"admin main() -> {page}")
        assert f.called("dataframe")
    f = r.run("officer", "page_admin", {"New username": "newofficer", "Password (8+ characters)": "long-password-1",
              "Role": "officer", "Create account": True}, user=admin, label="admin creates an account")
    assert "Account created" in f.output() and database.get_user(engine.db, "newofficer")
    f = r.run("officer", "page_admin", {"New username": "crew_b", "Password (8+ characters)": "long-password-1", "Role": "crew",
              "Crew (for crew accounts)": "SAN-2", "Create account": True}, user=admin, label="admin creates a crew account")
    made = database.get_user(engine.db, "crew_b")
    assert "Account created" in f.output() and made["role"] == "crew" and made["crew_id"] == "SAN-2"
    from modules import evaluate as ev_mod
    calls, real = [], ev_mod.evaluate
    try:
        r.run("officer", "page_admin", {"Re-run model evaluation": True}, user=admin, label="admin re-runs the model evaluation",
              patch=lambda m: setattr(ev_mod, "evaluate", lambda *a, **k: calls.append(1)))
    finally:
        ev_mod.evaluate = real
    assert calls == [1] and "run_evaluation" in [a["action"] for a in database.audit_entries(engine.db)[:3]]
    calls.clear()
    try:
        r.run("officer", "page_admin", {"Re-run model evaluation": True}, user=officer, label="an officer cannot re-run the evaluation",
              patch=lambda m: setattr(ev_mod, "evaluate", lambda *a, **k: calls.append(1)))
    finally:
        ev_mod.evaluate = real
    assert calls == []
    assert "already exists" in r.run("officer", "page_admin", {"New username": "newofficer", "Password (8+ characters)": "long-password-1",
              "Create account": True}, user=admin, label="duplicate account is refused").output()
    assert "at least 8" in r.run("officer", "page_admin", {"New username": "weak", "Password (8+ characters)": "123",
              "Create account": True}, user=admin, label="weak password is refused").output()
    r.run("officer", "page_admin", {"Reset database": True}, user=admin, label="reset without the confirmation tick does nothing")
    assert engine.count() > 0
    count = engine.count()
    r.run("officer", "page_admin", {"Simulate monsoon surge (+40 drainage complaints)": True}, user=admin, label="admin simulates a monsoon surge")
    assert engine.count() > count + 25 and database.audit_entries(engine.db)[0]["action"] == "simulate_surge"
    f = r.run("officer", "page_schedule", user=admin, label="crew schedule after the surge")
    assert "cs-tl" in f.output()
    export_path = os.path.join(folder, "corrections.csv")
    real_export = engine.export_corrections
    engine.export_corrections = lambda path=export_path, actor=None: real_export(path, actor)
    r.run("officer", "page_admin", {"Export corrections": True}, user=admin, label="admin exports corrections")
    engine.export_corrections = real_export
    assert os.path.exists(export_path)
    f = r.run("officer", "page_audit", user=admin, label="admin reads the audit log")
    assert "resolve" in f.output() and "login" in f.output() and "logout" in f.output()
    f = r.run("officer", "page_admin", {"Reset database": True, "I understand that resetting deletes every complaint and photo": True},
              user=admin, label="admin resets the database")
    assert engine.count() == 0 and database.get_user(engine.db, "admin") and f.called("rerun")
    assert database.audit_entries(engine.db)[0]["action"] == "reset_database"
    r.run("officer", "page_admin", {"Load demo data (60 complaints)": True}, user=admin, label="admin loads demo data")
    assert engine.count() > 50
    f = r.run("officer", "page_insights", user=admin, label="insights page")
    assert "Do citizens say it was really fixed?" in f.output() and "No feedback yet" in f.output()      # the reset removed the ratings
    f = r.run("officer", "page_model", user=officer, label="model performance page")
    assert "Most common answer (baseline)" in f.output() and "cs-cm" in f.output() and "Where the mistakes are" in f.output()
    assert "Category, hard cases" in f.output() and "Clear text sent to a person" in f.output()
    f = r.run("officer", "page_model", {"What to look at": "Priority", "Test set": "Easy test", "Model": "Random Forest"}, user=officer,
              label="model page: priority, easy test, another model")
    assert "within one level" in f.output() and "weak score" in f.output()
    real_load = ev_mod.load_results
    try:
        f = r.run("officer", "page_model", user=officer, label="model page without a saved evaluation explains how to create one",
                  patch=lambda m: setattr(ev_mod, "load_results", lambda *a, **k: None))
    finally:
        ev_mod.load_results = real_load
    assert "has not been run yet" in f.output() and not f.called("dataframe")
    print(f"\n{r.passed} checks passed")


if __name__ == "__main__":
    main()
