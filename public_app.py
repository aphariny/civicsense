"""CivicSense PUBLIC portal: report a problem, track it, see city-wide figures.

Opened from the landing page in app.py (streamlit run app.py). It can also run alone: streamlit run public_app.py
Nothing here shows another person's complaint: no text, no photos, no exact locations.
"""
import secrets

import streamlit as st

import ui
from app_common import get_engine, html, show_html_map
from location_picker import pick_location
from modules.geo import WARD_CENTRES

PAGES = ["\U0001F3E0 Home", "\U0001F4CD Report a problem", "\U0001F50E Track my complaint", "\U0001F3D9\uFE0F City dashboard"]
MAX_FAILED_LOOKUPS = 10
EXAMPLES = {"Open manhole": "Open manhole near the government school on Gandhi Street, a child almost fell in",
            "Broken streetlight": "Streetlight not working on Station Road for 3 days, the lane is dark at night",
            "Garbage pile-up": "Garbage not collected near the market for a week, bad smell and stray dogs",
            "Pipe leakage": "Water pipe leaking on the main road, a lot of water is being wasted"}


def _text_key():
    return f"complaint_text_{st.session_state.get('form_n', 0)}"


def _use_example(text):
    st.session_state[_text_key()] = text


def _client_key():
    """An opaque id for this browser session, used only to limit how fast one visitor can send things."""
    if "client_key" not in st.session_state:
        st.session_state["client_key"] = secrets.token_hex(8)
    return st.session_state["client_key"]


def _new_report():
    st.session_state.pop("report_result", None)


def _stats_cards(stats):
    avg = f"{stats['avg_days']:.1f}" if stats["avg_days"] is not None else "n/a"
    return ui.kpis([("Problems reported", stats["issues"], "blue", "", "clipboard"), ("Resolved", stats["resolved"], "blue", "", "check"),
                    ("Still open", stats["open"], "red", "", "alert"), ("Average days to resolve", avg, "blue", "", "clock")])


# ----------------------------------------------------------------------------- pages
def page_home(engine):
    html(ui.hero("Report a problem. Track it to the end.",
                 "CivicSense sends every complaint to the right department and shows you where it stands.",
                 pill="Citizen portal - no login needed", icon_name="pin"))
    html(ui.public_steps())
    stats = engine.public_stats()
    if stats["issues"]:
        html(ui.section("chart", "Your city right now"))
        html(_stats_cards(stats))
    st.caption("Complaint details, photos and exact locations are visible only to authorised officers.")


def page_report(engine):
    html(ui.page_header("Report a problem", "Say where it is, describe it, and add a photo if you can."))
    left, right = st.columns([5, 4])
    with left:
        html(ui.section("pin", "1. Where is the problem?"))
        loc = pick_location()
        html(ui.section("clipboard", "2. What is the problem?"))
        st.caption("Not sure what to write? Try an example:")
        for col, (label, text) in zip(st.columns(len(EXAMPLES)), EXAMPLES.items()):
            col.button(label, key=f"example_{label}", on_click=_use_example, args=(text,))
        text = st.text_area("Describe the problem", key=_text_key(), placeholder="e.g. Open manhole near the school on Gandhi Street")
        preview = engine.preview(text)
        if preview:
            html(ui.ai_preview(preview["category"], preview["confidence"], preview["department"], preview["needs_review"]))
        html(ui.section("camera", "3. Add a photo (optional)"))
        photo = st.file_uploader("Attach a photo (optional)", type=["jpg", "jpeg", "png"], key=f"photo_{st.session_state.get('form_n', 0)}")
        st.caption("Only officers can see your photo. The AI reads the text; photo analysis is planned future work.")
        send = st.button("Submit complaint", type="primary")
    with right:
        if send:
            if not loc or not loc["ok"]:
                st.error("Please choose a location inside the service area first.")
            else:
                try:
                    result = engine.submit(text, loc["lat"], loc["lon"], photo=photo.getvalue() if photo else None, client_key=_client_key())
                except ValueError as err:
                    st.error(str(err))
                else:
                    st.session_state["report_result"] = result
                    st.session_state["form_n"] = st.session_state.get("form_n", 0) + 1     # a fresh, empty form next time
                    if hasattr(st, "toast"):
                        st.toast("Complaint received", icon="\u2705")
                    st.rerun()
        result = st.session_state.get("report_result")
        if result:
            html(ui.section("check", "Your complaint was received"))
            html(ui.code_box(result["tracking_code"]))
            st.caption("Save this code. It is the only way to check your complaint's progress.")
            if result.get("pii_removed"):
                st.info("To protect your privacy we removed " + " and ".join(result["pii_removed"]) + " from your description.")
            if result["merged_into"]:
                st.info("Other residents have reported the same problem nearby. Your report was added to it, "
                        "which helps the authorities see how many people are affected.")
            if result["needs_review"]:
                st.warning("An officer will review your complaint to make sure it goes to the right place.")
            else:
                st.write(f"We understood this as a **{result['category']}** problem and sent it to **{result['department']}**.")
            st.button("Report another problem", on_click=_new_report)
        elif not send:
            html(ui.section("sparkle", "What happens next"))
            html(ui.public_steps())


