"""Pieces shared by the public portal and the officer portal."""
import streamlit as st

from pipeline import Engine


@st.cache_resource
def get_engine():
    return Engine()


def html(markup):
    st.markdown(markup, unsafe_allow_html=True)


def show_html_map(page, height=540):
    """Show a complete HTML page (a Leaflet map) inside the app. Returns False if Streamlit cannot do it."""
    try:
        from streamlit.components.v1 import html as render_html
        render_html(page, height=height)
        return True
    except Exception:
        return False
