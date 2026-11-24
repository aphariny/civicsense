"""CivicSense: ONE portal with a citizen side and an officer side.   Run:  streamlit run app.py

The landing page offers two doors. 'Citizen' opens the public portal (report and track a complaint, no account).
'City staff' opens the staff portal, which shows nothing until an officer or crew member signs in. Leaving the officer portal
signs the officer out, so someone on a shared computer cannot walk into an open session.
"""
import streamlit as st

import officer_app
import public_app
import ui
from app_common import get_engine, html

PORTALS = ("citizen", "officer")


def choose(portal):
    st.session_state["portal"] = portal


def leave(engine):
    """Back to the landing page. An officer who leaves is signed out."""
    if st.session_state.get("portal") == "officer":
        officer_app.sign_out(engine)
    st.session_state["portal"] = None


def landing(engine):
    html(ui.hero("CivicSense", "One portal for citizens and city officers. Report problems, follow them, and get them fixed.",
                 pill="Choose how you want to continue", icon_name="building"))
    left, right = st.columns(2)
    with left:
        html(ui.portal_card("citizen"))
        st.button("Continue as a citizen", key="go_citizen", type="primary", on_click=choose, args=("citizen",))
    with right:
        html(ui.portal_card("officer"))
        st.button("Continue as city staff", key="go_officer", on_click=choose, args=("officer",))
    stats = engine.public_stats()
    if stats["issues"]:
        html(ui.section("chart", "Your city right now"))
        html(public_app._stats_cards(stats))
    st.caption("Citizens never see other people's complaints. The officer side needs an account and records every action.")


def main():
    st.set_page_config(page_title="CivicSense", page_icon="\U0001F3D9\uFE0F", layout="wide")
    html(ui.css())
    engine = get_engine()
    portal = st.session_state.get("portal")
    if portal not in PORTALS:                       # anything unexpected means: show the landing page
        portal = None
    if portal == "citizen":
        public_app.render(engine, leave=lambda: leave(engine))
    elif portal == "officer":
        officer_app.render(engine, leave=lambda: leave(engine))
    else:
        landing(engine)


if __name__ == "__main__":
    main()
