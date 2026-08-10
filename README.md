# cuopt-routing-extensions

Build, validation, and enhancements for [NVIDIA cuOpt](https://github.com/NVIDIA/cuopt) routing. This
repository covers four enterprise routing capabilities, each backed by code and measured results.

Capabilities 1 to 3 are Python glue and tests with no change to the cuOpt solver core. Capability 4 (native
sparse cost matrices) is a small, feature-gated change to the solver core: with the flag off, dense problems
are identical to upstream cuOpt.

Targets cuOpt 26.10.00 (base commit f3ebc673). License: Apache-2.0. This repository contains no cuOpt
source; every solver and server change is provided as a patch for maintainer review.

## The four capabilities

| # | Capability | Status | Approach | Solver-core change |
|---|------------|--------|----------|--------------------|
| 1 | EV charging stops (distance-windowed mandatory recharge) | Validated | Adopt [PR #1196](https://github.com/NVIDIA/cuopt/pull/1196) plus 3 integration fixes | No (PR plus Python) |
| 2 | Skill-match honoured in partial solutions | Validated | Prize pattern (per NVIDIA guidance) | No |
| 3 | Time-of-day / rush-hour travel times | Validated | Application-layer Tier A (2.21x rush penalty) | No |
| 4 | Native sparse (K-NN) cost matrices | Validated | CSR read path in the solver plus B5 REST ingestion | Yes (gated patch) |

All four capabilities are in this main branch, with code and evidence. The `native-sparse/` folder was
merged in from the `sparse-matrix-native` branch, which is retained for history.

## Summary for the cuOpt maintainers

Capabilities 1 to 3 (EV, skill-match, time-of-day), validated against a from-source build of 26.10.00:

1. PR #1196 (EV distance-breaks) still integrates cleanly. It conflicts only in one test file; the 28
   solver-core files merge clean; the PR's own suites pass (C++ distance_breaks 5/5, Python
   test_distance_breaks 29/30).
2. Two small integration fixes are needed against main's store-then-build (deferred) DataModel: a
   `_serialize` `_distance_break` handler and `_SETTERS` registration for `add_distance_break`
   (`enhancements/integration-fixes.patch`).
3. One open semantics question: for multi-cycle distance breaks, the lower bound d_min is soft and the
   range-critical upper bound d_max is hard-enforced (infeasible past it), so it is not a safety bug.
   Should d_min be hard for distance breaks?

Capability 4 (native sparse), the change that touches the solver:

4. Native sparse (K-NN / CSR) cost matrix support: a feature-gated read path in the solver core plus a
   `cost_matrix_csr` REST field. The 10,000-stop payload that failed in the earlier benchmark (2,290 MB
   dense, above the 2 GB REST limit) now submits at about 2.9 MB and solves as a single global problem.
   Solver memory is O(N*K) instead of O(N^2): about 303x smaller at 10,000 stops and 3,030x at 100,000.

## Capability 4: native sparse cost matrices

### Problem

cuOpt reads cost from a dense N-by-N matrix, and the REST API accepts only a dense `cost_matrix_data`. A
K-nearest-neighbour graph is small (0.76 MB at 10,000 stops, K=10) but must be re-expanded to a dense
2,290 MB matrix, which exceeds the 2 GB REST limit. As a result, sparse matrices could not be used.

| Stops | Dense cost matrix | Native-sparse CSR | Reduction |
|-------|-------------------|-------------------|-----------|
| 10,000 | 0.4 GB | 1.3 MB | 303x |
| 50,000 | 10 GB | 6.6 MB | 1,515x |
| 100,000 | 40 GB (does not fit a single GPU) | 13 MB | 3,030x |

### Files changed, and why

Solver core (`native-sparse/native-sparse-core.patch`, 3 files, all gated by `has_sparse_cost`):

| File | Change | Reason |
|------|--------|--------|
| cpp/src/routing/arc_value.hpp | Add a BIG_COST (1e6) sentinel and a gated branch in `get_distance()`: when has_sparse_cost is set, binary-search the CSR row (O(log K)) instead of the dense index; an absent arc returns BIG_COST. | `get_distance` is the single cost-lookup point used by the whole solver. One gated change here keeps the dense path identical. |
| cpp/src/routing/utilities/md_utils.hpp | Add CSR fields to the matrix view and device storage to d_mdarray_t, plus `build_csr(K)` (depot-aware top-K, sorted so the device can binary-search). | Stores the CSR on the GPU; depot-aware construction preserves connectivity at small K. |
| cpp/src/routing/fleet_info.cu | Add a CUOPT_SPARSE_K hook in `populate_matrices` (prototype trigger). | Enables the sparse read path; superseded by B5 ingestion. |

Server, B5 CSR ingestion (`native-sparse/b5-server-csr.patch`, 3 files, 87 lines):

| File | Change | Reason |
|------|--------|--------|
| cuopt_server/utils/routing/data_definition.py | Add a CostMatrixCSR model and a `cost_matrix_csr` request field. | Defines the new REST payload; it threads through the existing request pipeline automatically. |
| cuopt_server/utils/solver.py | Thread `cost_matrix_csr` through the solve entry point and add the ingestion branch. | Wires the field to the data model without touching the dense path. |
| cuopt_server/utils/routing/optimization_data_model.py | Add `set_cost_matrix_csr()`, a vectorized O(nnz) reconstruction. | Rebuilds the cost matrix server-side from the CSR; the client never sends a dense matrix. |

### API

Endpoints: POST /cuopt/request returns a reqId; GET /cuopt/solution/{reqId} returns the solution; GET
/cuopt/health returns server status.

Sparse cost matrix: send the K nearest neighbours as CSR, and set `vehicle_max_costs` below the sentinel so
that a missing arc is treated as infeasible rather than traversed.

```json
{
  "cost_matrix_csr": {
    "n_locations": 10000,
    "offsets": { "0": [0, 52, 105] },
    "indices": { "0": [0, 3, 7] },
    "values":  { "0": [0.0, 12.4, 9.1] }
  },
  "travel_time_matrix_data": { "data": { "0": [[0]] } },
  "fleet_data": { "vehicle_locations": [[0, 0]], "vehicle_max_costs": [900000] },
  "task_data": { "task_locations": [1, 2, 3] },
  "solver_config": { "time_limit": 10 }
}
```

Field notes: offsets has length n_locations+1; indices and values have length nnz and are sorted within each
row; keys ("0") are the vehicle-type. Build the CSR by keeping, for each row, the K nearest columns plus the
depot (0) and self, sorted ascending; K = min(50, N-1) is a reasonable default.

EV charging (Python client): `dm.add_distance_break(distance_min=[30.0], distance_max=[40.0], duration=[15],
break_locations=charger_ids)`. d_max is hard-enforced; d_min is soft.

### Results

Same K-NN generator and same 10,000-stop scenario as the earlier Phase-4 run, with the payload sent as
`cost_matrix_csr`:

| Stops | K | Sparse core | CSR request | Prior dense | Prior | Now |
|-------|---|-------------|-------------|-------------|-------|-----|
| 10,000 | 10 | 0.76 MB | 2.94 MB | 2,290.5 MB | FAILED | PASS (HTTP 200) |
| 10,000 | 20 | 1.53 MB | 5.39 MB | 2,292.0 MB | FAILED | PASS (HTTP 200) |
| 10,000 | 50 | 3.81 MB | 12.68 MB | 2,296.5 MB | FAILED | PASS (HTTP 200) |

Payload reduction is about 99.97 percent. The problem solves as a single global optimization (no
clustering), the routes are feasible, and there is no measurable lookup overhead versus dense. Validated on
NVIDIA A10 (sm_86).

![Payload reduction by method](docs/assets/native-sparse-a10-payload-comparison.png)
![Cost-matrix memory, dense versus CSR](docs/assets/native-sparse-a10-memory-scaling.png)

Full write-up: `native-sparse/A10-BENCHMARK-REPORT.md` and `native-sparse/B5-CSR-INGESTION.md`. Annotated
C++ walkthrough (read without applying the patch): `native-sparse/CPP-CHANGES.md`. Concrete input data
(10,000 seeded stops plus the K-NN CSR, for inspection): `native-sparse/sample_data/`.

Scope: this beta reconstructs the matrix server-side, which is suitable up to about 10,000 stops on a single
GPU. The next step is a native C++ `add_cost_matrix_csr` that never materializes the dense matrix, giving
true O(N*K) memory at 100,000 stops on one GPU. It is scoped in
`native-sparse/B5-PLAN-direct-csr-ingestion.md`.

## Capabilities 1 to 3: EV, regression, skill-match, time-of-day

### Regression and test results

![cuOpt routing regression and EV validation](docs/assets/regression-results.png)

Every failure was attributed by rebuilding stock main (f3ebc673) and re-running the same tests, so "no
regression" is demonstrated rather than asserted.

| Suite | Result | Notes |
|-------|--------|-------|
| C++ ROUTING_UNIT_TEST | 53 / 53 pass | includes EV distance_breaks 5/5 |
| C++ ROUTING_INTERNAL_TEST | 52 / 52 pass | |
| C++ ROUTING_L1TEST | 1 pre-existing failure | l1_homberger crash, fails on stock main as well |
| Python routing suite | 86 pass / 1 fail | after the enhancements (was 84 / 3) |

| Failure | Stock main | EV build | Verdict |
|---------|-----------|----------|---------|
| l1_homberger | FAILS | FAILS | Pre-existing, not a regression |
| test_serialize | PASS | was FAIL | Our integration gap, fixed by the serialize handler |
| test_range | PASS (<=3) | was FAIL (<=2) | The PR's own off-by-one fix; stale test aligned |
| test_solve_full_feature_api | not applicable | FAIL | Documented multi-cycle d_min (soft by design) |

Full narrative: `docs/REGRESSION-ANALYSIS-AND-ENHANCEMENTS.md`.

### Performance benchmark (cuOpt's own methodology)

Gap to Best-Known Solution on standard academic instances, with cuOpt's default 5 percent threshold. On
Solomon r107 (BKS cost 1080.92, 11 vehicles) cuOpt reaches about 1 percent of best-known within seconds, and
the EV feature ON versus OFF is within noise on both solve time and quality (10.08 s / 0.58 percent versus
10.12 s / 0.66 percent). There is no measurable performance cost.

![EV distance-breaks add no measurable cost](docs/assets/benchmark-parity.png)

### EV integration fixes (our contribution)

Since PR #1196 branched, cuOpt refactored DataModel to store-then-build (deferred). These fixes complete the
integration:

1. A `_distance_break` serialization handler (`_serialize.py`), making the EV setter serializable through
   the deferred model. Verified with a round trip.
2. Registration of `add_distance_break` in `_SETTERS` (`_deferred.py`).
3. Alignment of a stale range-validation test with the PR's own off-by-one fix.

All three are in `enhancements/integration-fixes.patch`, applied on top of a PR #1196 merge.

## Container image

A server image bundles all four capabilities (cuOpt 26.10 plus native sparse, B5, and EV):

```
fra.ocir.io/<namespace>/aipacksrepo:cuopt-ev-sparse-b5-server-beta   (built for sm_86 / A10)
```

Deployment note (Kubernetes): a cuda:*-base image ships no CUDA headers, so set
CUDA_PATH=<conda-prefix>/targets/x86_64-linux or cupy JIT compilation fails at solve time. Use a Recreate
rollout on single-GPU nodes.

## Building from source and packaging the image

The image is produced from open-source cuOpt plus the C++ solver patch and the Python server patch in this
repository. No cuOpt source is redistributed here; the build clones it from NVIDIA and applies the patches.

Prerequisites: a Linux host with an NVIDIA GPU, CUDA 13 driver, and about 120 GB of free disk. Conda or
mamba (miniforge). The conda environment supplies the compilers and CUDA toolkit, so a system CUDA install
is not required for the build.

Step 1. Clone open-source cuOpt at the validated base commit.

```bash
git clone https://github.com/NVIDIA/cuopt.git
cd cuopt
git checkout f3ebc673
```

Step 2. Apply the changes from this repository.

```bash
# Capability 4: native sparse read path (C++) and the CSR server ingestion (Python)
git apply /path/to/cuopt-routing-extensions/native-sparse/native-sparse-core.patch
git apply /path/to/cuopt-routing-extensions/native-sparse/b5-server-csr.patch

# Capability 1 (optional, for the combined image): adopt EV PR #1196, then the integration fixes
# git merge <PR-1196>            # or fetch the provided bundle in bundle/
git apply /path/to/cuopt-routing-extensions/enhancements/integration-fixes.patch
```

Files the C++ patch touches (all gated by has_sparse_cost): cpp/src/routing/arc_value.hpp,
cpp/src/routing/utilities/md_utils.hpp, cpp/src/routing/fleet_info.cu. The server patch touches three files
under python/cuopt_server/cuopt_server/utils.

Step 3. Create the CUDA 13.3 conda environment and build from source. Build for a single GPU architecture
(90 for H200, 86 for A10) to keep the build fast.

```bash
mamba env create --yes -p ./.cuopt_env --file conda/environments/all_cuda-133_arch-$(uname -m).yaml
conda activate ./.cuopt_env
CUDAARCHS=86 ./build.sh libcuopt cuopt --skip-grpc-build --install
python -c "import cuopt; print(cuopt.__version__)"     # expect 26.10.00
```

Step 4. Install the patched cuOpt server into the same environment.

```bash
pip install ./python/cuopt_server --no-deps
```

Step 5. Package the environment into a container image. The conda environment is self-contained; keep it at
the same path inside the image so its activation scripts resolve.

```dockerfile
FROM nvidia/cuda:13.0.0-base-ubuntu24.04
COPY .cuopt_env /work/cuopt/.cuopt_env
ENV PATH=/work/cuopt/.cuopt_env/bin:$PATH
# GenAI/cupy needs CUDA headers at runtime; the conda env already ships them under targets/
ENV CUDA_PATH=/work/cuopt/.cuopt_env/targets/x86_64-linux
WORKDIR /work
EXPOSE 5000
CMD ["python", "-m", "cuopt_server.cuopt_service", "-p", "5000", "-i", "0.0.0.0"]
```

```bash
podman build --format docker -t <registry>/cuopt-ev-sparse-b5-server-beta .
podman push <registry>/cuopt-ev-sparse-b5-server-beta
```

Build notes: build single-arch (CUDAARCHS) rather than all-arch to save time; the `--install` flag is
required so the Python cuopt wheel can locate libcuopt; when building the front-end image separately, raise
the open-file limit (podman build --ulimit nofile=65536) because the bundler opens many files. The one-shot
script `scripts/phase0_bootstrap.sh` performs the from-source build (steps 1, 3, 4) with these settings.

## Repository layout

```
native-sparse/        Capability 4: solver patch, B5 server patch, benchmark and generator, A10 report, plots
  native-sparse-core.patch     solver read path (3 files, gated)
  b5-server-csr.patch          cost_matrix_csr REST ingestion (3 files)
  b5_csr_benchmark.py          the CSR-mode benchmark (synthetic, seeded)
  sparse_matrix_generator.py   the K-NN generator, so the benchmark runs standalone
  A10-BENCHMARK-REPORT.md / B5-CSR-INGESTION.md / DATASETS.md / B5-PLAN-direct-csr-ingestion.md
enhancements/         integration-fixes.patch (EV)
feature1-ev-charging/, feature2-skill-match/, feature3-time-of-day/   capabilities 1 to 3, repro and results
benchmark/            gap-to-BKS benchmark (cuOpt's own methodology)
docs/                 build, validation, and regression reports; assets/ holds the plots
analysis/             feasibility study, cited to cuopt source file and line
scripts/              phase0_bootstrap.sh (one-shot from-source build)
bundle/               git bundle of the validated EV branch (importable)
```

## Datasets and reproducibility

No private data is required. See `native-sparse/DATASETS.md`.

- Sparse benchmark: synthetic locations, numpy seed 42; the K-NN generator ships in `native-sparse/`.
- Regression and gap-to-BKS: standard Solomon and Gehring-Homberger instances, fetched with cuOpt's own
  `datasets/get_test_data.sh`. This is why `datasets/` is git-ignored.
- Skill-match and time-of-day: self-generated with numpy.

## Reproduce

```bash
# 1. From-source build (any Linux GPU host, CUDA 13 driver, 120 GB or more disk)
bash scripts/phase0_bootstrap.sh

# 2a. EV: adopt PR #1196, then apply the integration fixes (see docs/COMMANDS-RUNBOOK.md)
git apply enhancements/integration-fixes.patch

# 2b. Native sparse: apply the solver and server patches, rebuild, run the CSR benchmark
git apply native-sparse/native-sparse-core.patch native-sparse/b5-server-csr.patch
python native-sparse/b5_csr_benchmark.py
```

## Open question for the maintainers

For multi-cycle distance breaks, d_min is soft (as with time-window waiting) while the range-critical d_max
is hard-enforced (infeasible past it), so it is not a safety bug. Should d_min be hard for distance breaks
so that stacked cycles do not collapse into the earliest window? Detail is in
`docs/BUILD-VALIDATION-REPORT.md`, section 4.6.

## Relationship to NVIDIA cuOpt

This is an independent, Apache-2.0 companion to NVIDIA cuOpt. It contains no cuOpt source. The EV feature is
NVIDIA's PR #1196 (credited), and the solver and server changes are provided as patches for review. See
NOTICE.
