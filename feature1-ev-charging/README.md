# Feature 1 — EV Charging Stops (distance-windowed mandatory recharge)

**Status: ✅ validated.** The feature is NVIDIA/cuOpt **[PR #1196](https://github.com/NVIDIA/cuopt/pull/1196)**
("routing: add distance breaks"). The professional move — per the study — is to *adopt* the existing,
tested PR, not re-invent it. This folder documents adopting it onto current `main` and the enhancements
needed to integrate with main's newer architecture.

## What we did

1. **Merge PR #1196 onto `main` (26.10.00).** Despite `main` advancing 1000+ commits past the PR's
   branch point, the merge conflicts in **one test file only** (`l1_routing_test.cu`); all 28
   solver-core files merge clean.
2. **Rebuild + run the PR's own suites.** C++ `distance_breaks` **5/5 pass**; Python
   `test_distance_breaks.py` **29/30**.
3. **Three integration enhancements** (Python glue/test — no solver source), because the PR predates
   main's store-then-build (deferred) `DataModel` refactor:
   - `_distance_break` **serialize handler** (`_serialize.py`)
   - `add_distance_break` **registered in `_SETTERS`** (`_deferred.py`)
   - **stale range-validation test aligned** with the PR's own off-by-one correctness fix
4. After enhancements: full Python routing suite **86/1** (the 1 = the documented multi-cycle item).

The diffs are in `../enhancements/integration-fixes.patch`. Full narrative in
`../docs/BUILD-VALIDATION-REPORT.md` and `../docs/REGRESSION-ANALYSIS-AND-ENHANCEMENTS.md`.

## One open question for the maintainers

`test_solve_full_feature_api` (multi-cycle, `n_cycles=2`) fails deterministically: the second cycle's
break lands outside its window, because the distance-window lower bound `d_min` is **soft** (mirrors the
time-window "arriving early is free" design). The range-critical **upper bound `d_max` is
hard-enforced** (→ infeasible), so this is **not** a safety bug — an EV cannot be routed past its range.
Should `d_min` be hard for *distance* breaks? See `../docs/BUILD-VALIDATION-REPORT.md` §4.6.
