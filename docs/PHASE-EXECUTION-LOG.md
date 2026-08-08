# cuOPT-Dev — Phased Execution Log (H200)

Running record of the phase-by-phase validation, executed autonomously. For each phase:
**what** we did, **why**, **how** (exact steps), and **results**. Companion to the deeper
`BUILD-VALIDATION-REPORT.md`, `FILES-CHANGED.md`, `COMMANDS-RUNBOOK.md`, and `feature2-prizes/RESULTS.md`.

## Environment

| Item | Value |
|------|-------|
| GPU box | NVIDIA **H200** (Hopper, sm_90), driver **580.126.09**, 140 GB VRAM |
| CPU / RAM / disk | 44 vCPU / 178 GB / 1.3 TB free |
| Provisioning | Brev instance `gpu-box` (user `ubuntu`) |
| Toolchain | CUDA 13.3, GCC 14.x, Python 3.14, single-arch `CUDAARCHS=90`, 32 build jobs |
| cuOpt | `main` VERSION 26.10.00, base HEAD `f3ebc673` |

> Note: this H200 is a **fresh rebuild** after the earlier 2×A10 GPU box was terminated. Because the
> deliverable `scripts/phase0_bootstrap.sh` now carries all four Phase-0 fixes, the build reproduced
> green in a single unattended shot — itself a validation of the fixed script.

---

## Phase 0 — Build cuOpt from source ✅ DONE

- **What:** Build `libcuopt` + `cuopt` from `main` and run the routing test suite as the green signal.
- **Why:** Establish a working, tested baseline before adopting any feature — you cannot claim
  "no regression" without a reproducible build + passing baseline.
