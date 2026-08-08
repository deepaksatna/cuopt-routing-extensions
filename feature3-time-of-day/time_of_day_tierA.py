#!/usr/bin/env python3
"""
Phase 1 - Time-of-Day Routing, Tier A (application layer; NO cuOpt source change).

Study reference: analysis/02 Feature 3 "Tier A", analysis/04 Phase 1.

Idea
----
Travel time depends on WHEN you depart (rush hour vs off-peak). cuOpt solves a
single static matrix per job. The Tier-A pattern delivers time-of-day routing
WITHOUT modifying the solver: the application

  1. pre-computes one travel-time / cost matrix per departure window
     (in production these come from HERE / TomTom / Google historical traffic),
  2. runs one cuOpt job per departure window with that window's matrix,
  3. compares / stitches the results and picks the departure that best meets the
     business objective.

This script demonstrates the pattern end-to-end against the locally built cuOpt
and prints, per departure window: solver status, objective (total travel cost),
vehicles used, and solve time. It also shows a simple "warm-start-style" reuse
note and an honest boundary of where native (Tier B) would be required.

Run inside the cuOpt conda env:
    RAPIDS_DATASET_ROOT_DIR unused here (self-contained synthetic instance)
    python time_of_day_tierA.py
"""

import time
import numpy as np
import cudf
from cuopt.routing import DataModel, SolverSettings, Solve


# --------------------------------------------------------------------------- #
# 1. A small city: depot (0) + N delivery stops on a grid.                     #
# --------------------------------------------------------------------------- #
def make_instance(seed_points):
    coords = np.array(seed_points, dtype=float)
    n = len(coords)
    # free-flow travel time (minutes) ~ Euclidean distance * base speed factor
    diff = coords[:, None, :] - coords[None, :, :]
    base = np.sqrt((diff ** 2).sum(-1))
    np.fill_diagonal(base, 0.0)
    return coords, base.astype("float32"), n


# --------------------------------------------------------------------------- #
# 2. Departure windows -> per-arc congestion multipliers.                      #
#    In production these are real time-bucketed matrices; here we scale the    #
#    free-flow matrix by a window-specific congestion factor. (A refinement    #
#    can make the multiplier per-arc, e.g. worse on arterials at rush hour.)   #
# --------------------------------------------------------------------------- #
DEPARTURE_WINDOWS = {
    "06:00 off-peak":    1.00,
    "08:00 morning-rush": 1.85,
    "13:00 midday":      1.20,
    "17:30 evening-rush": 2.10,
    "21:00 night":       0.95,
}


def window_matrix(base, congestion):
    """Return a time-bucketed matrix for one departure window."""
    m = base * float(congestion)
    np.fill_diagonal(m, 0.0)
    return m.astype("float32")


# --------------------------------------------------------------------------- #
# 3. Solve one cuOpt job for one departure window's matrix.                    #
# --------------------------------------------------------------------------- #
def solve_window(matrix, n_locations, fleet_size, order_locations, time_limit=3):
    dm = DataModel(n_locations, fleet_size, len(order_locations))
    df = cudf.DataFrame(matrix)
    dm.add_cost_matrix(df)
    dm.add_transit_time_matrix(df)  # same matrix drives both cost and time here
    dm.set_order_locations(cudf.Series(order_locations, dtype="int32"))
    settings = SolverSettings()
    settings.set_time_limit(time_limit)
    t0 = time.time()
    sol = Solve(dm, settings)
    dt = time.time() - t0
    return sol, dt


def main():
    # depot + 8 stops
    pts = [
        (0, 0),      # 0 depot
        (2, 3), (5, 1), (6, 4), (1, 6),
        (4, 7), (8, 2), (3, 2), (7, 6),
    ]
    coords, base, n = make_instance(pts)
    fleet = 3
    order_locations = list(range(1, n))  # every non-depot stop is an order

    print(f"Instance: {n} locations ({len(order_locations)} orders), fleet {fleet}")
    print("Solving one cuOpt job per departure window (Tier A, app layer):\n")
    header = f"{'departure window':22} {'congestion':>10} {'status':>7} {'objective':>11} {'veh':>4} {'solve_s':>8}"
    print(header)
    print("-" * len(header))

    results = {}
    for name, cong in DEPARTURE_WINDOWS.items():
        m = window_matrix(base, cong)
        sol, dt = solve_window(m, n, fleet, order_locations)
        obj = sol.get_total_objective()
        try:
            veh = sol.get_vehicle_count()
        except Exception:
            veh = "?"
        results[name] = (sol.get_status(), obj, veh, dt)
        print(f"{name:22} {cong:>10.2f} {sol.get_status():>7} {obj:>11.2f} {str(veh):>4} {dt:>8.3f}")

    # --------------------------------------------------------------------- #
    # Business read-out: same stops, different departure -> different cost. #
    # --------------------------------------------------------------------- #
    ok = {k: v for k, v in results.items() if v[0] == 0}
    if ok:
        best = min(ok, key=lambda k: ok[k][1])
        worst = max(ok, key=lambda k: ok[k][1])
        spread = ok[worst][1] / ok[best][1] if ok[best][1] else float("inf")
        print("\nSummary")
        print(f"  cheapest departure : {best}  (objective {ok[best][1]:.2f})")
        print(f"  costliest departure: {worst}  (objective {ok[worst][1]:.2f})")
        print(f"  rush-hour penalty  : {spread:.2f}x  <- this is the time-of-day signal Tier A captures")

    print(
        "\nBoundary note (Tier A vs Tier B):\n"
        "  Tier A (this script) assumes the WHOLE route uses one window's matrix -- correct when\n"
        "  each vehicle's tour fits within a single congestion window. When a single long tour\n"
        "  spans multiple windows (arc cost must change WITHIN the tour by cumulative arrival\n"
        "  time), that needs native time-dependent matrices in the solver (Tier B). Tier A ships\n"
        "  today with zero solver risk; Tier B is the funded follow-on."
    )


if __name__ == "__main__":
    main()
