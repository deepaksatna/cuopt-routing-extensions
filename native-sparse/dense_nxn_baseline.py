#!/usr/bin/env python3
"""Feature 4 — dense N×N baseline.

Quantifies why native sparse support matters. For increasing stop counts, reports:
  - GPU matrix memory (2 · N² · 4 bytes: cost + transit, float32)
  - the JSON API payload law measured in the POC (~36 · N² bytes for 2 dense matrices)
  - in-process dense solve time / status (Python API, no server)

Key expected finding (matches the POC): GPU memory stays small, but the JSON *payload*
crosses the ~2 GB API limit near ~7,500 stops — so the wall is the payload, not the GPU.
That is exactly what server-side matrix generation (Option A) removes.
"""
import time, numpy as np, cudf
from cuopt.routing import DataModel, SolverSettings, Solve

PAYLOAD_LIMIT = 2 * 1024**3  # 2 GB

def run(n, tl):
    rng = np.random.RandomState(0)
    pts = rng.rand(n, 2) * 1000.0
    d = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).astype("float32")
    np.fill_diagonal(d, 0.0)
    gpu_mem = 2 * d.nbytes                 # cost + transit matrices in GPU
    json_payload = 36 * n * n              # measured POC law (2 dense matrices, JSON)
    fleet = max(2, n // 50)
    dm = DataModel(n, fleet, n - 1)
    df = cudf.DataFrame(d)
    dm.add_cost_matrix(df); dm.add_transit_time_matrix(df)
    dm.set_order_locations(cudf.Series(list(range(1, n)), dtype="int32"))
    s = SolverSettings(); s.set_time_limit(tl)
    t0 = time.time(); sol = Solve(dm, s); dt = time.time() - t0
    return gpu_mem, json_payload, dt, sol.get_status()

print(f"{'stops':>7} {'GPU_matrix':>11} {'JSON_payload':>13} {'payload>2GB':>12} {'solve_s':>8} {'status':>7}")
for n in (500, 1000, 2500, 5000, 7500, 10000):
    tl = 5.0 if n <= 2500 else 10.0
    gm, jp, dt, st = run(n, tl)
    wall = "FAIL" if jp > PAYLOAD_LIMIT else "ok"
    print(f"{n:>7} {gm/1e6:>9.0f}MB {jp/1e9:>11.2f}GB {wall:>12} {dt:>8.1f} {st:>7}")
# where does the payload law cross 2 GB?
import math
n_star = math.sqrt(PAYLOAD_LIMIT / 36)
print(f"\nJSON payload crosses 2 GB at N ≈ {n_star:.0f} stops (36·N² = 2 GB).")
print("GPU matrix memory at 10k stops is < 1 GB — the wall is the PAYLOAD, not the GPU.")
print("DENSE_DONE")
