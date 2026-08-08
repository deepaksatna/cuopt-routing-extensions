# EV Distance-Breaks Adoption — File-by-File Change Log

Every file changed vs. upstream `main` (base `f3ebc673`), what changed, and why.
Local branch `feature/ev-distance-breaks-pr1196`, commit `914530e5` — **30 files, +1881 / −106**.

**Provenance key:**
- **[PR]** = content from NVIDIA/cuopt **PR #1196** ("routing: add distance breaks"), adopted as-is.
- **[FIX]** = our **integration fix** required because `main` moved 1000+ commits past the PR branch point.
- **[MERGE]** = our **conflict resolution** during the merge.

---

## A. C++ solver core — the distance-window dimension  *(all [PR], feature-gated)*

The EV feature adds a **distance-window** capability to the existing `BREAK`/`DIST` machinery. Every
addition is gated behind `dim_info.has_distance_window` so a problem without EV constraints executes
the identical instructions/allocations as upstream (zero cost when unused).

| File | Δ | What & why |
|------|---|-----------|
| `cpp/src/routing/dimensions.cuh` | +7/−? | Registers the distance-window on the break/distance dimension info (the `has_distance_window` gate). Core enum/info touch is deliberately tiny (7 lines) — reuses the DIST dimension. |
| `cpp/src/routing/route/distance_route.cuh` | +127 | The heart of the feature: per-node window/excess bookkeeping (`distance_window_forward`, `window_start`, `excess_forward`), all inside `if (dim_info.has_distance_window)`. Both the compute and the buffer `resize` are gated → no extra memory/compute when off. |
| `cpp/src/routing/node/distance_node.cuh` | +58 | Adds the per-node fields the window logic reads/writes and their combine/propagation rules. |
| `cpp/src/routing/problem/problem.cu` | +64 | Ingests the distance-break constraints into the problem representation. |
| `cpp/src/routing/problem/special_nodes.cuh` | +26 | Represents break nodes / candidate break locations as special nodes. |
| `cpp/src/routing/data_model_view.cu` | +96 | Implements `add_distance_break(...)` storage + accessors on the data-model view. |
| `cpp/include/cuopt/routing/data_model_view.hpp` | +32 | Public C++ API declaration for `add_distance_break` (line ~185) + getters. |
| `cpp/include/cuopt/routing/routing_structures.hpp` | +34 | Structs/enums carrying the distance-break parameters through the solver. |
| `cpp/src/routing/local_search/breaks_insertion.cu` | +7 | Local-search move that inserts break nodes now respects the distance window. |
| `cpp/src/routing/ges/squeeze.cuh` | +9 | GES "squeeze" repair path made aware of distance-window feasibility. |
| `cpp/src/routing/solution/solution.cuh` | +7 | Solution carries/report break placements. |
| `cpp/src/routing/util_kernels/set_nodes_data.cuh` | +13 | Node-data setup kernel initializes the new window fields. |

## B. C++ tests

| File | Δ | Prov. | What & why |
|------|---|-------|-----------|
| `cpp/tests/routing/unit_tests/distance_breaks.cu` | +426 (new) | [PR] | Dedicated gtest suite: `default_case`, `with_break_locations`, `multi_cycle`, `break_distance_window_enforced`, `mixed_fleet`. **All 5 PASS.** |
| `cpp/tests/routing/routing_test.cuh` | +81 | [PR] | Shared test fixture support (`regression_routing_test_distance_breaks_t`) used by the L1 regression. |
| `cpp/tests/routing/CMakeLists.txt` | +1 | [PR] | Registers `distance_breaks.cu` in the unit-test build. |
| `cpp/tests/routing/level1/l1_routing_test.cu` | +9 | **[MERGE]** | **The one merge conflict.** Kept the PR's `l1_distance_breaks` `INSTANTIATE_TEST_SUITE_P`; **dropped** the PR's re-added `CUOPT_TEST_PROGRAM_MAIN()` because `main` relocated the test-main globally (re-adding duplicates a symbol). |

## C. Python API  *(mostly [PR]; one [FIX])*

