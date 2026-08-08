# Comprehensive Regression Analysis + Upstream Enhancements (EV / PR #1196)

Full accounting of the H200 comprehensive regression, **per-failure attribution proven against stock
`main`**, and the **upstream-quality enhancements** that complete PR #1196's integration with current
cuOpt `main`. Written so the cuOpt maintainers can see exactly what was found, how it was attributed,
and what was improved — with everything reproducible.

## 1. Comprehensive regression (H200, cuOpt 26.10.00, EV build)

| Suite | Result |
|-------|--------|
| C++ `ROUTING_UNIT_TEST` | ✅ 53 passed |
| C++ `ROUTING_INTERNAL_TEST` | ✅ 52 passed |
| C++ `ROUTING_L1TEST` | ⚠️ 1 failed (`l1_homberger`) |
| Python routing suite | 84 passed / **3 failed** |

Raw failures: `l1_homberger` (C++), and Python `test_solve_full_feature_api`, `test_serialize::
test_every_setter_is_exportable`, `test_warnings_exceptions::test_range`.

## 2. Attribution — proven by rebuilding STOCK `main` (f3ebc673) and running the same tests

| Failure | Stock `main` | EV build | Verdict |
|---------|--------------|----------|---------|
| `l1_homberger` | **FAILS** (identical `std::vector larger than max_size()` crash in `SetUp()`) | FAILS | **PRE-EXISTING** — a dataset-parse crash in the regression harness *before any solve*. Independent of EV (gated). **Not a regression.** |
| `test_serialize::test_every_setter_is_exportable` | PASSES | FAILS | **EV-integration gap** — our `_SETTERS` registration of `add_distance_break` was incomplete (needs an export handler). **Fixed (Enhancement 1).** |
| `test_warnings_exceptions::test_range` | PASSES (asserts `≤ 3`) | FAILS (runtime says `≤ 2`) | **PR correctness fix** — PR #1196 fixes an off-by-one in the location-range validation; the stale test still encoded the buggy bound. **Test updated (Enhancement 3).** Not a regression — the EV build is *more correct*. |
| `test_solve_full_feature_api` | n/a (test is PR's) | FAILS | **Known, documented** — multi-cycle `d_min` soft-by-design (time-window mirror); `d_max`/range hard-enforced → not a safety bug. Upstream semantics question (report §4.6). |

**Bottom line:** zero of the four are a functional or performance regression introduced by adopting the
EV feature. One is pre-existing infra (l1_homberger), one is a correctness *improvement* by the PR
(test_range), one was our own incomplete integration (now fixed), and one is a documented design
question for multi-cycle.

## 3. Upstream-quality enhancements (complete the PR's integration with refactored `main`)

Since PR #1196 branched, `main` refactored `DataModel` to a **store-then-build / deferred** model
(mutating setters are recorded in `_SETTERS` and replayed at solve time; each must also have a
**serialization handler** in `_serialize._HANDLERS`). The PR predates this, so the distance-break
setter was not wired into the new machinery. These enhancements finish that wiring cleanly.

### Enhancement 1 — `_distance_break` serialization handler *(NEW, upstream-worthy)*
`python/cuopt/cuopt/routing/_serialize.py`: added a `_distance_break(p, args)` handler (mirrors the
existing `_vehicle_break`, keyed by distance instead of time), registered it as
`"add_distance_break": _distance_break` in `_HANDLERS`, and added `"distance_breaks"` to
`_LIST_FIELDS`. This makes the EV feature **serializable** through the deferred model — closing the
gap the `test_every_setter_is_exportable` guard flagged ("fail loudly if a new setter has no export
mapping"). The test now passes because the export path is genuinely implemented, not bypassed.

### Enhancement 2 — register `add_distance_break` in `_SETTERS`
`python/cuopt/cuopt/routing/_deferred.py`: added `"add_distance_break"` so the deferred model records
and replays it. (Without this, `super().add_distance_break()` raised `AttributeError`.) Together with
Enhancement 1, the EV feature is now a first-class citizen of main's deferred architecture.

### Enhancement 3 — align the stale range-validation test with the PR's own bug fix
PR #1196 corrects an **off-by-one** in location-range validation:
`validate_range(..., 0, get_num_locations())` → `get_num_locations() - 1` (a 3-location model must
reject location index 3; valid indices are 0–2). This is applied in 4 places in the merged
`vehicle_routing.py`. The pre-existing `test_range` still asserted the buggy `≤ 3`; updated to `≤ 2`
to match the corrected, more-correct behavior. **This is the PR improving cuOpt correctness** — worth
calling out to the maintainers as a genuine fix, not just a test tweak.

All three are **Python glue / test** changes — **no cuOpt solver-core source was modified** (honoring
the code owner's guidance).

## 4. Validation after enhancements (H200, measured)

- `test_serialize.py`: **4/4 pass** (incl. round-trip — confirms the `_distance_break` handler is
  *correct*, not merely present).
- `test_warnings_exceptions.py::test_range`: **pass** (now expects the corrected `≤ 2`).
- **Full Python routing suite: 86 passed / 1 failed** — the only failure is the documented
  `test_solve_full_feature_api` (multi-cycle `d_min` soft-by-design). Before the enhancements it was
  84 / 3.
- C++ unchanged by these Python-only enhancements: `ROUTING_UNIT_TEST` 53/53, `ROUTING_INTERNAL_TEST`
  52/52; `l1_homberger` remains the **pre-existing** C++ infra failure (fails on stock `main` too).
- Committed on `feature/ev-distance-breaks-pr1196`: `f2a75bdb` (adopt PR + integration fixes) then
  `59432cf9` (serialize handler + test alignment). **Not pushed.**

**Net regression posture:** Python routing is green except the one documented upstream semantics
question; C++ has one pre-existing infra failure unrelated to EV. No functional or performance
regression was introduced by adopting the EV feature.

## 5. What to hand NVIDIA

1. PR #1196 **builds and adopts cleanly** onto current `main` (1-file test conflict; C++ core merges clean).
2. **Two integration enhancements** it needs against refactored `main`: deferred `_SETTERS` registration
   + `_serialize` handler for `add_distance_break` (both provided here, upstream-ready).
3. A **correctness win** the PR already contains (off-by-one range fix) — plus the one **stale test** it
   should update (`test_range`).
4. One **open semantics question**: multi-cycle distance-break lower bound (`d_min`) is soft (mirrors
   time windows). `d_max`/range is hard-enforced. Should `d_min` be hard for distance breaks?
5. One **pre-existing, unrelated** harness bug: `l1_homberger` `SetUp()` vector-size crash (fails on
   stock `main` too) — flagged for the maintainers as a separate issue.
