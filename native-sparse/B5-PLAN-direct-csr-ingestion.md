# B5 — Direct CSR ingestion API (production plan)

**Goal:** let the client hand cuOpt a **sparse K-NN cost graph directly** (CSR: offsets/indices/values), so
the server **never materialises the dense N×N matrix**. This converts the *already-proven* solver-memory
saving into the full **end-to-end network payload saving (~99.97%, 3,000× at 10k)** and makes the exact
original Phase-4 benchmark **PASS**.

**Status going in:** the hard part is done. The solver already reads cost from CSR (`arc_value.hpp`,
gated `has_sparse_cost`), the feasibility fix works, and dense is byte-identical. B5 is **bounded plumbing**
to feed a client-supplied CSR through the stack instead of building it from a dense matrix.

---

## What "done" looks like (acceptance)

1. `DataModel.add_cost_matrix_csr(offsets, indices, values)` exists in Python, mirroring
   `add_cost_matrix`, and a solve using it is feasible + matches the `CUOPT_SPARSE_K` build's quality.
2. The **self-hosted server** accepts a sparse cost matrix in the request payload (new field), never
   allocates dense, and the 10k-stop K-NN payload (0.76 MB) **submits and solves** (Phase-4 turns green).
3. Dense path unchanged — all existing tests still pass (57 py + 40 C++).
4. `CUOPT_SPARSE_K` env hook is removed (or kept only as a dev shim); K comes from the client graph.

---

## The chain to touch (client → solver), and the specific sites

Reuse the exact structures the native-sparse build already added; B5 just fills them from the request
instead of from `build_csr(dense)`.

### 1. C++ data model — accept CSR
- **`cpp/include/cuopt/routing/data_model_view.hpp`** — add `add_cost_matrix_csr(offsets, indices,
  values, n_locations, vehicle_type=0)` alongside `add_cost_matrix`. Store the three device spans + a
  `has_sparse_cost` marker per vehicle type.
- **`cpp/src/routing/data_model_view.cpp`** — implement the setter; validate `offsets.size()==n+1`,
  `indices.size()==values.size()==offsets[n]`, indices sorted per row (or sort once here).

### 2. `fleet_info.cu` — populate `d_mdarray_t` from the CSR instead of building it
- **`cpp/src/routing/fleet_info.cu` `populate_matrices`** — where it currently calls
  `fill_mdarray_from_data_model` (dense) and then optionally `build_csr(K)`, branch: **if the data model
  carries a CSR, copy those spans straight into `matrices_.csr_offsets/indices/values`** and set
  `has_sparse_cost=true`. Skip the dense allocation entirely. (Remove the `getenv("CUOPT_SPARSE_K")` shim.)
- Keep the existing `d_mdarray_t` device members + `view()` wiring — **no change** to `arc_value.hpp`
  (the read path already consumes `has_sparse_cost` + the CSR spans).

### 3. Transit-time matrix
- Same treatment for `add_transit_time_matrix_csr`, **or** support distance-only models where time == cost.
  Minimum viable B5: sparse **cost**, dense-or-absent time. Full: sparse time too (mirror step 1–2).

### 4. Cython / Python binding
- **`python/cuopt/cuopt/routing/data_model_view.pyx`** — expose `add_cost_matrix_csr(offsets, indices,
  values)` taking cudf Series / device arrays; hand the device pointers to the C++ setter. Mirror the
  existing `add_cost_matrix` binding exactly (dtype checks: offsets/indices int32, values float32).
- Add to `_SETTERS` / serialization handlers (the same places EV's `add_distance_break` needed:
  `_deferred.py` setter registry + a `_serialize` handler) so round-trip + partial-solution serialize work.

### 5. Server (self-hosted) — the payload win
- **`python/cuopt_server`** request schema — add a `cost_matrix_csr` object
  `{offsets:[...], indices:[...], values:[...]}` (per vehicle type) as an alternative to `cost_matrix_data`.
- Handler: if `cost_matrix_csr` present, call `add_cost_matrix_csr` and **never** build the dense list.
  This is the line that removes the 2,290 MB augmentation.
- Proto/OpenAPI: add the field; keep dense field for back-compat (one-of).

### 6. Productionise the feasibility fix (optional but recommended — was item 2 of the prod list)
- Replace the `set_vehicle_max_costs` co-opt with a dedicated **`SPARSE_ARC` infeasibility dimension**
  (mirror `dim_t` machinery) that drives missing-arc usage to zero, so it composes with real max-cost
  limits. Not required for the benchmark to pass; required for clean semantics.

---

## Suggested order (1 focused day)

| Step | Work | Proof |
|---|---|---|
| A | C++ `add_cost_matrix_csr` setter + data_model_view storage | compiles; unit-set/get |
| B | `fleet_info.cu` populate-from-CSR branch (skip dense) | small solve feasible, no dense alloc |
| C | Cython + Python `add_cost_matrix_csr` + `_SETTERS`/serialize | `production_usage_example.py` via CSR, no `CUOPT_SPARSE_K` |
| D | Regression: 57 py + 40 C++ green (dense untouched) | all pass |
| E | Server `cost_matrix_csr` field + handler (no dense) | 10k K-NN 0.76 MB **submits** |
| F | **Run the exact original sparse-matrix payload benchmark** (K-NN 0.76 MB submit) | payload < 2 GB → **PASS** |
| G | (opt) `SPARSE_ARC` dimension replaces max-cost co-opt | fix composes cleanly |

Steps A–D are the same edit sites the current patch already touches — low risk. E is the new surface (the
server field) and is where the headline payload number gets realised. F is the comparability run the
customer asked for.

---

## Risks / watch-items

- **Index ordering:** `arc_value.hpp` does binary search → per-row `indices` **must be sorted**. Enforce in
  the C++ setter (sort once) rather than trusting the client.
- **Self-loops / depot row:** keep the depot-aware rule from `build_csr` (depot row full; every row
  includes depot(0) + self) so connectivity holds at small K.
- **dtype contract:** offsets/indices int32, values float32 — validate at the Cython boundary; a silent
  int64 will corrupt the read path.
- **Back-compat:** dense `cost_matrix_data` must still work unchanged — one-of, feature-gated. Regression
  suite is the gate.
- **Do NOT commit to NVIDIA/cuopt upstream** — keep as the patch + a branch in the companion repo until the
  owner approves (same policy as the current native-sparse work).

---

## After B5

- Refresh `RESULTS-A10-POC.md` with the **green Phase-4 payload row** (0.76 MB submits, solves) — that is
  the exact number that was FAILED before.
- Then the four production items in `PRODUCTION-USAGE.md` section 4 (sparse time matrix, connectivity-preserving
  CSR builder) are the only things between B5 and a first-class feature.
