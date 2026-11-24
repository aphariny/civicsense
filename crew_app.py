"""CivicSense FIELD CREW view: one crew's route for the day, on a phone-friendly page.

Opened through the staff door in app.py: a crew account signs in and lands here. A crew sees only the jobs on its own
route, can start a job, and finishes it with a note and an 'after' photo. The engine refuses anything outside the route.
"""
import streamlit as st

import auth
import ui
from app_common import html
from modules import places


def denied(user, permission):
    if auth.can(user, permission):
        return False
    st.error("Your account cannot open this page.")
    return True


def _clock(engine, minutes):
    return engine.clock_time(minutes)


def _finish_form(engine, user, row):
    cid = row["id"]
    with st.form(f"finish_{cid}"):
        note = st.text_input("What did you do?", key=f"note_{cid}", placeholder="e.g. Filled the pothole and levelled the surface")
        photo = st.file_uploader("After photo (optional)", type=["jpg", "jpeg", "png"], key=f"after_{cid}")
        done = st.form_submit_button("Mark done")
    if done:
        try:
            engine.crew_finish(cid, user["crew_id"], user["username"], note=note, after_photo=photo.getvalue() if photo else None)
        except (ValueError, PermissionError) as err:
            st.error(str(err))
            return
        if hasattr(st, "toast"):
            st.toast("Job marked done", icon="\u2705")
        st.rerun()


def page_route(engine, user):
    if denied(user, "crew_work"):
        return
    crew_id = user["crew_id"]
    html(ui.hero(f"Crew {crew_id}", "Your route for today. Work through the jobs in order.", tone="blue",
                 pill=f"Signed in as {user['username']}", icon_name="truck"))
    route = engine.crew_route(crew_id)
    todo, started = route["todo"], route["in_progress"]
    html(ui.kpis([("Jobs to do", len(todo), "blue", "", "clipboard"), ("In progress", len(started), "red" if started else "blue", "", "clock"),
                  ("Next stop", _clock(engine, todo[0]["arrive"]) if todo else "-", "blue", "", "route")]))
    if not todo and not started:
        st.success("No jobs on your route right now. Check back later.")
        return
    if started:
        html(ui.section("clock", "In progress"))
        for row in started:
            html(ui.stop_card(row, "now", "-", number=None, near=places.near(row["lat"], row["lon"])))
            _finish_form(engine, user, row)
    if todo:
        html(ui.section("route", "Your route"))
        for stop in todo:
            row = stop["row"]
            html(ui.stop_card(row, _clock(engine, stop["arrive"]), _clock(engine, stop["deadline"]), stop["late"], stop["stop"],
                              places.near(row["lat"], row["lon"])))
            if st.button("Start work", key=f"start_{row['id']}"):
                try:
                    engine.crew_start(row["id"], crew_id, user["username"])
                except (ValueError, PermissionError) as err:
                    st.error(str(err))
                else:
                    st.rerun()
            with st.expander("Finish this job"):
                _finish_form(engine, user, row)


def render(engine, user, leave=None, sign_out=None):
    """The crew portal. sign_out and leave are functions supplied by officer_app / app."""
    st.sidebar.title("CivicSense")
    st.sidebar.caption(f"Crew {user['crew_id']} - signed in as {user['username']}")
    if sign_out is not None:
        st.sidebar.button("Sign out", key="crew_sign_out", on_click=sign_out)
    if leave is not None:
        st.sidebar.button("\u2190 Back to home (signs you out)", key="crew_home", on_click=leave)
    page_route(engine, user)
