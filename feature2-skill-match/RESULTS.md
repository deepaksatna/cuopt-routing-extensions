# Feature 2 (constraint honoring) — Prize-Based Validation

**Context.** NVIDIA (cuOpt Eng, via the code owner) advised that the intended way to avoid
*hard-constraint-violated-in-partial-solution* behavior is to **set prizes on visits** (e.g. all
prizes = 1). The solver then serves as many visits as possible **without violating constraints**;
if resources are insufficient it returns a **partial** solution (some visits unassigned) instead of a
violating one — "without having to do coding in the cuOpt source."

We validated this empirically on the built cuOpt (`main` 26.10.00, 2×A10). Reproduce with the two
scripts in this folder (`f2_prizes.py`, `f2_skill.py`).

## Setup

- 4 locations (depot + 3 order locations), 2 vehicles, 3 orders.
- **Capacity** dimension makes it impossible to serve all orders (each vehicle holds 1 unit).
- **Skill** constraint: `add_order_vehicle_match(0, [0])` — order 0 may only be served by vehicle 0.
- Solve twice: **without** prizes and **with** `set_order_prizes([1,1,1])`.

## Results

| Scenario | Without prizes | With `prizes=1` |
|----------|----------------|-----------------|
| Capacity-forced (`f2_prizes.py`) | `status=1` (infeasible); vehicle 1 carries **2 units on capacity 1** → **capacity violated**; all 3 orders "served" | `status=0` (SUCCESS); **clean partial** — 2/3 served, capacity + skill respected, 1 order dropped |
| Skill-locked & unservable (`f2_skill.py`): order 0 demand 2, only vehicle 0 allowed, vehicle 0 cap 1 | `status=1` (infeasible); solver over-packs **vehicle 0** to force order 0 in → **capacity violated** | `status=0` (SUCCESS); **clean partial** — drops the unservable order 0, 2/3 served, all constraints respected |

## Findings

1. **The guidance holds.** With `prizes=1`, every solve returned `status=0` and a **partial solution
   that violated no constraint**; without prizes, the solver returned `status=1` and satisfied the
   full-assignment demand by **violating a constraint** (capacity, in our scenarios).
2. **The MISMATCH/skill constraint was never violated** in any variant — the solver honored the
   `order_vehicle_match` and sacrificed capacity instead. So on this cuOpt build, skill-match already
   behaves as a hard constraint; the *partial-solution violation* risk the study flagged for Feature 2
   is addressed by the prize pattern (drop rather than violate).
3. **`status=1` is the tell.** A non-zero status signals the solver could not honor all constraints
   with a full assignment. Setting prizes lets it return a **feasible partial** (`status=0`) instead.

## Recommendation for the study (Feature 2)

- **Adopt the prize pattern** (`set_order_prizes(all=1)`) as the supported way to guarantee no
  constraint violations; unservable visits come back as **unassigned** (a partial solution) that the
  application layer can surface/handle. **No cuOpt source change required** — matching the code
  owner's guidance and the study's upstream-first principle.
- This simplifies Feature 2 from "reproduce + fix a bug" to "adopt a documented usage pattern," and
  it also covers the general case (capacity, time windows, skill) — not just skill-match.

*Scripts: `f2_prizes.py` (capacity-forced), `f2_skill.py` (skill-locked unservable). Run inside the
cuOpt conda env; no dataset needed.*
