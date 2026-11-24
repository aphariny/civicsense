"""Module 3: constraint-based crew scheduling and route optimization.

1. Road graph + A* search          -> travel distance/time between two places
2. Constraint Satisfaction Problem -> which crew takes which urgent complaint
     variables   = complaints that must be served today (priority high or critical)
     domains     = crews of the right department
     constraints = department match, crew capacity, shift length, response deadline
     solver      = backtracking + MRV (most constrained first) + forward checking
3. Best-effort filling             -> medium/low complaints added while they still fit
4. Route ordering                  -> earliest deadline first, then 2-opt local search
"""
import heapq
import math
import os
import random
from dataclasses import dataclass, replace

import networkx as nx
import yaml

from modules.geo import haversine_m

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CREWS_PATH = os.path.join(ROOT, "data", "crews.yaml")

SPEED_M_PER_MIN = 300                                # about 18 km/h in city traffic
DEADLINE_MIN = {3: 180, 2: 300, 1: 420, 0: 480}      # latest arrival (minutes after shift start) by priority level
SERVICE_MIN = {"Public Works": 60, "Sanitation Department": 40, "Electricity Board": 50,
               "Water Supply Board": 45, "Drainage & Sewerage": 60, "Health Department": 30}
NOT_SCHEDULABLE = "Control Room (manual review)"
NODE_LIMIT = 2000


# ------------------------------------------------------------------ data
@dataclass
class Job:
    id: int
    department: str
    level: int          # 0 low .. 3 critical
    score: float
    lat: float
    lon: float
    node: int = -1
    arrival: int = 0    # order in which the complaint came in (used by the baseline)
    soft: bool = False  # deadline could not be met: still scheduled, but may be late

    @property
    def service(self):
        return SERVICE_MIN.get(self.department, 45)

    @property
    def deadline(self):
        return DEADLINE_MIN[self.level]

    @property
    def order_deadline(self):
        # soft jobs are ordered as if they were due at the end of the shift, so they never push on-time jobs back
        return DEADLINE_MIN[0] if self.soft else self.deadline


@dataclass
class Crew:
    id: str
    department: str
    lat: float
    lon: float
    capacity: int
    shift_min: int
    node: int = -1


def load_crews(graph, path=CREWS_PATH):
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)["crews"]
    crews = [Crew(**c) for c in raw]
    for c in crews:
        c.node = graph.nearest(c.lat, c.lon)
    return crews


def make_job(complaint_id, lat, lon, rule_result, graph, arrival=0):
    """Turn a Module 2 result into a Job (or None if it needs manual review first)."""
    if rule_result["department"] == NOT_SCHEDULABLE:
        return None
    return Job(complaint_id, rule_result["department"], rule_result["priority_level"], rule_result["score"],
               lat, lon, graph.nearest(lat, lon), arrival)


# ------------------------------------------------------------------ road graph + A*
class RoadGraph:
    """A synthetic street grid; a few streets are blocked so shortest paths are not trivial."""

    def __init__(self, seed=7, rows=15, cols=15, lat0=12.995, lon0=80.195, step=0.0036, drop=0.15):
        rng = random.Random(seed)
        self.coords = {r * cols + c: (lat0 + r * step, lon0 + c * step) for r in range(rows) for c in range(cols)}
        self.g = nx.Graph()
        self.g.add_nodes_from(self.coords)
        edges = []
        for r in range(rows):
            for c in range(cols):
                n = r * cols + c
                if c + 1 < cols:
                    edges.append((n, n + 1))
                if r + 1 < rows:
                    edges.append((n, n + cols))
        for a, b in edges:
            self.g.add_edge(a, b, weight=haversine_m(*self.coords[a], *self.coords[b]))
        rng.shuffle(edges)
        for a, b in edges[: int(drop * len(edges))]:
            w = self.g[a][b]["weight"]
            self.g.remove_edge(a, b)
            if not nx.is_connected(self.g):          # never cut the city in two
                self.g.add_edge(a, b, weight=w)
        self._cache = {}
        self._near = {}

    def nearest(self, lat, lon):
        key = (round(lat, 5), round(lon, 5))
        if key not in self._near:
            self._near[key] = min(self.coords, key=lambda n: haversine_m(lat, lon, *self.coords[n]))
        return self._near[key]

    def _h(self, a, b):
        return haversine_m(*self.coords[a], *self.coords[b])

    def astar(self, start, goal):
        """A* search: f(n) = g(n) + h(n), h = straight-line distance (never overestimates)."""
        open_heap = [(self._h(start, goal), 0.0, start)]
        best_g, parent = {start: 0.0}, {}
        while open_heap:
            _, g, node = heapq.heappop(open_heap)
            if node == goal:
                path = [node]
                while node in parent:
                    node = parent[node]
                    path.append(node)
                return g, path[::-1]
            if g > best_g.get(node, math.inf):
                continue
            for nb, data in self.g[node].items():
                ng = g + data["weight"]
                if ng < best_g.get(nb, math.inf):
                    best_g[nb], parent[nb] = ng, node
                    heapq.heappush(open_heap, (ng + self._h(nb, goal), ng, nb))
        return math.inf, []

    def dist(self, a, b):
        if a == b:
            return 0.0
        key = (a, b) if a < b else (b, a)
        if key not in self._cache:
            self._cache[key] = self.astar(a, b)[0]
        return self._cache[key]


