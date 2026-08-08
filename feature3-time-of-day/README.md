# Phase 1 — Time-of-Day Routing, Tier A (application layer)

**Feature 3, Tier A** from the study: rush-hour-aware routing **without any cuOpt source change**.
The application pre-computes one travel-time/cost matrix per departure window and runs one cuOpt job
per window; the solver core is untouched, so there is **zero performance risk**.

## What / Why / How

- **What:** Demonstrate that the same set of stops routed at different departure times yields different
  (traffic-aware) optimal routes and costs.
- **Why:** It is the study's "fastest customer value" item — delivers the rush-hour outcome today with
  no fork and no solver risk, and is the fallback if native time-dependent matrices (Tier B) are
  deprioritised.
- **How:** `time_of_day_tierA.py` builds a free-flow matrix, scales it by a per-window congestion
  factor (in production these are real HERE/TomTom/Google time-bucketed matrices), and solves one
  cuOpt job per departure window.

## Results (measured, H200, cuOpt 26.10.00)

Instance: 9 locations (8 orders), fleet 3.

| Departure window | Congestion | Status | Objective | Vehicles | Solve (s) |
|------------------|-----------:|:------:|----------:|:--------:|----------:|
| 06:00 off-peak     | 1.00 | 0 | 27.16 | 1 | 0.239 |
| 08:00 morning-rush | 1.85 | 0 | 50.25 | 1 | 0.081 |
| 13:00 midday       | 1.20 | 0 | 32.59 | 1 | 0.079 |
| 17:30 evening-rush | 2.10 | 0 | 57.04 | 1 | 0.081 |
| 21:00 night        | 0.95 | 0 | 25.80 | 1 | 0.078 |

**Rush-hour penalty: 2.21×** (evening-rush 57.04 vs. night 25.80) — the time-of-day signal Tier A
captures. All windows solve to `status=0` in < 0.25 s.

## Boundary — when Tier B (native) is needed

Tier A assumes each vehicle's whole tour uses **one** window's matrix — correct when a tour fits inside
a single congestion window. When a **single long tour spans multiple windows** (arc cost must change
*within* the tour based on cumulative arrival time), that requires **native time-dependent matrices in
the solver** (Tier B): extend the existing multi-matrix selector from `[vehicle_type]` to
`[vehicle_type][time_bucket]`, gated behind a `has_time_dependency` flag. Tier B is the funded
follow-on (analysis/02 Feature 3 Tier B; analysis/04 Phase 4). Tier A ships now with zero solver risk.

## Run

```bash
conda activate <cuopt env>
python time_of_day_tierA.py
```
