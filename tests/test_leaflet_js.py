"""Runs the generated map pages in a real browser against a stand-in for Leaflet (which records the calls made).

This proves OUR code: the right layers are created, the data is read correctly, and hostile text is shown as text and
never run. It does not prove how Leaflet or the map tiles look. Skipped automatically if Playwright is not installed.
Run:  python tests/test_leaflet_js.py
"""
import json
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ui

EVIL = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>'
STUB = """
window.__c = {tiles: 0, rect: 0, circles: 0, markers: 0, placeMarkers: 0, layers: 0, fit: 0, setView: 0, tips: [], badges: []};
function Tip(c){ window.__c.tips.push(c instanceof Node ? c.textContent : 'HTML:' + String(c)); return this; }
function Layer(kind){ this.kind = kind; }
Layer.prototype.bindTooltip = function(c){ Tip(c); return this; };
Layer.prototype.addTo = function(){ var k = this.kind; window.__c[k] = (window.__c[k] || 0) + 1; return this; };
window.L = {
  map: function(){ return {setView: function(){ window.__c.setView++; return this; }, fitBounds: function(){ window.__c.fit++; return this; }}; },
  tileLayer: function(){ var l = new Layer('tiles'); return l; },
  rectangle: function(){ return new Layer('rect'); },
  circle: function(){ return new Layer('circles'); },
  circleMarker: function(){ return new Layer('markers'); },
  marker: function(a, o){ if (o && o.icon && o.icon.html instanceof Node) window.__c.badges.push(o.icon.html.textContent); return new Layer('placeMarkers'); },
  divIcon: function(o){ return o; },
  latLngBounds: function(){ return {pad: function(){ return this; }}; },
  control: {layers: function(){ return {addTo: function(){ window.__c.layers++; }}; }}
};
"""


def run_page(page_html):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/leaflet.js", lambda r: r.fulfill(body=STUB, content_type="application/javascript"))
        page.route("**/leaflet.css", lambda r: r.fulfill(body="", content_type="text/css"))
        page.set_content(page_html)
        page.wait_for_timeout(300)
        out = page.evaluate("() => ({c: window.__c, pwned: window.__pwned === undefined ? null : window.__pwned, "
                            "imgs: document.querySelectorAll('img').length, note: document.getElementById('note').textContent})")
        browser.close()
    return out, errors


def points(n=3):
    return [{"id": i, "lat": 13.0 + i * 0.001, "lon": 80.2, "priority": ["low", "medium", "high", "critical"][i % 4],
             "category": "Road"} for i in range(n)]


PLACES = [{"name": "Government High School", "type": "school", "lat": 13.003, "lon": 80.203},
          {"name": "Central Market", "type": "market", "lat": 13.006, "lon": 80.211}]


def test_hotspot_page_builds_every_layer():
    out, errors = run_page(ui.leaflet_hotspot_html(points(5), PLACES))
    c = out["c"]
    assert not errors, errors
    assert c["tiles"] == 1 and c["layers"] == 1 and c["rect"] == 1          # one base map drawn (the other is in the switch), the service area
    assert c["circles"] == 5 and c["markers"] == 5 and c["placeMarkers"] == 2 and c["fit"] == 1 and c["setView"] == 0
    assert sorted(c["badges"]) == ["M", "S"] and "5 open complaints" in out["note"]
    assert "#3 critical: Road" in c["tips"] and "Government High School (school)" in c["tips"]


def test_switches_remove_the_glow_and_the_places():
    c = run_page(ui.leaflet_hotspot_html(points(4), PLACES, show_density=False, show_places=False))[0]["c"]
    assert c["circles"] == 0 and c["placeMarkers"] == 0 and c["markers"] == 4


def test_an_empty_map_still_loads_and_centres_on_the_service_area():
    out, errors = run_page(ui.leaflet_hotspot_html([], PLACES))
    assert not errors and out["c"]["setView"] == 1 and out["c"]["fit"] == 0 and out["c"]["markers"] == 0


def test_hostile_text_is_shown_as_text_and_never_runs():
    evil_points = [{"id": 1, "lat": 13.0, "lon": 80.2, "priority": "high", "category": EVIL}]
    evil_places = [{"name": EVIL, "type": "school", "lat": 13.0, "lon": 80.2}]
    page_html = ui.leaflet_hotspot_html(evil_points, evil_places)
    assert page_html.count("</script>") == 2                                   # only the page's own two closing tags
    out, errors = run_page(page_html)
    assert not errors and out["pwned"] is None and out["imgs"] == 0
    assert any(EVIL in t for t in out["c"]["tips"]) and not any(t.startswith("HTML:") for t in out["c"]["tips"])


def test_ward_page_shows_totals_and_hidden_wards_only():
    page_html = ui.leaflet_ward_html({1: 12, 4: 5}, hidden=[2, 3])
    out, errors = run_page(page_html)
    c = out["c"]
    assert not errors and c["circles"] == 4 and c["placeMarkers"] == 2 and c["fit"] == 1 and c["markers"] == 0
    assert sorted(c["badges"]) == ["12", "5"] and "Ward 1: 12 problems" in c["tips"]
    assert any("hidden to protect privacy" in t for t in c["tips"])
    assert "Totals per ward only" in out["note"]


def test_the_page_data_is_valid_json():
    page_html = ui.leaflet_hotspot_html(points(2), PLACES)
    data = json.loads(re.search(r"var DATA=(\{.*?\});function tip", page_html, re.S).group(1))
    assert len(data["points"]) == 2 and len(data["places"]) == 2 and data["area"]["lat_min"] < data["area"]["lat_max"]


if __name__ == "__main__":
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as exc:
        print("SKIPPED: Playwright with a browser is not available here:", str(exc)[:80])
        sys.exit(0)
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print("PASS", name)
        except Exception as e:
            failed += 1; print("FAIL", name, type(e).__name__, e)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
