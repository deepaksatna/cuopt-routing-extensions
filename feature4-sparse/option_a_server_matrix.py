#!/usr/bin/env python3
"""Feature 4 — Option A: server-side matrix generation (payload GB -> KB).

Instead of the client transmitting a dense N×N JSON matrix (the ~36·N² payload that
hits the 2 GB API wall near ~7,700 stops), the client sends only coordinates (N×2),
and the server builds the cost/transit matrix on the GPU. This removes the *measured*
bottleneck (the payload) with no solver-core change.

Demonstrated in-process: build the matrix on the GPU from coordinates (what the server
would do) and solve — including at 10k stops, where the dense JSON payload would fail.
"""
import time, numpy as np, cupy as cp, cudf
from cuopt.routing import DataModel, SolverSettings, Solve

def gpu_matrix_from_coords(coords):
    # SERVER side: build the dense matrix on the GPU straight from coordinates.
    g = cp.asarray(coords)
    d = cp.sqrt(((g[:, None, :] - g[None, :, :]) ** 2).sum(-1)).astype(cp.float32)
    cp.fill_diagonal(d, 0)
    return cudf.DataFrame(d)   # never leaves the GPU

def solve_option_a(coords, tl):
    n = len(coords)
    t_build = time.time(); df = gpu_matrix_from_coords(coords); build_s = time.time() - t_build
    fleet = max(2, n // 50)
    dm = DataModel(n, fleet, n - 1)
    dm.add_cost_matrix(df); dm.add_transit_time_matrix(df)
    dm.set_order_locations(cudf.Series(list(range(1, n)), dtype="int32"))
    s = SolverSettings(); s.set_time_limit(tl)
    t0 = time.time(); sol = Solve(dm, s); solve_s = time.time() - t0
    return build_s, solve_s, sol.get_status(), sol.get_total_objective()

print(f"{'stops':>7} {'client_payload':>15} {'dense_payload':>14} {'reduction':>10} {'build_s':>8} {'solve_s':>8} {'status':>7}")
for n in (500, 2500, 7500, 10000):
    rng = np.random.RandomState(0)
    coords = (rng.rand(n, 2) * 1000.0).astype("float32")
    client_payload = coords.nbytes        # coordinates only
    dense_payload = 36 * n * n            # dense JSON matrices
    tl = 5.0 if n <= 2500 else 10.0
    bs, ss, st, obj = solve_option_a(coords, tl)
    print(f"{n:>7} {client_payload/1024:>12.1f}KB {dense_payload/1e9:>11.2f}GB "
          f"{dense_payload/client_payload:>9.0f}x {bs:>8.2f} {ss:>8.1f} {st:>7}")
print("\nOption A sends coordinates (KB), not the dense matrix (GB): the 2 GB payload wall is removed.")
print("The server builds the matrix on the GPU — no solver-core change, no dense JSON transfer.")
print("OPTIONA_DONE")