| File | Δ | Prov. | What & why |
|------|---|-------|-----------|
| `python/cuopt/cuopt/routing/vehicle_routing.py` | +107 | [PR] | Public `DataModel.add_distance_break(vehicle_ids, max_range, duration, locations, min_range, n_cycles)`. Expands `n_cycles` into per-cycle windows `[k·max_range+min_range, (k+1)·max_range]` and calls `super().add_distance_break(...)` per cycle. |
| `python/cuopt/cuopt/routing/vehicle_routing_wrapper.pyx` | +49 | [PR] | Cython binding calling the C++ `data_model_view.add_distance_break`. **Requires a clean Cython rebuild after merge** (see FIX note below). |
| `python/cuopt/cuopt/routing/vehicle_routing.pxd` | +8 | [PR] | Cython declaration of the C++ `add_distance_break` signature. |
| `python/cuopt/cuopt/routing/_deferred.py` | **+1** | **[FIX]** | **Our integration fix.** `main` refactored `DataModel` into a deferred *record-and-replay* model where mutating setters are enumerated in a `_SETTERS` tuple and replayed at build time. PR #1196 predates this, so `add_distance_break` was **unregistered** → `super().add_distance_break()` raised `AttributeError` from the deferred base. Fix: add `"add_distance_break"` to `_SETTERS`. |

## D. Server (self-hosted) — all [PR]

| File | Δ | What & why |
|------|---|-----------|
| `python/cuopt_server/cuopt_server/utils/routing/data_definition.py` | +79 | Pydantic schema for distance-break payload fields. |
| `python/cuopt_server/cuopt_server/utils/routing/validation_fleet_data.py` | +55 | Request validation for the distance-break inputs. |
| `python/cuopt_server/cuopt_server/utils/routing/optimization_data_model.py` | +53 | Wires the payload into the solver data model. |
| `python/cuopt_server/cuopt_server/utils/routing/solver.py` | +32 | Solver invocation passes distance-break config through. |
| `python/cuopt_server/cuopt_server/utils/solver.py` | +1 | Hook for the new field. |
| `python/cuopt_server/cuopt_server/tests/utils/utils.py` | +4 | Server test helper support. |

## E. Docs / examples — all [PR]

| File | Δ | What & why |
|------|---|-----------|
| `python/cuopt/cuopt/tests/routing/test_distance_breaks.py` | +487 (new) | The Python test suite (30 tests). **29 pass / 1 fails** — see the open item below. |
| `docs/cuopt/source/cuopt-python/routing/examples/distance_break_example.py` | +61 (new) | Worked example of `add_distance_break`. |
| `docs/cuopt/source/cuopt-python/routing/routing-examples.rst` | +35 | Docs index entry for the example. |
| `docs/cuopt/source/routing-features.rst` | +18 | Feature documentation. |

---

## Non-source build step (not a committed change) — **[FIX]**

**Clean Cython rebuild after merge.** After merging, the installed `vehicle_routing_wrapper*.so`
was recompiled from a **stale cached** Cython-generated `.cpp` under `python/cuopt/build/`, so the
compiled base class lacked `add_distance_break`. Required:
`rm -rf python/cuopt/build python/libcuopt/build` then rebuild the Python package. Suggested upstream
improvement: invalidate the Cython cache when `.pyx`/`.pxd` change.

---

## Open correctness item (multi-cycle) — **must resolve before production**

`test_solve_full_feature_api` fails **deterministically**. Diagnostic dump of the exact scenario
(`n_cycles=2`, windows `[10,20]` & `[30,40]`, 2 vehicles, 2 orders, 5-loc unit grid):

```
vehicle 1: Depot(0) -> Break@3 (cum 10.0) -> Break@3 (cum 10.0) -> Delivery@1 -> Depot   status=0
vehicle 0: Depot(0) -> Break@3 (cum 10.0) -> Break@3 (cum 10.0) -> Delivery@2 -> Depot   status=0
```

**Both cycle breaks are placed back-to-back at the same location (cumulative 10.0 and +0.0), so
cycle-0's window `[10,20]` is satisfied twice and cycle-1's `[30,40]` is never entered — yet the
solver returns `status=0` (feasible).** The route's total distance is only 30, so `[30,40]` is
effectively unreachable; the solver best-efforts rather than enforcing or declaring infeasible.

**Why this matters for production:** it means a **mandated recharge window can be silently skipped**
— an EV could be routed without the second charge. The dedicated tests pass (**C++ `multi_cycle` +
`break_distance_window_enforced` PASS; Python single-cycle/window tests PASS**), so the core works on
adequately-sized problems; the gap is specifically **multi-cycle enforcement when a cycle window is
unsatisfiable**. This is a genuine upstream correctness question for the PR author:

> Are distance-break windows **hard-guaranteed** (then this scenario should be **infeasible**), or
> **best-effort** (then multi-cycle EV routing is not production-safe as-is)?

We deliberately did **not** weaken the test to force a green run — that would hide the risk.
