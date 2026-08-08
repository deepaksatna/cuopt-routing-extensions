# 02 — Feature Feasibility & Design

For each capability: current state → proposed design → effort → risk → performance stance.
Effort is in engineer-weeks for one experienced CUDA/C++ engineer, *after* a working build exists
(build bring-up is costed once in `04-Implementation-Roadmap.md`).

---

## Feature 1 — EV charging stops (distance-windowed mandatory recharge)

**Current state:** Implemented in **PR #1196**, open against `main`, unmerged, awaiting first review.
Not in any shipping release (25.12 / 26.06 / 26.08).

**What it does (from the PR):** a *distance break* is a mandatory charging stop the vehicle must take
within a cumulative-distance window `[distance_min, distance_max]`, optionally restricted to specific
charging-station locations.

**Design — we do NOT design this; we adopt it.** The correct professional move is to **not fork-and-invent**.
Instead:

1. Build cuOpt from source at `main`.
2. Merge / cherry-pick `pr-1196` (already fetched into `cuopt-src` as branch `pr-1196`).
3. Run its bundled test suites (`distance_breaks.cu` 426 lines, `test_distance_breaks.py` 487 lines).
4. Expose `add_distance_break()` through the self-hosted server and wire it into the v4 front-end payload.
5. **Upstream-first:** review/upvote/help-land PR #1196 so we inherit it maintained, rather than carry a fork.

**How it preserves performance:** the entire per-node hot path is gated behind `dim_info.has_distance_window`
(`distance_route.cuh`, quoted in `03`). Problems without EV constraints allocate nothing and branch out
immediately. See `03` section Feature 1.

| Metric | Assessment |
|--------|-----------|
| Effort | **1–2 weeks** (dominated by build bring-up + validation, not coding) |
| Risk | **Low** — code + tests already written by NVIDIA-side contributor |
| Perf impact when unused | **Zero** (feature-gated) |
| Perf impact when used | Bounded extra O(nodes) window bookkeeping on affected routes only |
| Maintenance | **Low if upstreamed**, Medium if we carry a fork |

---

## Feature 2 — Hard vehicle/order skill-match honoured in partial solutions

**Current state:** Feature **exists** as the `MISMATCH` dimension backed by a hard vehicle×order boolean
mask (`fleet_order_constraints.cu:21`, `dimensions.cuh:216`). The vendor's report is that a **partial /
infeasible** result can be returned that **violates** this supposedly-hard constraint. That is a
**correctness defect**, not a missing feature.

**Design — reproduce, then choose the minimal correct fix:**

1. **Reproduce.** Build a minimal payload with a `vehicle_order_match` that forces infeasibility (workload
   exceeds vehicle-hours) and confirm whether the returned partial solution assigns a forbidden vehicle→order
   pair. Capture it as a regression test.
2. **Localise.** The mask enforcement lives in the `MISMATCH` dimension's feasibility check. The relaxation
   path is prize-collection / `solver_infeasible_response`. The bug is almost certainly that **prize-collection
   is allowed to drop or relax a MISMATCH-forbidden assignment instead of treating it as inviolable.**
3. **Fix options (pick smallest that is correct):**
   - **(a) Enforce hardness in the relaxation path** — mark MISMATCH as non-relaxable so the solver drops the
     *task* (leaves it unserved) rather than assigning a forbidden vehicle. Correct and localised.
   - **(b) Post-solve guard (defence in depth)** — in the server, reject/flag any returned route that breaks
     the input mask. Cheap, immediate, and belongs in our layer regardless of (a).
4. **Upstream** the failing repro as a GitHub issue + the fix as a PR.

**How it preserves performance:** the fix is in the **feasibility/relaxation logic**, not the accumulation
hot path; the mask already exists and is already consulted. No new per-node cost. If anything, correctly
pruning forbidden assignments **shrinks the search space** → potential net speedup on constrained problems.

| Metric | Assessment |
|--------|-----------|
| Effort | **1–3 weeks** (mostly reproduction + validation; fix is small once localised) |
| Risk | **Low-Medium** — requires understanding the relaxation/prize path |
| Perf impact | **Neutral to positive** (pruning forbidden pairs reduces branching) |
| Ownership | Prefer NVIDIA-owned fix; our post-solve guard (b) ships immediately regardless |

---

## Feature 3 — Time-of-day / rush-hour travel times

**Current state:** Not supported. Multiple cost/travel-time matrices exist but are keyed by **vehicle type**
only (`data_model_view.cu:46/53/515`). No temporal selection.

**Why it's feasible (not a rewrite):** the storage and lookup already handle *N matrices selected by a
`uint8_t` key*. Time-of-day is a **change to the selector**, not a new data path. Two design tiers:

### Tier A — Application layer (ship now, zero solver change)
Pre-compute time-bucketed matrices externally (HERE/TomTom/Google per departure window) and solve **one
cuOpt job per departure window**, then stitch. Delivers the customer outcome with **no fork, no perf risk**.
This is the recommended first delivery and the fallback if Tier B is deprioritised.

### Tier B — Native time-dependent matrices (the real solver feature)
Extend the multi-matrix mechanism so the arc cost/time lookup selects the matrix by the vehicle's **current
cumulative time** at that node:

1. Store matrices as `matrices_[vehicle_type][time_bucket]` (extend the existing map key).
2. In the forward-time accumulation (the TIME dimension's node evaluation), select the bucket from the
   running arrival time and read the corresponding matrix entry.
3. Gate the whole path behind a new `time_dependent_dimension_info_t::has_time_dependency` flag — **off by
   default, zero cost when unused** (same idiom as `has_distance_window`, `has_breaks`).
4. Handle the "FIFO" property (later departure never arrives earlier) to keep the local-search moves valid.

**Honest risk note:** Tier B touches the TIME dimension's hot accumulation, which is genuinely performance-
sensitive. The additive cost is a bucket-index computation + an extra indexed load per arc **only when the
flag is on**. Correctness of local-search move evaluation under time-dependent costs is the hard part and
must be covered by tests mirroring PR #1196's rigour (~450+ line test suite).

| Metric | Assessment |
|--------|-----------|
| Effort (Tier A) | **Days** — application layer, no cuOpt change |
| Effort (Tier B) | **4–8 weeks** — new solver logic + extensive tests |
| Risk (Tier A) | **Very low** |
| Risk (Tier B) | **Medium-High** — touches TIME hot path; correctness-critical |
| Perf when unused | **Zero** (feature-gated, both tiers) |
| Perf when used | Tier A: none (separate jobs). Tier B: small per-arc constant, on-demand only |

---

## Summary matrix

| Feature | Verdict | Effort | Risk | Perf when OFF | Perf when ON | Recommended path |
|---------|---------|--------|------|---------------|--------------|------------------|
| 1 — EV charging | **Do it** | 1–2 wk | Low | Zero | Bounded, per-route | Adopt PR #1196, upstream-first |
| 2 — Skill match | **Do it** | 1–3 wk | Low-Med | Neutral | **Neutral→faster** | Repro + fix upstream + server guard |
| 3 — Time-of-day | **Tier A now, Tier B if funded** | Days / 4–8 wk | VLow / Med-High | Zero | None / small | App-layer first; native later |

**Overall:** none of the three requires degrading the solver. All three follow cuOpt's own feature-gating
idiom, so the default (feature-off) code path is byte-for-byte the performance of upstream.
