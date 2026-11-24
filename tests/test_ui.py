"""Tests for the visual building blocks. Run:  python tests/test_ui.py   (or: pytest tests)"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ui
from modules import scheduler as sch

EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)>'
ROW = {"id": 7, "text": EVIL, "priority": "high", "ward": 3, "category": EVIL, "department": EVIL, "age_days": 2}


def test_user_text_is_escaped_everywhere():
    trace = [{"step": 1, "name": EVIL, "rule": EVIL, "why": EVIL, "changes": [EVIL]}]
    for markup in (ui.complaint_card(ROW), ui.mini_card(ROW), ui.trace_html(trace, [EVIL]),
                   ui.bars([(EVIL, 3, ui.BLUE)]), ui.kpis([(EVIL, EVIL, "blue", EVIL)]), ui.hero(EVIL, EVIL),
                   ui.page_header(EVIL, EVIL)):
        assert "<script" not in markup and "<img" not in markup, markup[:120]
        assert "&lt;script" in markup


def test_timeline_escapes_crew_names():
    graph = sch.RoadGraph()
    crew = sch.Crew(EVIL, EVIL, 13.0, 80.2, 6, 480, 0)
    markup = ui.timeline({crew.id: []}, [crew], lambda m: "08:00")
    assert "<script" not in markup and "&lt;script" in markup


def test_fragments_are_single_line_so_markdown_cannot_break_them():
    for markup in (ui.css(), ui.flow(), ui.legend(), ui.complaint_card(ROW), ui.mini_card(ROW), ui.trace_html([], []),
                   ui.kpis([("a", 1, "red", "n")]), ui.bars([("a", 1, ui.BLUE)])):
        assert "\n" not in markup


def test_unknown_priority_does_not_crash():
    assert "cs-badge" in ui.badge("nonsense")


def test_bars_with_all_zero_values():
    assert "cs-bar" in ui.bars([("a", 0, ui.BLUE), ("b", 0, ui.BLUE)])
    assert ui.bars([]) == '<div class="cs-bars"></div>'


def test_late_jobs_are_marked_and_blocks_stay_inside_the_shift():
    graph = sch.RoadGraph()
    job = sch.Job(5, "Public Works", 3, 300, 13.0, 80.2, 0, 0)
    crew = sch.Crew("PW-1", "Public Works", 13.0, 80.2, 6, 480, 0)
    stops = [{"job": job, "arrive": 470.0, "finish": 530.0, "late": True}]
    markup = ui.timeline({"PW-1": stops}, [crew], lambda m: f"{8 + int(m) // 60:02d}:{int(m) % 60:02d}")
    assert "cs-stop late" in markup and "LATE" in markup
    width = float(markup.split("width:")[1].split("%")[0])
    left = float(markup.split("left:")[1].split("%")[0])
    assert left + width <= 100.0001


def test_medium_priority_uses_dark_text_for_contrast():
    assert "color:#1F2D3D" in ui.badge("medium") and "color:#fff" in ui.badge("critical")


def test_tracker_marks_done_current_and_future_stages():
    labels = ["Received", "Routed", "Resolved"]
    mid = ui.tracker(2, labels, current_label="Routed to Public Works")
    assert mid.count("cs-ts done") == 1 and mid.count("cs-ts now") == 1 and "Routed to Public Works" in mid
    assert ui.tracker(3, labels).count("cs-ts done") == 3 and "cs-ts now" not in ui.tracker(3, labels)
    assert ui.tracker(1, labels).count("cs-ts done") == 0


def test_tracker_and_code_box_escape_text():
    assert "<script" not in ui.tracker(1, [EVIL, "b"], current_label=EVIL) and "<script" not in ui.code_box(EVIL)


def test_location_card_flags_places_outside_the_area():
    assert "cs-loc bad" in ui.location_card(28.6, 77.2, "Pin on the map", False)
    assert "cs-loc bad" not in ui.location_card(13.02, 80.22, "Pin on the map", True)
    assert "<script" not in ui.location_card(13.0, 80.2, EVIL, True, EVIL)


def test_new_fragments_are_single_line():
    for markup in (ui.public_steps(), ui.tracker(2, ["a", "b", "c"]), ui.code_box("CS-ABCDEFGH"),
                   ui.location_card(13, 80, "x", True), ui.hero("a", "b", tone="blue", pill="p")):
        assert "\n" not in markup


def test_icons_exist_and_unknown_names_are_empty():
    for name in ("pin", "shield", "alert", "clock", "route", "trash", "bolt", "drop", "wave", "sparkle"):
        assert ui.icon(name).startswith("<svg") and "currentColor" in ui.icon(name)
    assert ui.icon("<script>") == "" and ui.icon("nope") == "" and "<script" not in ui.bubble(EVIL)
    assert set(ui.CATEGORY_ICON.values()) <= set(ui._ICONS)


def test_kpis_accept_old_and_new_tuples():
    old = ui.kpis([("a", 1, "blue", "")])
    new = ui.kpis([("a", 1, "red", "note", "alert")])
    assert "cs-ibub" not in old and "cs-ibub red" in new and "note" in new


def test_donut_shares_add_up_and_empty_is_grey():
    markup = ui.donut([("a", 1, "#111"), ("b", 3, "#222")], 4, "total")
    assert "#111 0.00% 25.00%" in markup and "#222 25.00% 100.00%" in markup
    assert "conic-gradient" not in ui.donut([("a", 0, "#111")], 0, "total")
    assert "<script" not in ui.donut([(EVIL, 1, "#111")], EVIL, EVIL)


def test_ai_preview_covers_both_cases_and_escapes():
    sure = ui.ai_preview("Road", 0.91, "Public Works", False)
    assert "Road" in sure and "Public Works" in sure and "91%" in sure
    assert "Not sure yet" in ui.ai_preview("", 0.2, "", True)
    assert "<script" not in ui.ai_preview(EVIL, 0.5, EVIL, False)


def test_portal_cards_and_attention_cards():
    both = ui.portals()
    assert "I am a citizen" in both and "I am city staff" in both and both.count("cs-portal ") == 2
    assert "<script" not in ui.attention_card("alert", EVIL, EVIL, EVIL)


def test_critical_badge_pulses_and_others_do_not():
    assert "cs-badge crit" in ui.badge("critical") and "crit" not in ui.badge("high")


def test_all_new_fragments_are_single_line():
    for markup in (ui.portals(), ui.portal_card("officer"), ui.donut([("a", 1, "#111")], 1, "x"), ui.ai_preview("Road", .9, "PW", False),
                   ui.attention_card("alert", 3, "t", "s"), ui.section("chart", "x"), ui.hero("a", "b", icon_name="pin"), ui.icon("pin")):
        assert "\n" not in markup


def test_hotspot_map_draws_points_places_and_escapes_everything():
    pts = [{"id": 5, "lat": 13.01, "lon": 80.21, "priority": "critical", "category": EVIL}]
    pl = [{"name": EVIL, "type": "school", "lat": 13.0, "lon": 80.2}]
    out = ui.hotspot_svg(pts, pl, [((13.0, 80.2), (13.01, 80.2))])
    assert out.startswith("<svg") and out.endswith("</svg>") and "csglow" in out and "<line" in out and "\n" not in out
    assert "<script" not in out and "<img" not in out and "&lt;script" in out
    assert 'fill="url(#csglowa)"' in ui.hotspot_svg(pts, [], [])                          # glow drawn by default
    assert 'fill="url(#csglowa)"' not in ui.hotspot_svg(pts, [], [], show_density=False)  # and really gone when switched off
    assert "<text" in ui.hotspot_svg([], pl, [], show_places=True) and ">S<" not in ui.hotspot_svg([], pl, [], show_places=False)


def test_hotspot_points_stay_inside_the_picture_even_for_odd_coordinates():
    pts = [{"id": 1, "lat": 99, "lon": -50, "priority": "low", "category": "Road"}]
    out = ui.hotspot_svg(pts, [], [])
    x = float(out.split('<circle cx="')[-1].split('"')[0])
    assert 0 <= x <= 640


def test_ward_map_shows_totals_only_and_marks_hidden_wards():
    out = ui.ward_map_svg({1: 12, 4: 5}, hidden=[2, 3])
    assert ">12<" in out and ">5<" in out and out.count("stroke-dasharray") == 2 and "hidden to protect privacy" in out
    assert "\n" not in out and "lat" not in out.lower().replace("translate", "")


def test_priority_matrix_shades_cells_that_rank_higher():
    rows = [{"problem": "Pothole", "none": {"priority": "medium", "score": 100}, "public": {"priority": "high", "score": 208}}]
    out = ui.priority_matrix(rows, [("none", "Street"), ("public", "Public place")])
    assert out.count('class="up"') == 1 and "score 208" in out and "\n" not in out
    assert "<script" not in ui.priority_matrix([dict(rows[0], problem=EVIL)], [("none", EVIL), ("public", "x")])


def test_location_card_names_nearby_places():
    near = [{"name": "Government High School", "type": "school", "distance_m": 24.0}]
    out = ui.location_card(13.0, 80.2, "Pin on the map", True, nearby=near)
    assert "Near Government High School (school, 24 m)" in out and "extra priority" in out
    assert "extra priority" not in ui.location_card(13.0, 80.2, "x", True)
    assert "extra priority" not in ui.location_card(28.0, 77.0, "x", False, nearby=near)
    assert "<script" not in ui.location_card(13.0, 80.2, "x", True, nearby=[{"name": EVIL, "type": "school", "distance_m": 1.0}])


def test_map_pages_use_a_pinned_leaflet_and_valid_data():
    import json, re
    page = ui.leaflet_hotspot_html([{"id": 1, "lat": 13.0, "lon": 80.2, "priority": "high", "category": "Road"}],
                                   [{"name": "Gov School", "type": "school", "lat": 13.0, "lon": 80.2}])
    assert "leaflet@1.9.4/dist/leaflet.js" in page and "leaflet@1.9.4/dist/leaflet.css" in page
    data = json.loads(re.search(r"var DATA=(\{.*?\});function tip", page, re.S).group(1))
    assert data["points"][0]["color"] == ui.COLORS["high"] and data["places"][0]["letter"] == "S"


def test_map_data_cannot_break_out_of_the_script_tag():
    pts = [{"id": 1, "lat": 13.0, "lon": 80.2, "priority": "high", "category": "</script><script>alert(1)</script><!--"}]
    page = ui.leaflet_hotspot_html(pts, [{"name": "</script>x", "type": "park", "lat": 13.0, "lon": 80.2}])
    assert page.count("</script>") == 2 and "<!--" not in page.split("var DATA=")[1]


def test_the_ward_map_page_carries_ward_totals_and_never_complaint_points():
    import json, re
    page = ui.leaflet_ward_html({1: 12, 4: 5}, hidden=[2])
    data = json.loads(re.search(r"var DATA=(\{.*?\});function tip", page, re.S).group(1))
    assert data["points"] == [] and data["places"] == [] and [w["count"] for w in data["wards"]] == [12, 5] and len(data["hidden"]) == 1
    assert data["wards"][0]["radius"] > data["wards"][1]["radius"]


def test_unknown_priorities_and_places_do_not_break_the_map_page():
    page = ui.leaflet_hotspot_html([{"id": 2, "lat": 13.0, "lon": 80.2, "priority": "???", "category": "Road"}],
                                   [{"name": "x", "type": "spaceport", "lat": 13.0, "lon": 80.2}])
    assert "var DATA=" in page


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
