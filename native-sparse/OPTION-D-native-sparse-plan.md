# Option D — Native sparse cost core (cuOpt C++): architecture map + plan

Goal: make the solver read a **sparse (K-NN / CSR)** cost representation directly in its innermost
lookup, giving **O(N·K)** memory instead of dense **O(N²)** — the real path to 100k+ stops. Gated behind
a `has_sparse_cost` flag so dense problems stay **byte-for-byte** upstream.

## The injection point (mapped from source)

Every cost/time read in the routing solver funnels through **one** place:

- `cpp/src/routing/arc_value.hpp`
  - `lookup_dist(table, i, j, width)  ->  table[i*width + j]`   ← the dense O(1) index
  - `get_distance(l1, l2, vehicle_info)`  → `lookup_dist(cost_matrix, i, j, width)`
  - `get_transit_time(l1, l2, vehicle_info)` → `lookup_dist(time_matrix, i, j, width)`
- Storage: `cpp/src/routing/utilities/md_utils.hpp` — `mdarray_view_t` holds a flat dense buffer,
  `extent = [n_vehicle_types, n_matrix_types, n_loc, n_loc]`; `get_cost_matrix(type)` returns a raw
  pointer indexed as `matrix[i*n_loc + j]`.
- The pointer reaches the device via `VehicleInfo.matrices` (built in `fleet_info.cu` / `problem.cu`
  from `data_model_view.cost_matrices_`).

Because all reads pass through `lookup_dist` / `get_distance` / `get_transit_time`, a sparse path can be
injected at exactly these functions — the solver's local search, route eval, etc. all inherit it.

## The design (gated)

1. **Storage (device CSR).** Alongside the dense buffer, add a device CSR per (vehicle_type, matrix_type):
   `row_offsets [N+1]`, `col_indices [nnz]`, `values [nnz]` (nnz = N·K), with each row's neighbours
   **sorted by column** for binary search. Add `bool has_sparse_cost` on the matrices view / VehicleInfo.
2. **Lookup.** In `lookup_dist` (or a sparse-aware `get_distance`/`get_transit_time`), branch on
   `has_sparse_cost`:
   - dense: unchanged `table[i*width+j]`.
   - sparse: binary-search row `i`'s `[row_offsets[i], row_offsets[i+1])` slice of `col_indices` for `j`;
     if found return `values[...]`; else return a large sentinel `BIG_COST` ("(i,j) not directly
     connected").
3. **Gate.** `has_sparse_cost == false` → the dense branch compiles/executes identically to upstream
   (uniform-across-warp branch, predictable). This preserves the "zero cost when unused" guarantee.
4. **Ingestion.** `add_cost_matrix` gains a sparse overload (CSR/K-NN in), stored without densifying;
   Python/Cython + server plumbing mirror the existing dense path.

## The hard parts (honest R&D risk — this is why it's multi-week)

- **Search-space semantics.** A sparse matrix means (i,j) pairs outside the K-NN set are effectively
  "infinite". Local-search moves (2-opt, relocate, etc.) that would use those arcs are forbidden. This
  **changes the solution space**, not just storage — solution quality vs dense must be measured, and K
  chosen so the reachable graph stays connected and near-optimal.
- **Performance of the hot load.** Dense is a single coalesced O(1) load. Sparse is O(log K) binary
  search with potentially uncoalesced/divergent access. Must be measured; layout (sorted neighbours,
  possibly a hashed lookup) matters. **This is the one place "no perf impact" needs measured proof.**
- **Plumbing depth.** The sparse buffers must thread through `data_model_view -> fleet_info -> problem
  -> VehicleInfo.matrices -> arc_value`, plus Python/Cython/server. Broad but mechanical.

## Incremental plan (build + test at each step, on a separate source branch)

1. **B0** — branch `feature/native-sparse-core` off `main`; add `BIG_COST` sentinel + a `has_sparse_cost`
   flag on the matrices view (default false). Build; confirm dense unchanged (routing tests still pass).
2. **B1** — add device CSR fields to the matrices view/VehicleInfo (unused when flag false). Build; dense
   tests still pass.
3. **B2** — implement the sparse branch in `lookup_dist`/`get_distance`/`get_transit_time` (binary
   search + sentinel), still only reachable when the flag is set. Unit-test the lookup in isolation.
4. **B3** — a minimal ingestion path (build CSR from a dense matrix by keeping top-K per row) to drive an
   end-to-end sparse solve on a small instance; compare objective vs the dense solve (quality delta).
5. **B4** — benchmark the sparse lookup vs dense on a mid instance (the measured-proof step); tune layout.
6. **B5** — real K-NN ingestion API (coords + K) + Python/server plumbing; scale test toward 100k.

Steps B0–B3 are the feasibility core (does it build, is it correct, what's the quality delta). B4–B6 are
the productionisation + the measured performance case.

## Status

- [x] Hot-path mapped (`arc_value.hpp` is the single injection point)
- [ ] B0 flag/sentinel · [ ] B1 CSR storage · [ ] B2 sparse lookup · [ ] B3 e2e small · [ ] B4 bench · [ ] B5 API
