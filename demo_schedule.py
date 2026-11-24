"""Print one sample day's schedule (Module 1 -> 2 -> 3)."""
import sys
import pandas as pd
from demo import process
from modules import scheduler as sch

day = int(sys.argv[1]) if len(sys.argv) > 1 else 3
df = pd.read_csv("data/complaints.csv").sample(45, random_state=day)
graph = sch.RoadGraph()
crews = sch.load_crews(graph)
jobs, review = [], 0
for k, r in enumerate(df.itertuples()):
    res = process(r.text)[1]
    job = sch.make_job(int(r.complaint_id), r.lat, r.lon, res, graph, arrival=k)
    if job:
        jobs.append(job)
    else:
        review += 1
print(f"{len(df)} complaints: {len(jobs)} schedulable, {review} sent to manual review\n")
result = sch.schedule(graph, jobs, crews)
sch.print_schedule(result, crews)
m = sch.metrics(graph, result, jobs, crews)
print(f"\nUrgent on time: {m['urgent_on_time']}/{m['urgent_total']}   travel: {m['km']:.0f} km   served: {m['served']}/{m['total']}")
