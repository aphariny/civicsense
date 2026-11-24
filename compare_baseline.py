"""Simulate many days: CivicSense scheduler vs a first-come-first-served baseline.

Each day samples complaints from the dataset, runs Module 1 (classifier) and Module 2 (rules),
then schedules the same complaints with both methods on the same crews.
"""
import random
import sys
import pandas as pd
from demo import process
from modules import scheduler as sch

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30
JOBS_PER_DAY = int(sys.argv[2]) if len(sys.argv) > 2 else 45

df = pd.read_csv("data/complaints.csv")
graph = sch.RoadGraph()
crews = sch.load_crews(graph)

print("Running Module 1 + Module 2 on all complaints (once)...")
cache = {int(r.complaint_id): process(r.text)[1] for r in df.itertuples()}

totals = {"csp": [], "fcfs": []}
for day in range(DAYS):
    rng = random.Random(day)
    rows = df.sample(JOBS_PER_DAY, random_state=day)
    jobs = [j for k, r in enumerate(rows.itertuples())
            if (j := sch.make_job(int(r.complaint_id), r.lat, r.lon, cache[int(r.complaint_id)], graph, arrival=k))]
    totals["csp"].append(sch.metrics(graph, sch.schedule(graph, jobs, crews), jobs, crews))
    totals["fcfs"].append(sch.metrics(graph, sch.schedule_fcfs(graph, jobs, crews), jobs, crews))

def avg(name, key):
    return sum(m[key] for m in totals[name]) / DAYS

print(f"\n{DAYS} simulated days, about {JOBS_PER_DAY} complaints/day, {len(crews)} crews\n")
print(f"{'':44s}{'First-come':>12s}{'CivicSense':>12s}")
u_f, u_c = avg("fcfs", "urgent_on_time"), avg("csp", "urgent_on_time")
tot = avg("csp", "urgent_total")
print(f"{'Urgent (high/critical) reached on time':44s}{u_f:>9.1f}/{tot:.0f}{u_c:>9.1f}/{tot:.0f}")
print(f"{'  as a percentage':44s}{100*u_f/tot:>11.0f}%{100*u_c/tot:>11.0f}%")
print(f"{'Critical complaints: mean wait (minutes)':44s}{avg('fcfs','critical_mean_wait'):>12.0f}{avg('csp','critical_mean_wait'):>12.0f}")
print(f"{'Complaints served per day':44s}{avg('fcfs','served'):>12.1f}{avg('csp','served'):>12.1f}")
print(f"{'Total crew travel per day (km)':44s}{avg('fcfs','km'):>12.0f}{avg('csp','km'):>12.0f}")