# ------------------------------------------------------------------ routes and constraints
def simulate(graph, crew, order):
    t, pos, dist, stops = 0.0, crew.node, 0.0, []
    for j in order:
        d = graph.dist(pos, j.node)
        arrive = t + d / SPEED_M_PER_MIN
        stops.append({"job": j, "arrive": arrive, "finish": arrive + j.service, "late": arrive > j.deadline})
        t, pos, dist = arrive + j.service, j.node, dist + d
    return stops, t, dist


def edf(jobs):
    return sorted(jobs, key=lambda j: (j.order_deadline, -j.score, j.id))


def feasible(graph, crew, jobs):
    """All constraints for one crew: capacity, shift length, every deadline met (earliest-deadline-first order)."""
    if len(jobs) > crew.capacity:
        return False
    stops, end, _ = simulate(graph, crew, edf(jobs))
    return end <= crew.shift_min and not any(s["late"] and not s["job"].soft for s in stops)


def finish_time(graph, crew, jobs):
    return simulate(graph, crew, edf(jobs))[1]


# ------------------------------------------------------------------ CSP: backtracking + MRV + forward checking
class CSP:
    def __init__(self, graph, jobs, crews):
        self.graph, self.jobs, self.crews = graph, jobs, crews
        self.assign = {c.id: [] for c in crews}
        self.nodes = 0

    def domain(self, job):
        return [c for c in self.crews if c.department == job.department
                and feasible(self.graph, c, self.assign[c.id] + [job])]

    def solve(self):
        self.nodes = 0
        return self._bt(list(self.jobs))

    def _bt(self, todo):
        if not todo:
            return True
        self.nodes += 1
        if self.nodes > NODE_LIMIT:
            return False
        domains = {j.id: self.domain(j) for j in todo}
        if any(not d for d in domains.values()):                    # forward checking: someone has no crew left
            return False
        job = min(todo, key=lambda j: (len(domains[j.id]), -j.score))   # MRV: most constrained first
        rest = [j for j in todo if j is not job]
        # least-constraining value: the crew whose day grows the least
        for crew in sorted(domains[job.id], key=lambda c: finish_time(self.graph, c, self.assign[c.id] + [job])):
            self.assign[crew.id].append(job)
            if self._bt(rest):
                return True
            self.assign[crew.id].remove(job)
        return False


def solve_urgent(graph, urgent, crews):
    """Serve as many urgent jobs as possible, most important first.

    Each job is first inserted directly. If no crew has room, the backtracking CSP re-solves
    everything accepted so far plus the new job, which may move earlier jobs to different crews.
    A job that still cannot fit (or exceeds the search budget) is deferred.
    """
    assign = {c.id: [] for c in crews}
    accepted, deferred, nodes = [], [], 0
    for job in sorted(urgent, key=lambda j: (-j.score, j.id)):
        options = [c for c in crews if c.department == job.department
                   and feasible(graph, c, assign[c.id] + [job])]
        if options:
            crew = min(options, key=lambda c: finish_time(graph, c, assign[c.id] + [job]))
            assign[crew.id].append(job)
            accepted.append(job)
            continue
        csp = CSP(graph, accepted + [job], crews)
        solved = csp.solve()
        nodes += csp.nodes
        if solved:
            assign = {cid: list(js) for cid, js in csp.assign.items()}
            accepted.append(job)
        else:
            deferred.append(job)
    return assign, deferred, nodes


