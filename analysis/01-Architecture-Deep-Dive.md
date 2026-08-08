# 01 — Architecture Deep-Dive

*Why this matters:* you cannot credibly claim "no performance impact" without understanding how the
solver is structured. This section establishes that cuOpt's routing engine is built for exactly this
kind of extension. All references point to files in `cuopt-src/` (branch `main`, VERSION 26.10.00).

---

## 1. The engine is a GPU local-search solver organised by "dimensions"

The routing solver (`cpp/src/routing/`, ~34k lines of CUDA/C++ across 158 files) evaluates and mutates
routes on the GPU. Every quantity a route accumulates — distance, time, capacity, prizes, breaks — is a
**dimension**. The full set is a single compile-time enum:

```cpp
// cpp/src/routing/dimensions.cuh:19
enum class dim_t {
  DIST = 0,
  TIME,
  CAP,
  PRIZE,
  TASKS,
  SERVICE_TIME,
  MISMATCH,             // ← vehicle/order skill match (Feature 2 already lives here)
  BREAK,                // ← driver breaks (Feature 1 extends this family)
  VEHICLE_FIXED_COST,
  SIZE
};
```

Costs across all dimensions are carried in a **fixed-size, stack-allocated vector** whose length is known
at compile time:

```cpp
// cpp/src/routing/dimensions.cuh:43
template <class enum_t>
struct static_vec_t {
  static constexpr size_t N = (size_t)enum_t::SIZE;   // compile-time length
  double cost[N];                                     // no heap, no pointer chasing
  ...
};
using infeasible_cost_t = static_vec_t<dim_t>;        // dimensions.cuh:181
```

**Architectural consequence:** dimensions are resolved at compile time via
`get_dimension_of<I>()` (`dimensions.cuh:240`), a templated `if constexpr` dispatch. There is **no virtual
dispatch, no runtime dimension list, no per-dimension allocation** in the hot path. Adding a dimension is a
first-class, supported operation — the enum, the cost vector, and the dispatch all scale by design.

---

## 2. Each dimension carries an "info" struct that gates its own work

Every dimension has a small info struct with a `has_constraints()` predicate. Two are directly relevant:

```cpp
// cpp/src/routing/dimensions.cuh:216
struct mismatch_dimension_info_t {
  bool has_vehicle_order_match = false;
  constexpr bool has_constraints() const { return has_vehicle_order_match; }
};

// cpp/src/routing/dimensions.cuh:221
struct break_dimension_info_t {
  bool has_breaks = false;
  constexpr bool has_constraints() const { return has_breaks; };
};
```

These booleans are the **feature gates**. When a customer's problem does not use a constraint, the
corresponding `has_*` flag is `false` and the solver skips that dimension's work entirely. This is the
mechanism that makes new features **zero-cost when unused** (quantified in `03-Performance-Preservation.md`).

---

## 3. Travel-cost and travel-time matrices are already multi-matrix, keyed by a `uint8_t`

This is the single most important discovery for Feature 3 (time-of-day traffic). The data model does **not**
hold one cost matrix — it holds a **map of matrices selected by a key**:

```cpp
// cpp/src/routing/data_model_view.cu:46
void data_model_view_t<i_t,f_t>::add_cost_matrix(f_t const* matrix, uint8_t vehicle_type) {
  cost_matrices_[vehicle_type] = matrix;
}
// cpp/src/routing/data_model_view.cu:53
void data_model_view_t<i_t,f_t>::add_transit_time_matrix(f_t const* matrix, uint8_t vehicle_type) {
  transit_time_matrices_[vehicle_type] = matrix;
}
// cpp/src/routing/data_model_view.cu:515
f_t const* get_cost_matrix(uint8_t vehicle_type) const noexcept;
```

Today the selector key is **vehicle type** (car vs. bike). The infrastructure to *store several matrices and
choose one at lookup time already exists* — time-of-day routing is an **extension of the selector**
(`vehicle_type` → `(vehicle_type, time_bucket)`), not a new subsystem. That reframes Feature 3 from
"impossible / rewrite" to "hard but bounded" (see `02` design).

---

## 4. The skill-match constraint is fully implemented as a hard feasibility mask

Feature 2 is **not** missing. The solver builds an explicit vehicle×order boolean matrix and even
cross-validates the two directions of the constraint:

```cpp
// cpp/src/routing/fleet_order_constraints.cu:21
rmm::device_uvector<bool> generate_vehicle_order_match_matrix(...) {
  const auto& vehicle_order_match = data_model.get_vehicle_order_match();   // :30
  const auto& order_vehicle_match = data_model.get_order_vehicle_match();   // :31
  std::vector<bool> vehicle_order_match_h(n_orders * fleet_size, true);     // :35
  ...
  // vehicle_order_match_h[vehicle_id * n_orders + order_id] = false;       // :46 (forbidden pairs)
  ...
  cuopt_assert(..., "Mismatch between vehicle_order_match and order_vehicle_match constraints!"); // :63
}
```

The mask feeds the `MISMATCH` dimension. Therefore a *violation in a returned (partial) solution* is a
**correctness bug in enforcement or in the infeasible/relaxation path** — not an absent feature. This
changes ownership and effort (see `02`).

---

## 5. Reference implementation proof: PR #1196 adds a feature the "right" way

PR #1196 ("distance breaks" = mandatory recharge within a cumulative-distance window) is a **complete,
tested reference** for how a routing feature is added to this codebase. Diff shape — measured against the
PR's branch point, `git diff $(git merge-base main pr-1196)..pr-1196 --stat` (a bare `git diff main pr-1196`
no longer works: `main` has advanced 1000+ files past the branch point and would swamp the PR's own changes):

| Area | Files | Notes |
|------|-------|-------|
| Solver core (CUDA/C++) | 12 | `dimensions.cuh` **+7 lines only** — reuses DIST dimension |
| Tests (C++ + Python) | 2 | **913 lines** (`distance_breaks.cu` 426, `test_distance_breaks.py` 487) |
| Server / Python API | ~9 | Pydantic schema, validation, bindings |
| Docs / examples | ~5 | `.rst` + `distance_break_example.py` |
| **Total** | **29 files** | **~1,882 lines, of which ~49% are tests** |

The core-compute change is small and localised. Crucially, **every hot-path addition is gated** behind a
runtime flag (`03-Performance-Preservation.md` quotes the exact lines). This is the template we follow for
all three features.

---

## Takeaways feeding the rest of the study

1. The solver is **designed to be extended by dimension** — compile-time, allocation-free, no virtual dispatch.
2. **Feature-gating is idiomatic** here (`has_*` flags) → new work is skippable → zero cost when off.
3. **Feature 2 already exists** as a hard mask → it's a bug hunt, not a build.
4. **Feature 3's multi-matrix plumbing already exists** → extend the selector, don't rebuild.
5. **PR #1196 is a working, tested exemplar** for Feature 1 and a pattern for the others.
