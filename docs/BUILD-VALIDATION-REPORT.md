# cuOpt From-Source Build & PR #1196 (EV Distance-Breaks) Validation — Worklog

**Purpose.** A reproducible record of what we tried, why, and what we achieved when building
**NVIDIA/cuopt** (`main`, VERSION `26.10.00`) from source and adopting the **EV charging /
distance-breaks** feature from **PR #1196**. Written to be shareable with the cuOpt maintainers /
PR author: it contains the exact environment, the issues we hit, the fixes we applied, and the
test results — including one **reproducible open item** for upstream (a multi-cycle break test).

*Companion file:* `COMMANDS-RUNBOOK.md` — the exact, copy-pasteable command sequence.

---

## 1. Executive summary

| Milestone | Result |
|-----------|--------|
| Build cuOpt `main` from source (GPU box) | ✅ **Success** — `import cuopt` = 26.10.00 |
| cuOpt routing test suite (baseline green signal) | ✅ **57 passed** (151 s) |
| Adopt PR #1196 (EV distance-breaks) — merge onto current `main` | ✅ **Clean except 1 test file** (28/29 files merge clean) |
| Rebuild with EV feature | ✅ **Success** |
| PR #1196's own test suite (`test_distance_breaks.py`) | ⚠️ **29 passed / 1 failed** after 2 integration fixes |

**Headline for the feasibility study:** PR #1196's **C++ solver core merges cleanly** onto a `main`
that has advanced **1000+ commits** past the PR's branch point. The only friction is (a) a trivial
one-file **test** merge conflict and (b) **two Python-integration drifts** where the PR's Python glue
predates a `main` refactor of the `DataModel` class. All were fixable in minutes. One multi-cycle
solver test remains failing and is documented below as an open question for upstream.

---

## 2. Environment (hardware / toolchain)