def page_track(engine):
    html(ui.page_header("Track my complaint", "Enter the code you received when you reported the problem."))
    with st.form("track_form"):
        code_in = st.text_input("Tracking code", placeholder="CS-XXXXXXXX", max_chars=20)
        checked = st.form_submit_button("Check status")
    if checked:
        if st.session_state.get("failed_lookups", 0) >= MAX_FAILED_LOOKUPS:
            st.error("Too many unknown codes were entered. Please try again later.")
            return
        found = engine.public_status(code_in)
        if found is None:
            st.session_state.pop("tracked_code", None)
            st.session_state["failed_lookups"] = st.session_state.get("failed_lookups", 0) + 1
            st.error("We could not find that code. Please check it and try again.")
            return
        st.session_state["tracked_code"] = found["code"]
    code = st.session_state.get("tracked_code")
    if not code:
        return
    status = engine.public_status(code)
    if status is None:
        st.session_state.pop("tracked_code", None)
        return
    html(ui.tracker(status["stage"], engine.STAGES, current_label=status["stage_label"]))
    st.write(f"Reported on **{status['submitted']}** as a **{status['category']}** problem.")
    if status["updates"]:
        html(ui.section("clock", "What has happened so far"))
        html(ui.updates_timeline(status["updates"]))
    after = engine.public_after_photo(code)
    if after:
        st.image(after, caption="Photo of the finished repair")
    if status["resolved_on"]:
        st.success(f"Resolved on {status['resolved_on']}.")
    if status["can_give_feedback"]:
        html(ui.section("check", "Was it really fixed?"))
        with st.form("feedback_form"):
            answer = st.radio("Was the problem fixed?", ["Yes, it is fixed", "No, it is still a problem"])
            rating = st.selectbox("Your rating (5 is best)", [5, 4, 3, 2, 1])
            comment = st.text_area("Anything to add? (optional)", key="feedback_comment", max_chars=300)
            sent = st.form_submit_button("Send feedback")
        if sent:
            try:
                outcome = engine.submit_feedback(code, answer.startswith("Yes"), rating, comment, client_key=_client_key())
            except ValueError as err:
                st.error(str(err))
            else:
                st.session_state["feedback_outcome"] = outcome["reopened"]
                st.rerun()
    elif status["feedback_given"]:
        st.caption("Thank you. We have your feedback on this repair.")
    outcome = st.session_state.pop("feedback_outcome", None)
    if outcome is True:
        st.warning("Thank you for telling us. Your complaint has been reopened and will be looked at again.")
    elif outcome is False:
        st.success("Thank you for your feedback.")


def page_dashboard(engine):
    html(ui.page_header("City dashboard", "What residents are reporting and how it is going. No personal details are shown."))
    stats = engine.public_stats()
    if not stats["issues"]:
        st.info("Nothing has been reported yet.")
        return
    html(_stats_cards(stats))
    left, right = st.columns(2)
    with left:
        html(ui.section("check", "How many are fixed"))
        html(ui.donut([("Resolved", stats["resolved"], "#2E7D32"), ("Still open", stats["open"], ui.RED)],
                      f"{stats['resolved'] / stats['issues']:.0%}", "resolved"))
    with right:
        html(ui.section("layers", "By category"))
        html(ui.bars(sorted(((c, n, ui.BLUE) for c, n in stats["by_category"].items()), key=lambda x: -x[1])))
    html(ui.section("map", "Where problems are"))
    if stats["by_ward"]:
        shown = set(stats["by_ward"])
        hidden = [w for w in WARD_CENTRES if w not in shown]
        if not show_html_map(ui.leaflet_ward_html(stats["by_ward"], hidden), height=460):     # no internet map: draw our own
            html(ui.ward_map_svg(stats["by_ward"], hidden))
        html(ui.bars([(f"Ward {w}", n, ui.BLUE) for w, n in stats["by_ward"].items()]))
    st.caption("The map shows ward totals only, never exact places, and needs an internet connection for the map tiles. "
               "Wards with only one or two complaints are hidden (dashed circles) to protect people's privacy.")


# ----------------------------------------------------------------------------- entry points
def render(engine, leave=None):
    """Draw the citizen portal. leave: a function that returns to the landing page (set by app.py)."""
    st.sidebar.title("CivicSense")
    st.sidebar.caption("Citizen portal")
    page = st.sidebar.radio("Go to", PAGES)
    if leave is not None:
        st.sidebar.button("\u2190 Back to home", key="citizen_home", on_click=leave)
    {PAGES[0]: page_home, PAGES[1]: page_report, PAGES[2]: page_track, PAGES[3]: page_dashboard}[page](engine)


def main():
    st.set_page_config(page_title="CivicSense - Report a problem", page_icon="\U0001F3D9\uFE0F", layout="wide")
    html(ui.css())
    render(get_engine())


if __name__ == "__main__":
    main()
