#!/usr/bin/env python3
"""Native-sparse cuOpt — minimal production-usage example (validated end-to-end).

Enables the native sparse cost path (K-NN), applies the missing-arc->infeasibility
fix, solves, and verifies a fully feasible (no missing-arc) solution. This is the
exact pattern documented in PRODUCTION-USAGE.md, section 3.
"""
import os, numpy as np, cudf
from cuopt.routing import DataModel, SolverSettings, Solve

N, K, SENTINEL = 500, 50, 1e6

# (a) turn on native sparse
os.environ["CUOPT_SPARSE_K"] = str(K)

# build a representative instance
rng = np.random.RandomState(7)
pts = rng.rand(N, 2) * 1000.0
cost = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(-1)).astype("float32")
np.fill_diagonal(cost, 0.0)
fleet = max(2, N // 25)
cost_df = cudf.DataFrame(cost)

dm = DataModel(N, fleet, N - 1)
dm.add_cost_matrix(cost_df)
dm.add_transit_time_matrix(cost_df)
dm.set_order_locations(cudf.Series(list(range(1, N)), dtype="int32"))

# (c) the fix: make missing-arc usage infeasible (threshold > real route, << sentinel)
max_route_cost = float(cost.sum() ** 0.5 * 50)   # generous, well below 1e6
dm.set_vehicle_max_costs(cudf.Series([max_route_cost] * fleet, dtype="float32"))

settings = SolverSettings(); settings.set_time_limit(10)
sol = Solve(dm, settings)

status = sol.get_status()
obj = sol.get_total_objective()
feasible = (status == 0 and obj < SENTINEL)
csr_mem = N * K * 8
dense_mem = N * N * 4
print(f"N={N} K={K} fleet={fleet}")
print(f"status={status}  objective={obj:.1f}  feasible(no missing arcs)={feasible}")
print(f"cost-matrix memory: dense {dense_mem/1e6:.1f} MB  ->  CSR {csr_mem/1e3:.0f} KB  ({dense_mem/csr_mem:.0f}x less)")
print("PROD_EXAMPLE_OK" if feasible else "PROD_EXAMPLE_FEASIBILITY_FAIL")
