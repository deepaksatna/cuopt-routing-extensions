#!/usr/bin/env python3
"""Indicative cuOpt routing benchmark (single GPU).

Measures, at a fixed solver time budget, the objective reached and end-to-end
wall time across problem sizes, and the marginal cost of the EV distance-break
feature ON vs OFF at a fixed size/seed. Intended as a starting harness; the
canonical no-regression gate uses the adopted POC methodology (see analysis/05).
"""
import time, numpy as np, cudf
from cuopt.routing import DataModel, SolverSettings, Solve

def instance(n, seed):
    rng = np.random.RandomState(seed)
    pts = rng.rand(n, 2) * 100.0
    d = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).astype("float32")
    np.fill_diagonal(d, 0.0)
    return d

def solve(n, tl, ev=False, seed=0):
    d = instance(n, seed); fleet = max(2, n // 25)
    dm = DataModel(n, fleet, n - 1)
    df = cudf.DataFrame(d); dm.add_cost_matrix(df); dm.add_transit_time_matrix(df)
    dm.set_order_locations(cudf.Series(list(range(1, n)), dtype="int32"))
    if ev:
        dm.add_distance_break(vehicle_ids=list(range(fleet)), max_range=350.0, duration=1)
    s = SolverSettings(); s.set_time_limit(tl)
    t0 = time.time(); sol = Solve(dm, s); dt = time.time() - t0
    return dt, sol.get_status(), sol.get_total_objective()

print("=== solve-time / quality vs size (feature OFF) ===")
print(f"{'stops':>6} {'fleet':>6} {'budget_s':>9} {'wall_s':>8} {'status':>7} {'objective':>11}")
for n in [50, 100, 250, 500, 1000]:
    tl = 3.0 if n <= 250 else (6.0 if n <= 500 else 10.0)
    dt, st, obj = solve(n, tl, seed=7)
    print(f"{n:>6} {max(2,n//25):>6} {tl:>9.1f} {dt:>8.2f} {st:>7} {obj:>11.1f}")

print("=== EV distance-breaks: ON vs OFF (n=250, same seed, 5s budget) ===")
for ev in (False, True):
    dt, st, obj = solve(250, 5.0, ev=ev, seed=11)
    print(f"EV={'ON ' if ev else 'OFF'}  wall_s={dt:>6.2f}  status={st}  objective={obj:.1f}")
print("BENCH_DONE")
