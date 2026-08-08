# cuopt-routing-extensions — `sparse-matrix-native` branch

## Native sparse cost matrices in the NVIDIA cuOpt solver core

> **This branch implements Feature 4 the *real* way — native sparse (K-NN / CSR) cost support inside the
> cuOpt C++ solver**, so routing scales past the dense **O(N²)** memory wall. It is a **validated
> prototype**: gated behind a `has_sparse_cost` flag, so a dense problem is byte-for-byte identical to
> upstream cuOpt. Measured on an H200, cuOpt `26.10.00`.
>
> *(The sibling `feature/sparse-matrix` branch is Option A — an application-layer payload fix. This branch
> is the deeper solver change.)*

---

## Why this matters

cuOpt's solver reads cost from a **dense N×N matrix**. At enterprise scale that memory grows
quadratically and simply won't fit:

- **10,000 stops → 0.4 GB · 50,000 → 10 GB · 100,000 → 40 GB** (won't fit on most GPUs).

Native sparse stores only each stop's **K nearest neighbours** (K-NN / CSR): **O(N·K)** memory instead of
O(N²) — the path to **100k+ stop** routing that dense cannot reach.

![GPU cost-matrix memory: dense O(N^2) crosses typical GPU memory near 50-100k stops; top-K CSR stays in MB](docs/assets/native-sparse-memory.png)

---

## What's proven (measured, not modeled)

| Result | Evidence |
|--------|----------|
| **Correct** | Full-CSR solve matches dense; dense regression green (57 py + 40 C++) with the flag off |
| **No lookup overhead** | Dense vs full-CSR reach the same objective at the same time budget |
| **Fully feasible & near-optimal** | With the missing-arc→infeasibility fix: **+1.8% to +6.2%** vs dense, up to n=1000 |
| **Memory saving grows with N** | **8× → 12× → 20×** measured (K/N shrinks 0.12→0.05); O(N·K) model → 3,030× at 100k |

![Native sparse fully feasible; memory saving grows with N: 8x at 250 (+1.9%), 12x at 500 (+3.2%), 20x at 1000 (+1.8%)](docs/assets/native-sparse-feasibility.png)

**The engineering that makes it feasible** (all measured):
1. A **navigable sentinel** for absent arcs (`BIG_COST=1e6`, not `1e30` — the latter leaves the search stuck).
2. **Depot-aware CSR** (every node keeps the depot; depot connects to all).
3. **Missing-arc → infeasibility** — route "used a missing arc" into the solver's infeasibility system
   (demonstrated via existing vehicle max-cost machinery) so the solver drives it to **zero**.

---

## How it works (one injection point)

The whole solver reads cost through a single chokepoint — `arc_value.hpp: get_distance → lookup_dist`.
Native sparse adds a gated branch there (binary-search a sorted K-NN row) plus CSR storage in
`md_utils.hpp` and a build hook in `fleet_info.cu`. Three files, ~175 lines, all gated. The exact diff is
`native-sparse/native-sparse-core.patch`.

## How to use it

- **Full guide:** [`native-sparse/PRODUCTION-USAGE.md`](native-sparse/PRODUCTION-USAGE.md) — build, deploy,
  use, tune.
- **Tested example:** [`native-sparse/production_usage_example.py`](native-sparse/production_usage_example.py)
  (runs green: feasible sparse solve, 5× memory reduction at n=500).

```bash
# build cuOpt with the patch, then:
export CUOPT_SPARSE_K=50                       # keep 50 nearest neighbours per stop
# ... build DataModel as usual, then apply the fix:
dm.set_vehicle_max_costs([max_route_cost]*fleet)   # > real route, << 1e6 sentinel
sol = Solve(dm, settings)                          # verify status==0 and objective < 1e6
```

## Current state & what's next (B5+)

This is a **validated prototype**, not yet a shipping feature. The remaining work is a **bounded list**,
not a rewrite:

1. **Direct CSR ingestion API** (`add_cost_matrix_csr`) — client sends K-NN directly; dense is *never*
   built → a true never-build-dense **100k** demonstration.
2. **`SPARSE_ARC` infeasibility dimension** — productionise the fix (no co-opting max-cost).
3. **Sparse the time matrix** too; **connectivity-preserving CSR** to lower K.

Full findings: [`native-sparse/OPTION-D-RESULTS.md`](native-sparse/OPTION-D-RESULTS.md) ·
plan/architecture map: [`native-sparse/OPTION-D-native-sparse-plan.md`](native-sparse/OPTION-D-native-sparse-plan.md) ·
raw logs: `native-sparse/logs/`.

---

*Apache-2.0. Independent companion to [NVIDIA/cuopt](https://github.com/NVIDIA/cuopt); contains no cuOpt
source (the solver changes are provided as a patch). See `NOTICE`.*
