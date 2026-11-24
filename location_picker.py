"""Lets a resident say exactly where a problem is.

Four ways: click on a map, use the phone/computer's location, type coordinates, or pick a ward.
The click map and the GPS button need two optional packages (folium + streamlit-folium, streamlit-geolocation);
without them those two options show how to install them and the other two options still work.
Whatever the method, a location outside the service area is refused.
"""
import pandas as pd
import streamlit as st

import ui
from modules import places
from modules.geo import SERVICE_AREA, WARD_CENTRES, in_service_area

DEFAULT = (13.020, 80.220)
METHODS = ["Pin on the map", "Use my current location", "Type coordinates", "Pick a ward"]
MAP_HELP = "The click-to-pin map needs two extra packages: `pip install folium streamlit-folium`. Meanwhile use another option."
GPS_HELP = "Using your location needs one extra package: `pip install streamlit-geolocation`. Meanwhile use another option."


def _html(markup):
    st.markdown(markup, unsafe_allow_html=True)


def _map_pin(center):
    """Click-to-pin map. Returns (lat, lon) of the last click, None before any click, or 'missing' / 'error'."""
    try:
        import folium
        from streamlit_folium import st_folium
    except ImportError:
        return "missing"
    try:
        a = SERVICE_AREA
        m = folium.Map(location=list(center), zoom_start=15, control_scale=True)
        folium.Rectangle(bounds=[[a["lat_min"], a["lon_min"]], [a["lat_max"], a["lon_max"]]],
                         color="#C1292E", weight=2, fill=False, tooltip="Service area").add_to(m)
        folium.Marker(list(center), tooltip="Selected location").add_to(m)
        out = st_folium(m, height=380, returned_objects=["last_clicked"], key="pin_map")
        click = (out or {}).get("last_clicked")
        if click and "lat" in click and "lng" in click:
            return float(click["lat"]), float(click["lng"])
        return None
    except Exception:                                  # a library change must never take the page down
        return "error"


def _geolocate():
    """The browser's location. Returns (lat, lon), None until the user allows it, or 'missing' / 'error'."""
    try:
        from streamlit_geolocation import streamlit_geolocation
    except ImportError:
        return "missing"
    try:
        loc = streamlit_geolocation()
    except Exception:
        return "error"
    if loc and loc.get("latitude") is not None and loc.get("longitude") is not None:
        return float(loc["latitude"]), float(loc["longitude"])
    return None


def _preview(lat, lon):
    frame = pd.DataFrame({"lat": [lat], "lon": [lon]})
    try:
        st.map(frame, zoom=15)
    except TypeError:                                  # older Streamlit has no zoom option
        st.map(frame)


def pick_location():
    """Show the location options. Returns {'lat', 'lon', 'ok', 'source'} or None if nothing is chosen yet."""
    method = st.radio("How would you like to give the location?", METHODS, horizontal=True)
    lat = lon = None
    note = ""
    if method == METHODS[0]:
        pin = st.session_state.get("pin")
        result = _map_pin(pin or DEFAULT)
        if isinstance(result, tuple):
            st.session_state["pin"] = pin = result
        elif result == "missing":
            st.info(MAP_HELP)
        elif result == "error":
            st.warning("The map could not be loaded. Please use another option.")
        if pin and result not in ("missing", "error"):
            lat, lon = pin
        elif result not in ("missing", "error"):
            st.caption("Click on the map to drop a pin on the problem.")
    elif method == METHODS[1]:
        result = _geolocate()
        if isinstance(result, tuple):
            lat, lon = result
            note = "Taken from your device. Check that it is where the problem is."
        elif result == "missing":
            st.info(GPS_HELP)
        elif result == "error":
            st.warning("Your location could not be read. Please use another option.")
        else:
            st.caption("Press the button above and allow location access in your browser.")
    elif method == METHODS[2]:
        c1, c2 = st.columns(2)
        lat = c1.number_input("Latitude", value=DEFAULT[0], format="%.5f")
        lon = c2.number_input("Longitude", value=DEFAULT[1], format="%.5f")
    else:
        ward = st.selectbox("Ward", list(WARD_CENTRES), format_func=lambda w: f"Ward {w}")
        lat, lon = WARD_CENTRES[ward]
        note = "Approximate: the centre of the ward. Use the map for an exact spot."
    if lat is None:
        return None
    ok = in_service_area(lat, lon)
    _html(ui.location_card(lat, lon, method, ok, note, nearby=places.near(lat, lon) if ok else ()))
    if ok and method != METHODS[0]:
        _preview(lat, lon)
    return {"lat": float(lat), "lon": float(lon), "ok": ok, "source": method}
