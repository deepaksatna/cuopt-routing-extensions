# 03 — Performance Preservation (and where we can *improve*)

The user's explicit bar: **"it will not impact any performance and even improve with those features."**
This section shows, with code, why that bar is achievable — and where genuine speedups are on the table.

---

## The core guarantee: feature-gating makes new work zero-cost when unused

cuOpt's idiom is that every optional constraint is guarded by a compile-time-friendly runtime flag on the
dimension's info struct. PR #1196 demonstrates it exactly. From the EV feature's hot path:

```cpp
// cpp/src/routing/route/distance_route.cuh  (git diff main..pr-1196)
DI distance_node_t<i_t,f_t> get_node(i_t idx) const {
  distance_node_t<i_t,f_t> n;
  n.distance_forward  = distance_forward[idx];
  n.distance_backward = distance_backward[idx];
  if (dim_info.has_distance_window) {              // ← GATE
    n.distance_window_forward  = distance_window_forward[idx];
    n.window_start             = window_start[idx];
    n.excess_forward           = excess_forward[idx];
    ...
  }
  return n;
}

void resize(i_t max_nodes_per_route, ...) {
  distance_forward.resize(max_nodes_per_route, stream);
  ...
  if (dim_info.has_distance_window) {              // ← ALLOCATION ALSO GATED
    distance_window_forward.resize(max_nodes_per_route, stream);
    excess_forward.resize(max_nodes_per_route, stream);
    ...
  }
}
```

**Two guarantees fall out of this:**

1. **No extra memory when unused.** The buffers (`distance_window_forward`, `excess_forward`, …) are only
   `resize`d when `has_distance_window` is true. A non-EV problem allocates exactly what upstream allocates.
2. **No extra compute when unused.** Every read/write of the new state is inside `if (has_distance_window)`.
   The branch is on a value that is **uniform across the warp** (a per-problem flag), so on the GPU it is a
   predictable, non-divergent branch — effectively free. A non-EV problem executes the same instructions as
   upstream.

Because all three features follow this same idiom (`has_distance_window`, `has_breaks`,
`has_vehicle_order_match`, and the proposed `has_time_dependency`), **the feature-OFF path is identical to
upstream cuOpt**. That is the literal meaning of "will not impact any performance."

---

## Per-feature performance analysis

### Feature 1 — EV charging
- **OFF:** identical to upstream (gated, proven above).
- **ON:** adds O(nodes-per-route) window/excess bookkeeping **only on routes that use the constraint**. This
  is the intrinsic cost of the capability, not overhead. It runs in the same coalesced, per-route kernels as
  the existing DIST dimension, so it inherits cuOpt's memory-access efficiency.

### Feature 2 — Skill match (bug fix)
- **OFF:** unchanged.
- **ON:** the mask is **already built and already consulted** today; the fix changes *decision logic in the
  relaxation path*, not the accumulation hot path. **Net effect can be positive:** correctly treating
  forbidden vehicle→order pairs as inviolable **prunes branches** the solver would otherwise explore before
  rejecting — a smaller feasible search space can converge faster on tightly-constrained fleets. This is the
  one place the user's "even improve" is concretely plausible.

### Feature 3 — Time-of-day
- **Tier A (app layer):** no solver code changes → **zero** solver performance impact by construction.
- **Tier B (native), OFF:** gated behind `has_time_dependency` → identical to upstream.
- **Tier B (native), ON:** one bucket-index computation + one additional indexed matrix load per arc
  evaluation. Matrices are read-only and can be bound to texture/`__ldg` read paths; the extra load is L2/
  texture-cache friendly. Cost is a small constant per arc, incurred only when the feature is active.

---

## Where we can *improve* performance (opportunities surfaced during analysis)

These are optional, separable wins — not required by the three features, but available because we now
understand the code:

1. **Constraint-aware pruning (Feature 2 side-effect).** As above, hardening MISMATCH can shrink the search
   space on constrained problems → faster convergence, better solutions in the same time budget.
2. **Skip-flags we can contribute upstream.** `build.sh` already exposes `--skip-routing-build`,
   `--skip-tests-build`, `--build-lp-only`. For deployments that only route, a leaner build reduces binary
   size and load time. Low-risk contribution.
3. **Matrix memory-access tuning.** The multi-matrix path (relevant to Feature 3) is a natural place to
   evaluate texture-cache binding / `__ldg` for the read-only cost matrices — a general routing speedup, not
   just time-of-day.
4. **Reuse over re-solve (app layer).** For time-of-day Tier A, warm-start each window's solve from the prior
   window's routes to cut solve time versus independent cold solves.

None of these are prerequisites; they are the honest "and even improve" answer, kept separate from the
"do no harm" guarantee so the two claims are not conflated.

---

## How we will *prove* it (not just argue it)

A claim of "no regression" must be measured, per your standing practice of always capturing benchmark
numbers. The gate before any adoption:

- **Baseline vs. feature-OFF:** run cuOpt's own routing benchmark set on stock `main` and on our build with
  the feature compiled in but **not activated**. Requirement: **within noise (±a few %).**
- **Feature-ON cost curve:** measure solve-time vs. problem size with the feature active; record the marginal
  cost so it is a known, documented number — never "it's fine."
- **Hardware:** an available GPU box (A10 / H100). Capture date, GPU, driver/CUDA, dataset, and method.

Until the feature-OFF regression test passes within noise, no change is considered "performance-safe."