| Item | Value |
|------|-------|
| GPU box | OCI `VM.GPU.A10.2` — **2 × NVIDIA A10** (23 GB each), driver **595.71.05**, compute cap **8.6** |
| CPU / RAM | 60 vCPU / 471 GB (build throttled to `PARALLEL_LEVEL=32`) |
| OS | Oracle Linux 9.8, kernel 5.15 UEK |
| Disk | Boot volume grown 30 GB → **283 GB** via `oci-growfs` (build tree + toolchain need ~120 GB) |
| Build arch | **single-arch** `CUDAARCHS=86` (fast; vs `--allgpuarch`) |
| Toolchain (conda env) | CUDA **13.3.73**, GCC **14.4.0**, Python **3.14.6**, CMake 4.4 |
| cuOpt | `main` VERSION `26.10.00`, HEAD `f3ebc673` (build), merge commit `448fb194` (with PR #1196) |
| PR #1196 branch point (merge-base) | `7b6e43db` |

> Note: an earlier attempt on a single-GPU **L40S** (8 vCPU / 31 GB) also compiled the C++ cleanly,
> but the 2×A10 box was preferred because it (a) has 60 cores for a ~5× faster build and (b) **matches
> the study's benchmark-baseline hardware** (`VM.GPU.A10.2`), so build + functional tests + the
> eventual no-regression benchmark can all run on the correct HW.

---

## 3. Phase 0 — from-source build

Followed the project's `scripts/phase0_bootstrap.sh` (README Phase 0): preflight → miniforge →
clone `main` → create CUDA-13.3 conda env → single-arch build → routing tests as the green signal.

### 3.1 Issues hit and fixes (all folded back into `scripts/phase0_bootstrap.sh`)

| # | Symptom | Root cause | Fix |
|---|---------|-----------|-----|
| 1 | Build hung silently | `mamba env create` waited on an interactive `Confirm changes: [Y/n]` | Add **`--yes`** to `mamba env create`/`update` |
| 2 | `EXIT_CODE=1` right after env build; `NVCC_PREPEND_FLAGS: unbound variable` | conda's `cuda-nvcc` `activate.d` script references an unset var, tripping the script's `set -u` | Wrap `conda activate` in **`set +u` … `set -u`** |
| 3 | C++ built (`[372/373]`) but **Python wheel failed**: `rapids_cython_create_modules` → *"Target waypoint_matrix_wrapper links to cuopt::cuopt but the target was not found"* | `build.sh` **default does not install libcuopt** into the conda prefix (its own help line says so), so the Python build's `find_package(cuopt)` can't resolve `cuopt::cuopt` | Add **`--install`** to `build.sh` (installs `libcuopt.so` + `cuopt-config.cmake` into `$CONDA_PREFIX`) |
| 4 | Routing tests errored: `FileNotFoundError: .../datasets/solomon/In/r107.txt` | Tests read Solomon/PDPTW instances from `RAPIDS_DATASET_ROOT_DIR`, which defaults to `<cwd>/../datasets` (wrong path) | Run **`datasets/get_test_data.sh`** and export **`RAPIDS_DATASET_ROOT_DIR=$REPO/datasets`** |

> **NOT a problem:** Python 3.14. cuOpt 26.10 declares `requires-python >=3.11` and lists 3.14 in its
> classifiers; the wheel failure (#3) was purely the missing `--install`, not the Python version.

### 3.2 Result

```
import cuopt  →  26.10.00
pytest python/cuopt/cuopt/tests/routing  →  57 passed, 82 warnings in 151.41s   (PYTEST_EXIT=0)
```

C++ build wall-time: **4m35s** (single-arch, 32 jobs). This is the Phase-0 exit gate — **met**.

---

## 4. Phase 2 — adopt PR #1196 (EV distance-breaks)

Goal (per the study): *do not fork-and-invent; build + validate + adopt the existing PR.*

### 4.1 Does the PR still merge? (the key unknown)

`main` has moved **1000+ commits** since PR #1196 branched, so `git diff main..pr-1196` is meaningless
now (it reports ~1000 files). Measured against the **merge-base** the PR is unchanged and small:

```
git diff $(git merge-base HEAD pr-1196)..pr-1196 --stat
→ 29 files changed, 1882 insertions(+), 108 deletions(-)
```

**Merge result:** conflict in **exactly one file** — `cpp/tests/routing/level1/l1_routing_test.cu`
(a test file). **All 28 solver-core files merged clean** (incl. `dimensions.cuh`, `distance_route.cuh`).

### 4.2 Conflict resolution (1 file)

The conflict was at the end of `l1_routing_test.cu`:
- `main` had **removed** the per-file `CUOPT_TEST_PROGRAM_MAIN()` macro (test main is now provided
  globally).
- PR #1196 adds the `l1_distance_breaks` test instantiation **and** re-adds `CUOPT_TEST_PROGRAM_MAIN()`.

**Resolution:** keep the PR's `l1_distance_breaks` `INSTANTIATE_TEST_SUITE_P(...)`; **drop** the
re-added `CUOPT_TEST_PROGRAM_MAIN()` (re-adding it would duplicate a symbol `main` no longer expects
here). Committed as merge `448fb194`.

### 4.3 Integration drifts found (PR's Python layer vs. current `main`)

The EV rebuild succeeded, but PR #1196's **Python** test suite initially failed **13/30**. Two
distinct, real integration drifts — both because the PR's Python glue predates a `main` refactor:

**Drift A — stale Cython build cache.** After the merge, the installed
`vehicle_routing_wrapper*.so` was recompiled from a **cached, pre-merge** Cython-generated `.cpp`
(in `python/cuopt/build/`), so `super().add_distance_break(...)` raised
`AttributeError: 'super' object has no attribute 'add_distance_break'` even though the `.pyx`/`.pxd`
and the C++ header all define it.
*Fix:* `rm -rf python/cuopt/build python/libcuopt/build` and rebuild the Python package so Cython
regenerates. (Improvement suggestion for upstream: `build.sh` could invalidate the Cython cache when
`.pyx`/`.pxd` change.)

**Drift B — `DataModel` deferred-setter list missing the new method.** `main` refactored `DataModel`
to a **deferred / record-and-replay** model: mutating setters are listed in a `_SETTERS` tuple in
`python/cuopt/cuopt/routing/_deferred.py` and replayed onto the device model at build time. PR #1196
added `add_distance_break` to `vehicle_routing.py` and the Cython layer, **but not to `_SETTERS`**
(that refactor landed on `main` after the PR was written), so the deferred base never exposed it.
*Fix (1 line):* add `"add_distance_break"` to `_SETTERS`.

### 4.4 Result

After Drifts A + B fixed:

```
pytest test_distance_breaks.py  →  29 passed, 1 failed   (was 13 failed)
```

All 7 `add_distance_break` **API** tests pass; all **solve** tests pass **except one**.

### 4.5 Open item for upstream (reproducible) — `test_solve_full_feature_api`

- **Status:** deterministic failure (3/3 runs).
- **Scenario:** `n_cycles=2`, two non-overlapping cycle windows `[10, 20]` and `[30, 40]`, 5-location
  unit-cost grid (arc = 10), 2 vehicles.
- **Assertion that fails:**
  `vehicle 1 cycle 1 break at cumulative 10.0 outside window [30.0, 40.0]`
  i.e. the **second** cycle's break is observed at absolute cumulative distance `10.0` (inside the
  *first* window) rather than within `[30, 40]`.
- **Two candidate explanations (needs PR-author confirmation):**
  1. **Multi-cycle window enforcement gap** — the second cycle's `[d_min, d_max]` window is not being
     enforced by the solver, or
  2. **Semantics mismatch** — the solver measures **per-cycle (reset-after-recharge)** cumulative
     distance while the test measures **absolute** cumulative distance from route start; the two
     models disagree on what "cycle 1's break distance" means.
- Single-cycle break tests and all API tests pass, so the core distance-break mechanism works; the
  gap is specifically in the **multi-cycle** path.

This is exactly the kind of finding worth handing back to the PR author: the EV feature is real and
adoptable; the multi-cycle full-feature test is the one thing to resolve (bug vs. test expectation).

### 4.6 Root cause of the multi-cycle behavior (code-level) + code-owner guidance

**Mechanism** (`cpp/src/routing/node/distance_node.cuh:46-52`). The distance-window is modeled as a
mirror of the **time window**, with the explicit comment: *"arriving before window_start is free (the
analogue of waiting), arriving after window_end accumulates excess."* In the forward pass, a break
reached **before** its window lower bound `d_min` is **clamped up to `d_min` for free** (no excess);
only **exceeding `d_max`** accumulates excess, which feeds `inf_cost[dim_t::DIST]` (→ infeasible).

