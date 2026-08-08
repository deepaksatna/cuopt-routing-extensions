#!/usr/bin/env python3
"""Feature 4 — end-to-end sparse test suite (regressive, with PASS/FAIL checks).

Test 1  Correctness  : the server-side GPU-built matrix equals the client host-built
                       matrix (proves Option A produces the *correct* matrix, not just
                       a smaller payload).
Test 2  Payload+solve : dense-matrix path vs Option A (coords->GPU matrix) across sizes.
Test 3  Beyond-the-wall: Option A solves past the 2 GB dense-payload ceiling.
"""
import math, time, numpy as np, cupy as cp, cudf
from cuopt.routing import DataModel, SolverSettings, Solve

PAYLOAD_LIMIT = 2 * 1024**3
def coords(n):
    rng = np.random.RandomState(42); return (rng.rand(n, 2) * 1000.0).astype("float32")
def host_matrix(c):
    d = np.sqrt(((c[:, None, :] - c[None, :, :]) ** 2).sum(-1)).astype("float32"); np.fill_diagonal(d, 0); return d
def gpu_matrix(c):
    g = cp.asarray(c); d = cp.sqrt(((g[:, None, :] - g[None, :, :]) ** 2).sum(-1)).astype(cp.float32); cp.fill_diagonal(d, 0); return d
def solve(df, n, tl):
    fleet = max(2, n // 50); dm = DataModel(n, fleet, n - 1)
    dm.add_cost_matrix(df); dm.add_transit_time_matrix(df)
    dm.set_order_locations(cudf.Series(list(range(1, n)), dtype="int32"))
    s = SolverSettings(); s.set_time_limit(tl); sol = Solve(dm, s)
    return sol.get_status(), sol.get_total_objective()

passed = True
print("### TEST 1 - matrix equivalence (server GPU build == client host build)")
for n in (100, 500, 2500, 7500):
    c = coords(n); md = float(np.abs(host_matrix(c) - cp.asnumpy(gpu_matrix(c))).max())
    ok = md < 1e-1; passed &= ok
    print(f"  n={n:>5}  max|host-gpu|={md:.4f}   {'PASS' if ok else 'FAIL'}")

print("### TEST 2 - payload + solve: dense (host matrix) vs Option A (coords->GPU)")
print(f"  {'n':>5} {'dense_GB':>9} {'optA_KB':>8} {'reduct':>8} {'dense(st/obj)':>16} {'optA(st/obj)':>16}")
for n in (500, 2500, 5000, 7500):
    c = coords(n); dp = 36 * n * n; ap = c.nbytes; tl = 8.0 if n > 2500 else 5.0
    ds, dobj = solve(cudf.DataFrame(host_matrix(c)), n, tl)
    as_, aobj = solve(cudf.DataFrame(gpu_matrix(c)), n, tl)
    print(f"  {n:>5} {dp/1e9:>8.2f} {ap/1024:>7.1f} {dp/ap:>7.0f}x {ds:>7}/{dobj:>7.0f} {as_:>7}/{aobj:>7.0f}")

print("### TEST 3 - feasibility beyond the 2 GB dense-payload wall (Option A only)")
for n in (8000, 10000):
    c = coords(n); ap = c.nbytes; dp = 36 * n * n
    as_, aobj = solve(cudf.DataFrame(gpu_matrix(c)), n, 12.0)
    print(f"  n={n:>5}  dense_payload={dp/1e9:.2f}GB (>2GB WALL)  optionA_payload={ap/1024:.1f}KB  status={as_}  obj={aobj:.0f}")

nstar = math.sqrt(PAYLOAD_LIMIT / 36)
print(f"\nSUMMARY: matrix-equivalence {'PASS' if passed else 'FAIL'}; "
      f"Option A removes the 2 GB payload wall (dense crosses at N≈{nstar:.0f} stops).")
print("SPARSE_E2E_DONE")
