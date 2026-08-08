# Validated branch — bundle & patch

Two ways to obtain the exact validated state (main `26.10.00` + PR #1196 + our enhancements):

## Option 1 — import the complete branch from the bundle

`cuopt-ev-enhancements.bundle` contains the validated branch
`feature/ev-distance-breaks-pr1196`. It is incremental on upstream base
`f3ebc673` (already in cuOpt history), so it stays tiny (56 KB).

```bash
git clone https://github.com/NVIDIA/cuopt.git
cd cuopt
git bundle verify /path/to/cuopt-ev-enhancements.bundle
git fetch /path/to/cuopt-ev-enhancements.bundle \
    feature/ev-distance-breaks-pr1196:ev-validated
git checkout ev-validated
```

This gives you: PR #1196 merged onto `main`, the 1-file conflict resolved, and our integration
enhancements — the exact tree that produced the reported test results.

## Option 2 — apply only our enhancements

`my-enhancements.patch` is our net contribution (deferred `_SETTERS` registration + `_serialize`
`_distance_break` handler + stale-test alignment) on top of a PR-#1196 merge.

```bash
# after merging NVIDIA/cuopt PR #1196 onto main:
git am /path/to/my-enhancements.patch
# or, non-committing:
git apply ../enhancements/integration-fixes.patch
```

## Attribution

PR #1196's own commits are **not** re-published here — they live in
https://github.com/NVIDIA/cuopt/pull/1196 (credit to the original author). The bundle references them
by object id; nothing in this repo claims their authorship. See `../NOTICE`.
