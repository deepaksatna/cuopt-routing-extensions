#!/usr/bin/env python3
"""Routing benchmark adapting NVIDIA cuOpt's own methodology.

Adapted from cuOpt's regression/benchmark_scripts/benchmark.py: report the gap to
the Best-Known Solution (BKS) on a standard Solomon instance, using cuOpt's own
metric  bks_change = |((achieved - BKS) / BKS) * 100|  (a 5% change is cuOpt's
default regression threshold). BKS values come from datasets/ref/solomon_100.txt.

Also runs the EV distance-break feature OFF vs ON on the same instance to show the
(feature-gated) EV code does not regress standard-instance solution quality.
"""
import os
import time
from cuopt.routing import utils, SolverSettings, Solve

# Best-Known Solution from datasets/ref/solomon_100.txt
BKS = {"solomon/In/r107.txt": {"cost": 1080.92, "vehicles": 11}}

def bks_change(current, bks):
    return abs(((current - bks) / bks) * 100.0) if bks else abs(current) * 100.0

def solve(inst, tl, ev=False):
    path = os.path.join(utils.RAPIDS_DATASET_ROOT_DIR, inst)
    dm = utils.create_data_model(path)
    if ev:
        fleet = dm.get_fleet_size()
        dm.add_distance_break(vehicle_ids=list(range(fleet)), max_range=200.0, duration=0)
    s = SolverSettings(); s.set_time_limit(tl)
    t0 = time.time(); sol = Solve(dm, s); dt = time.time() - t0
    return dt, sol.get_status(), sol.get_total_objective(), sol.get_vehicle_count()

inst = "solomon/In/r107.txt"; bks = BKS[inst]
print(f"Instance {inst}   BKS: cost={bks['cost']}  vehicles={bks['vehicles']}")
print("=== gap-to-BKS vs solver time budget (feature OFF) ===")
print(f"{'budget_s':>9} {'wall_s':>8} {'status':>7} {'cost':>10} {'veh':>4} {'gap_cost_%':>11} {'gap_veh_%':>10}")
for tl in (1, 3, 10, 30):
    dt, st, cost, veh = solve(inst, tl)
    print(f"{tl:>9} {dt:>8.2f} {st:>7} {cost:>10.2f} {veh:>4} "
          f"{bks_change(cost, bks['cost']):>11.2f} {bks_change(veh, bks['vehicles']):>10.2f}")
print("=== EV distance-breaks OFF vs ON (same instance, 10s budget) ===")
for ev in (False, True):
    dt, st, cost, veh = solve(inst, 10, ev=ev)
    tag = "ON " if ev else "OFF"
    print(f"EV={tag}  wall_s={dt:.2f}  status={st}  cost={cost:.2f}  veh={veh}  "
          f"gap_cost={bks_change(cost, bks['cost']):.2f}%")
print("BENCH2_DONE")
