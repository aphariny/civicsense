"""Tests for Module 3. Run:  python tests/test_scheduler.py   (or: pytest tests)"""
import os
import random
import sys
import networkx as nx
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from modules import scheduler as sch
from modules.geo import haversine_m

G = sch.RoadGraph()


def crew(cid, dept, node, cap=6, shift=480):
    lat, lon = G.coords[node]
    return sch.Crew(cid, dept, lat, lon, cap, shift, node)


def job(jid, dept, level, node, score=None):
    lat, lon = G.coords[node]
    return sch.Job(jid, dept, level, score if score is not None else level * 100, lat, lon, node, jid)


def test_astar_matches_dijkstra():
    rng = random.Random(1)
    for _ in range(40):
        a, b = rng.sample(list(G.coords), 2)
        assert abs(G.astar(a, b)[0] - nx.dijkstra_path_length(G.g, a, b, weight="weight")) < 1e-6


def test_astar_heuristic_never_overestimates():
    rng = random.Random(2)
    for _ in range(40):
        a, b = rng.sample(list(G.coords), 2)
        assert G.dist(a, b) >= haversine_m(*G.coords[a], *G.coords[b]) - 1e-6


def test_astar_path_is_connected_walk():
    d, path = G.astar(0, 224)
    assert path[0] == 0 and path[-1] == 224 and all(G.g.has_edge(x, y) for x, y in zip(path, path[1:]))


def test_mrv_avoids_the_dead_end():
    """Job B must go to C1 (5-minute deadline, C2 is far). Job A could go to either.
    A is placed on C1 first, which strands B: the CSP must rearrange."""
    old = sch.DEADLINE_MIN[3]
    sch.DEADLINE_MIN[3] = 5
    try:
        c1, c2 = crew("C1", "Public Works", 100, cap=1), crew("C2", "Public Works", 0, cap=1)
        b, a = job(1, "Public Works", 3, 100, score=100), job(2, "Public Works", 2, 101, score=250)
        res = sch.schedule(G, [a, b], [c1, c2])
        got = {cid: [s["job"].id for s in stops] for cid, stops in res["routes"].items()}
        assert got["C1"] == [1] and got["C2"] == [2] and not res["deferred"]
        # A (higher score) is inserted on C1 first; B then has no room, so the CSP re-solves and
        # MRV takes B first (only C1 can reach it in time): 2 search nodes, no dead end
        assert res["csp_nodes"] == 2
    finally:
        sch.DEADLINE_MIN[3] = old


def test_department_constraint():
    c = [crew("PW", "Public Works", 50), crew("SAN", "Sanitation Department", 60)]
    jobs = [job(i, "Public Works" if i % 2 else "Sanitation Department", 2, 40 + i) for i in range(1, 7)]
    res = sch.schedule(G, jobs, c)
    for cid, stops in res["routes"].items():
        assert all(s["job"].department == next(x.department for x in c if x.id == cid) for s in stops)


def test_capacity_constraint():
    res = sch.schedule(G, [job(i, "Public Works", 0, 50) for i in range(1, 5)], [crew("PW", "Public Works", 50, cap=2)])
    assert len(res["routes"]["PW"]) == 2 and len(res["unassigned"]) == 2


def test_no_crew_for_department_is_left_unassigned():
    res = sch.schedule(G, [job(1, "Health Department", 3, 50)], [crew("PW", "Public Works", 50)])
    assert [j.id for j in res["unassigned"]] == [1]


def test_infeasible_urgent_jobs_defer_the_least_important():
    jobs = [job(i, "Public Works", 3, 50, score=300 + i) for i in range(1, 6)]   # 5 critical jobs, same spot
    res = sch.schedule(G, jobs, [crew("PW", "Public Works", 50)])
    assert [j.id for j in res["deferred"]] == [1]                                 # lowest score is deferred
    stops = res["routes"]["PW"]
    on_time = [s for s in stops if not s["job"].soft]
    assert len(on_time) == 4 and not any(s["late"] for s in on_time)
    late = [s for s in stops if s["job"].soft]
    assert [s["job"].id for s in late] == [1] and late[0]["late"]                  # still scheduled, flagged late


def test_scheduled_stops_meet_deadlines_and_shift_on_random_days():
    rng = random.Random(5)
    crews = sch.load_crews(G)
    depts = sorted({c.department for c in crews})
    for _ in range(10):
        jobs = [job(i, rng.choice(depts), rng.choice([0, 1, 2, 3]), rng.randrange(225)) for i in range(1, 41)]
        res = sch.schedule(G, jobs, crews)
        for c in crews:
            stops = res["routes"][c.id]
            assert len(stops) <= c.capacity
            assert not any(s["late"] and not s["job"].soft for s in stops)         # only deferred jobs may be late
            assert not stops or stops[-1]["finish"] <= c.shift_min
        seen = [s["job"].id for r in res["routes"].values() for s in r]
        assert len(seen) == len(set(seen))                                        # no job scheduled twice


def test_local_search_never_makes_a_route_longer():
    c = crew("PW", "Public Works", 0)
    jobs = [job(i, "Public Works", 0, n) for i, n in enumerate([200, 15, 190, 30, 100], 1)]
    before = sch.simulate(G, c, sch.edf(jobs))[2]
    after = sch.simulate(G, c, sch.improve_route(G, c, jobs))[2]
    assert after <= before + 1e-6


def test_manual_review_complaints_are_not_scheduled():
    rr = {"department": sch.NOT_SCHEDULABLE, "priority_level": 2, "score": 200}
    assert sch.make_job(1, 13.0, 80.2, rr, G) is None


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn(); print("PASS", name)
        except AssertionError as e:
            failed += 1; print("FAIL", name, e)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