- **How:** `JOBS=32 MERGE_PR=0 RUN_TESTS=1 bash phase0_bootstrap.sh` (single-arch sm_90). The script
  encodes the four fixes discovered earlier: `--yes` (mamba), `set +u` (conda activate),
  `--install` (libcuopt into prefix so the Python wheel's `find_package(cuopt)` resolves),
  `get_test_data.sh` + `RAPIDS_DATASET_ROOT_DIR` (test data).
- **Results:** `EXIT_CODE=0`; `import cuopt` = **26.10.00**; **57 routing tests PASSED** (150.56 s).
  C++ build ~5 min on 44 cores.

## Phase 2 — Adopt & validate EV distance-breaks (PR #1196) ✅ DONE

- **What:** Adopt the EV charging / distance-breaks feature from PR #1196 onto current `main` and run
  its own test suites.
- **Why:** Feature 1 of the study. The professional move is to *adopt* the existing, tested PR
  (build + validate), not re-invent it — and to prove it still integrates with a fast-moving `main`.
- **How (exact):**
  1. `git fetch origin pull/1196/head:pr-1196`; branch `feature/ev-distance-breaks-pr1196`.
  2. `git merge --no-ff pr-1196` → conflict in **one** file only,
     `cpp/tests/routing/level1/l1_routing_test.cu`. Resolved: keep the `l1_distance_breaks`
     `INSTANTIATE_TEST_SUITE_P`; drop the re-added `CUOPT_TEST_PROGRAM_MAIN()` (main relocated it).
  3. Integration fix (Drift B): add `"add_distance_break"` to the `_SETTERS` tuple in
     `python/cuopt/cuopt/routing/_deferred.py` (main refactored `DataModel` to a deferred
     record-and-replay model after the PR was written).
  4. Integration fix (Drift A): `rm -rf python/cuopt/build python/libcuopt/build python/cuopt/_skbuild`
     so Cython regenerates (stale cache omitted `add_distance_break` from the compiled base class).
  5. Rebuild `./build.sh libcuopt cuopt --skip-grpc-build --install` (sm_90).
- **Results (H200):** merge conflicted in **1 file only** (as expected); both integration fixes
  applied. Rebuild `BUILD_EXIT=0` (95 targets). **C++ `distance_breaks` gtest: 5/5 PASS.**
  **Python `test_distance_breaks.py`: 29 passed / 1 failed** — the 1 = `test_solve_full_feature_api`
  (multi-cycle `d_min` soft-by-design; see report §4.6; `d_max`/range hard-enforced → not a safety
  bug). Committed locally: branch `feature/ev-distance-breaks-pr1196` `f2a75bdb` (30 files; **not
  pushed** to NVIDIA). Identical outcome to the earlier 2×A10 run → reproducible.

## Phase 1 — Time-of-day routing Tier A ✅ DONE

- **What:** Rush-hour-aware routing at the application layer (one cuOpt job per departure window).
- **Why:** Feature 3 "Tier A" — fastest customer value, zero solver change/risk.
- **How:** `phase1-time-of-day/time_of_day_tierA.py` — time-bucketed matrices per departure window.
- **Results (H200):** 9 locations / 8 orders / fleet 3; 5 departure windows all `status=0`.
  **Rush-hour penalty 2.21×** (evening-rush objective 57.04 vs. night 25.80); solve < 0.25 s/window.
  Full table + boundary note in `phase1-time-of-day/README.md`. Zero solver change.

## Phase 3 — Feature 2 skill-match via prizes ✅ DONE

- **What:** Validate NVIDIA's guidance that constraint honoring in partial solutions is achieved via
  prizes (not source changes).
- **Why:** Feature 2 — the code owner's authoritative resolution; no fork.
- **How:** re-ran `worklog/feature2-prizes/{f2_prizes.py,f2_skill.py}` on the H200.
- **Results (H200):** reproduced exactly. **No prizes → `status=1`** (solver over-packs to force a full
  assignment → constraint violated). **`prizes=1` → `status=0`**, clean **partial** solution honoring
  every constraint (capacity + skill), unservable order dropped. Skill/MISMATCH never violated.
  Confirms: Feature 2 = documented usage pattern, **no cuOpt source change**.

## Phase 4 — Comprehensive regression ✅ DONE (with enhancements)

- **What:** Full C++ (`ROUTING_UNIT_TEST`, `ROUTING_L1TEST`, `ROUTING_INTERNAL_TEST`) + full Python
  routing suite; then attribute every failure against **stock `main`** and fix what is genuinely ours.
- **Why:** Prove the EV adoption regresses nothing else — and don't hand-wave any red.
- **Results (H200):** C++ `ROUTING_UNIT_TEST` 53/53, `ROUTING_INTERNAL_TEST` 52/52. Initial Python
  84/3. **Attributed by rebuilding stock `main` f3ebc673:** `l1_homberger` = pre-existing SetUp crash
  (fails on stock too); `test_serialize` = our incomplete integration; `test_range` = the PR's own
  off-by-one correctness fix vs a stale test; `test_solve_full_feature_api` = documented soft-by-design.
  **Enhancements applied** (Python glue/test only — no solver source): `_distance_break` serialize
  handler + `_SETTERS` registration + `test_range` alignment. **Re-run: Python 86/1** (only the
  documented multi-cycle item). Full detail in `REGRESSION-ANALYSIS-AND-ENHANCEMENTS.md`.

## Phase 5 — Consolidate deliverable ✅ DONE

- **What:** Fold all measured results into the study docs + a final shareable summary; update memory.
- **Results:** worklog updated (`PHASE-EXECUTION-LOG.md`, `REGRESSION-ANALYSIS-AND-ENHANCEMENTS.md`,
  `BUILD-VALIDATION-REPORT.md`, `FILES-CHANGED.md`, `COMMANDS-RUNBOOK.md`, `feature2-prizes/`,
  `phase1-time-of-day/`). Feature 4 (sparse Option A) noted as the remaining stretch item.

---

## Final scorecard (all phases)

| Feature / phase | Verdict | Evidence |
|-----------------|---------|----------|
| Build from source | ✅ green | 57 routing tests pass (H200) |
| **F1 — EV charging (PR #1196)** | ✅ **adopted** | merges clean (1-file conflict); C++ 5/5; Python 29/30 (+2 integration enhancements); 1 documented multi-cycle semantics question |
| **F3 — Time-of-day (Tier A)** | ✅ **works** | 2.21× rush-hour penalty across 5 windows; zero solver change |
| **F2 — Skill-match** | ✅ **solved via prizes** | prizes=1 → clean partial, no violation (NVIDIA guidance); no source change |
| Regression | ✅ **no EV regression** | C++ 105 pass; Python 86/1; every failure attributed vs stock main |
| F4 — Sparse (Option A) | ⏳ stretch | server-side matrix generation — not yet built |

**Overall:** every studied feature is achievable **without modifying the cuOpt solver core** — matching
the study's thesis and the code owner's guidance.