**Consequence:**
- The **safety-critical upper bound `d_max` IS hard-enforced** — a vehicle cannot be routed past its
  range without a break (excess → infeasible). *EV "runs out of charge" cannot happen.*
- The **lower bound `d_min` is soft by design** — placing a break early is free, so with several
  stacked cycles the breaks **collapse into the earliest window** (each early break shows zero excess,
  so every cycle looks satisfied). That is what `test_solve_full_feature_api` detects.

**Code-owner (NVIDIA) guidance received:** for the class of *hard-constraint-violated-in-partial-
solution* issues, the intended cuOpt design is to **set prizes on visits** (e.g. all prizes = 1). The
solver then schedules as many visits as possible **without violating constraints**; if resources are
insufficient it returns a **partial** solution (some visits unassigned) rather than a violating one —
"without having to do coding in the cuOpt source."

**We tested the prize guidance against the multi-cycle scenario** (added `set_order_prizes([1,1])`):
break placement was **byte-identical** (both breaks still at cumulative 10.0). Reason: prizes govern
whether **visits/orders** are dropped, not how **breaks** are placed — a different mechanism. So:

- **Prizes = the correct, source-free resolution for Feature 2 (skill-match)** — the solver drops an
  unservable (skill-mismatched) visit instead of assigning a forbidden pair. This *simplifies* the
  study's Feature 2 from "reproduce + fix a bug" to "adopt a documented usage pattern."
- **Prizes do NOT change multi-cycle break placement.** The `d_min` softness is a deliberate
  time-window-mirror design. Given the owner's explicit preference to avoid cuOpt source changes, and
  that this is **not a safety violation** (range/`d_max` is enforced), the recommendation is **not** to
  patch `distance_node.cuh`. Instead: (a) treat single-cycle distance-breaks as production-ready; and
  (b) raise multi-cycle strict per-window placement with the PR author as a **semantics question**
  (should `d_min` be hard for distance breaks, unlike time windows?), not a local fork.

> We deliberately did **not** modify the solver core. The `d_min`-enforcement change (making early
> arrival accumulate excess like late arrival) is a viable one-line direction, but it (1) contradicts
> the documented "early is free" design, (2) would break the node-level unit tests that encode that
> contract, and (3) risks the delicate forward/backward feasibility invariants — so it belongs
> upstream with the PR author, per NVIDIA's own no-source-change guidance.

---

## 5. What this validates for the feasibility study

- **Feature 1 (EV charging) is "build + validate + adopt", not "invent"** — confirmed empirically:
  the PR's C++ merges clean, rebuilds, and 29/30 of its own tests pass.
- **The feature-gating architecture holds** — the EV rebuild touched only 96 targets and the baseline
  routing suite is unaffected (feature is off by default).
- **The realistic adoption cost** is: 1 trivial test-conflict resolution + 2 small Python-integration
  fixes + investigating 1 multi-cycle test. That is a low-risk, days-not-weeks adoption — matching the
  study's "low risk" rating for Feature 1.

---

## 6. Deliverable-script fixes captured

`scripts/phase0_bootstrap.sh` now contains, from this session:
`--yes` (mamba), `set +u` (conda activate), `--install` (libcuopt into prefix),
`get_test_data.sh` + `RAPIDS_DATASET_ROOT_DIR` (test data), and a corrected import smoke-test
(the 26.10 API is `cuopt.routing.{DataModel,SolverSettings,Solve}`, not `cuopt.routing.routing`).

*Prepared during the cuopt-routing-extensions feasibility work. Every result above is reproducible via
`COMMANDS-RUNBOOK.md`.*