# ------------------------------------------------------------------ route improvement (local search)
def improve_route(graph, crew, jobs):
    best = edf(jobs)
    best_d = simulate(graph, crew, best)[2]
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for k in range(i + 1, len(best)):
                cand = best[:i] + best[i:k + 1][::-1] + best[k + 1:]
                stops, end, d = simulate(graph, crew, cand)
                if end <= crew.shift_min and not any(s["late"] and not s["job"].soft for s in stops) \
                        and d < best_d - 1e-6:
                    best, best_d, improved = cand, d, True
    return best


# ------------------------------------------------------------------ the scheduler
def schedule(graph, jobs, crews, must_level=2):
    """Urgent jobs by CSP (most important first), then best effort for the rest."""
    urgent = [j for j in jobs if j.level >= must_level]
    others = sorted([j for j in jobs if j.level < must_level], key=lambda j: -j.score)
    no_crew = [j for j in jobs if not any(c.department == j.department for c in crews)]
    urgent = [j for j in urgent if j not in no_crew]
    others = [j for j in others if j not in no_crew]
    assign, deferred, nodes = solve_urgent(graph, urgent, crews)
    # deferred urgent jobs are still worth doing: schedule them after the on-time work, flagged as late
    others = sorted([replace(j, soft=True) for j in deferred] + others, key=lambda j: -j.score)
    unassigned = []
    for job in others:                                                   # best effort, highest score first
        options = [c for c in crews if c.department == job.department and feasible(graph, c, assign[c.id] + [job])]
        if options:
            crew = min(options, key=lambda c: finish_time(graph, c, assign[c.id] + [job]))
            assign[crew.id].append(job)
        else:
            unassigned.append(job)
    routes = {}
    for c in crews:
        order = improve_route(graph, c, assign[c.id]) if assign[c.id] else []
        routes[c.id] = simulate(graph, c, order)[0]
    return {"routes": routes, "deferred": deferred, "unassigned": unassigned + no_crew, "csp_nodes": nodes}


def schedule_fcfs(graph, jobs, crews):
    """Baseline: complaints handled in the order they arrived, each given to the nearest free crew."""
    routes = {c.id: [] for c in crews}
    pos = {c.id: c.node for c in crews}
    unassigned = []
    for job in sorted(jobs, key=lambda j: j.arrival):
        options = [c for c in crews if c.department == job.department and len(routes[c.id]) < c.capacity]
        if not options:
            unassigned.append(job)
            continue
        crew = min(options, key=lambda c: graph.dist(pos[c.id], job.node))
        if simulate(graph, crew, routes[crew.id] + [job])[1] > crew.shift_min:
            unassigned.append(job)
            continue
        routes[crew.id].append(job)
        pos[crew.id] = job.node
    return {"routes": {c.id: simulate(graph, c, routes[c.id])[0] for c in crews},
            "deferred": [], "unassigned": unassigned, "csp_nodes": 0}


# ------------------------------------------------------------------ evaluation
def metrics(graph, result, jobs, crews):
    """Compare schedules fairly: urgent jobs (high/critical) should be reached before their deadline."""
    stops = [s for r in result["routes"].values() for s in r]
    urgent_all = [j for j in jobs if j.level >= 2]
    served = {s["job"].id: s for s in stops}
    on_time = [j for j in urgent_all if j.id in served and not served[j.id]["late"]]
    crit = [served[j.id]["arrive"] for j in jobs if j.level == 3 and j.id in served]
    km = sum(simulate(graph, c, [s["job"] for s in result["routes"][c.id]])[2] for c in crews) / 1000
    return {"urgent_total": len(urgent_all), "urgent_on_time": len(on_time),
            "critical_mean_wait": sum(crit) / len(crit) if crit else 0.0,
            "served": len(stops), "total": len(jobs), "km": km}


def print_schedule(result, crews):
    for c in crews:
        stops = result["routes"][c.id]
        if not stops:
            continue
        print(f"{c.id} ({c.department}):")
        for s in stops:
            j = s["job"]
            print(f"   arrive {s['arrive']:5.0f} min  complaint #{j.id}  priority {['low','medium','high','critical'][j.level]:8s}"
                  f" deadline {j.deadline}{'  LATE' if s['late'] else ''}")
    if result["deferred"]:
        print("Deadline could not be met (scheduled late where possible):", [j.id for j in result["deferred"]])
    if result["unassigned"]:
        print("Left for the next shift:", [j.id for j in result["unassigned"]])
