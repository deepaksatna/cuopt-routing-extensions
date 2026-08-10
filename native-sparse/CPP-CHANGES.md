# C++ solver changes, annotated

This is a readable walkthrough of the C++ changes for maintainer review, so the code can be read without
applying the patch. It shows only the lines added by `native-sparse-core.patch`; no cuOpt source is
reproduced. The authoritative artifact is `native-sparse-core.patch` (apply on cuOpt at commit f3ebc673).

Scope: 3 files, about 175 lines, all behind a `has_sparse_cost` flag. With the flag unset, none of this
code runs and dense problems are identical to upstream cuOpt.

- cpp/src/routing/arc_value.hpp        - the cost-lookup read path (the core change)
- cpp/src/routing/utilities/md_utils.hpp - CSR storage on the device and a CSR builder
- cpp/src/routing/fleet_info.cu        - a hook to enable the sparse path

Design in one line: the whole solver reads travel cost through one function, `get_distance()`; we add a
single gated branch there that reads from a CSR (K-nearest-neighbour) structure by binary search, instead of
indexing a dense N by N matrix.

---

## 1. arc_value.hpp - the read path

A finite sentinel is added for pairs that are not in the sparse graph. It is large but finite so that
route-cost accumulation stays well defined (using infinity would break comparisons in the local search).

```cpp
// Sentinel cost for an (i,j) pair absent from a sparse cost matrix.
// Large but finite so route-cost accumulation stays well-defined.
constexpr double BIG_COST = 1e6;
```

The change to `get_distance()` (the single point every part of the solver uses to read cost):

```cpp
// Native sparse: read the CSR cost matrix directly (O(log K) binary search)
// instead of the dense O(1) index. Gated: dense problems never enter this branch.
if (vehicle_info.matrices.has_sparse_cost) {
  const auto& m = vehicle_info.matrices;
  const auto i  = l1.location();
  const auto j  = l2.location();
  int lo = m.csr_offsets[i];
  int hi = m.csr_offsets[i + 1];
  while (lo < hi) {                       // binary search within row i's neighbours
    const int mid = (lo + hi) >> 1;
    const int c   = m.csr_indices[mid];
    if (c == j) return m.csr_values[mid]; // arc (i,j) is in the K-NN graph
    if (c < j) { lo = mid + 1; } else { hi = mid; }
  }
  return BIG_COST;                        // arc (i,j) not kept -> treated as very expensive
}
// unchanged dense path below:
auto matrix = vehicle_info.matrices.get_cost_matrix(vehicle_info.type);
return lookup_dist(matrix, l1.location(), l2.location(), vehicle_info.matrices.extent[3]);
```

Annotations:
- The branch is guarded by `has_sparse_cost`. When false, control falls through to the original dense
  lookup, unchanged. This is why dense behaviour is bit-for-bit identical.
- Row i's neighbour column indices are stored sorted, so a present arc is found in O(log K).
- An absent arc returns the sentinel. Pairing this with a per-vehicle max-cost limit below the sentinel
  makes "use a missing arc" infeasible, so the solver does not route through gaps.
- Choosing this single function keeps the change small and auditable: it is the one cost-lookup chokepoint,
  not a broad refactor.

---

## 2. md_utils.hpp - CSR storage and builder

Three read-only pointers are added to the matrix view that the solver sees. They are inert unless
`has_sparse_cost` is set.

```cpp
// native sparse scaffolding; inert unless has_sparse_cost is set
bool has_sparse_cost{false};
const int* csr_offsets{nullptr};  // [n_loc + 1] row offsets (cost matrix)
const int* csr_indices{nullptr};  // [nnz] column indices, sorted within each row
f_t  const* csr_values{nullptr};  // [nnz] cost values
```

Device-side storage is added to the owning structure (`d_mdarray_t`), using cuOpt's existing RMM device
vectors, and the view is wired to expose it once built:

```cpp
rmm::device_uvector<int> csr_offsets;
rmm::device_uvector<int> csr_indices;
rmm::device_uvector<f_t> csr_values;
bool sparse_built{false};

// in view():
if (sparse_built) {
  view.has_sparse_cost = true;
  view.csr_offsets     = csr_offsets.data();
  view.csr_indices     = csr_indices.data();
  view.csr_values      = csr_values.data();
}
```

A CSR builder constructs the sparse structure from a dense cost matrix (used by the prototype hook and as a
reference for the ingestion path). It is depot-aware so connectivity is preserved at small K:

```cpp
// Build a CSR from the dense cost matrix. K <= 0 or K >= n keeps all entries (lossless);
// otherwise keep the K smallest-cost columns per row. Columns are sorted for binary search.
void build_csr(int K) {
  const int n = static_cast<int>(extent[3]);
  // ... copy the dense cost matrix to host ...
  for (int i = 0; i < n; ++i) {
    if (i == 0 || K <= 0 || K >= n) {
      // depot row (and lossless mode): keep every column so the depot reaches all nodes
      for (int j = 0; j < n; ++j) sel.push_back(j);
    } else {
      // keep the K nearest columns (partial sort), then add the depot and self
      std::nth_element(cols.begin(), cols.begin() + K, cols.end(),
                       [&](int a, int b){ return dense[row+a] < dense[row+b]; });
      sel.assign(cols.begin(), cols.begin() + K);
      sel.push_back(0);  // depot connectivity: guarantees return-to-depot is feasible
      sel.push_back(i);  // self
      std::sort(sel.begin(), sel.end());
      sel.erase(std::unique(sel.begin(), sel.end()), sel.end());
    }
    // append sel's indices/values into the CSR; record the row offset
  }
  // ... copy offsets/indices/values to the device; set sparse_built = true ...
}
```

Annotations:
- Depot-aware: row 0 (depot) keeps all columns, and every other row includes the depot and self. This
  guarantees a feasible return-to-depot even for small K.
- Columns are sorted per row, which is what lets the read path in arc_value.hpp binary-search.
- Memory is O(N*K): offsets is N+1, indices and values are nnz (about N*(K+2)). For 100,000 stops at K=16
  that is about 13 MB, versus 40 GB for the dense matrix.

---

## 3. fleet_info.cu - the enable hook

A small hook builds the CSR after the matrices are populated, enabling the sparse read path. In the
prototype it is triggered by an environment variable; the production trigger is the B5 REST ingestion
(`cost_matrix_csr`), which supplies the CSR directly.

```cpp
detail::fill_mdarray_from_data_model(matrices_, data_model);
// CUOPT_SPARSE_K=<K> builds a CSR from the dense matrix and flips on the sparse read path.
if (const char* ks = std::getenv("CUOPT_SPARSE_K")) { matrices_.build_csr(std::atoi(ks)); }
```

Annotation: this is the only place that turns the feature on. With the variable unset (and no
`cost_matrix_csr` in the request), `sparse_built` stays false, `has_sparse_cost` stays false, and the solver
runs the unchanged dense path.

---

## Why there is no measured performance regression for dense

Every added line is inside a `has_sparse_cost` guard or a `sparse_built` guard. The dense code path is
untouched, so dense solves are identical to upstream. This is verified by the regression suite (see the
repository README): 57 routing tests pass with the feature off, and the C++ and Python suites match stock
cuOpt behaviour.
