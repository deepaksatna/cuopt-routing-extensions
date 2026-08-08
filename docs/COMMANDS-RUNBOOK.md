# cuOpt Build + PR #1196 — Exact Commands Runbook

Copy-pasteable reproduction of the work described in `BUILD-VALIDATION-REPORT.md`.
Target: a Linux GPU box, compute capability ≥ 7.0, CUDA 13 driver (≥ 560; we used driver 595),
≥ 120 GB free disk. All commands are as-run on the 2×A10 GPU box (`user@…`, Linux).

Conventions:
- `REPO=~/cuopt-dev/cuopt`  ·  conda env at `$REPO/.cuopt_env`
- Build single-arch for speed: `CUDAARCHS=86` (A10 = sm_86; use your GPU's arch)
- Parallelism: `PARALLEL_LEVEL=32` (60-core box; lower it on smaller boxes)

---

## 0. (cloud VMs) Grow the boot volume if the disk is < 120 GB free

```bash
# cloud-provider specific; generic form:
sudo growpart /dev/DISK 1                       # grow the partition
sudo lvextend -r -l +100%FREE /dev/mapper/root  # extend LVM + filesystem
df -Ph /                                         # verify free space
```

## 1. Prereqs

```bash
sudo dnf install -y git tmux curl      # RPM-based distro; use apt on Debian/Ubuntu
```

## 2. Phase 0 — build from source (via the bootstrap script)

The maintained path is the project's bootstrap script (idempotent). It installs miniforge, clones
`main`, creates the CUDA-13.3 conda env, builds single-arch, and runs the routing tests.

```bash
# from the CoE workspace, copy the script to the box, then:
JOBS=32 MERGE_PR=0 RUN_TESTS=1 bash phase0_bootstrap.sh 2>&1 | tee phase0.log
```

The script already encodes the four Phase-0 fixes below. If building **by hand** instead, they are:

```bash
# (a) miniforge + env — note --yes so mamba doesn't block on [Y/n]
mamba env create --yes -p "$REPO/.cuopt_env" \
  --file "$REPO/conda/environments/all_cuda-133_arch-$(uname -m).yaml"

# (b) activate under set -u safely (conda cuda-nvcc activate.d references unset vars)
source ~/miniforge3/etc/profile.d/conda.sh
set +u; conda activate "$REPO/.cuopt_env"; set -u

# (c) BUILD WITH --install  (installs libcuopt.so + cuopt-config.cmake into the conda prefix;
#     WITHOUT it the Python wheel fails: find_package(cuopt) can't resolve cuopt::cuopt)
cd "$REPO"
CUDAARCHS=86 PARALLEL_LEVEL=32 ./build.sh libcuopt cuopt --skip-grpc-build --install -v

# (d) fetch datasets + point tests at them (else FileNotFoundError on solomon/In/r107.txt)
bash datasets/get_test_data.sh
export RAPIDS_DATASET_ROOT_DIR="$REPO/datasets"
```

### Verify Phase 0

```bash
python -c "import cuopt; print(cuopt.__version__)"          # -> 26.10.00
python -c "import cuopt.routing; from cuopt.routing import DataModel, SolverSettings, Solve; print('API OK')"
python -m pytest -q python/cuopt/cuopt/tests/routing --disable-warnings
# expected: 57 passed
```

## 3. Phase 2 — adopt PR #1196 (EV distance-breaks)

### 3.1 Fetch + test the merge (main moved 1000+ commits; use the merge-base for the real diff)

```bash
cd "$REPO"
git fetch origin pull/1196/head:pr-1196
git diff "$(git merge-base HEAD pr-1196)"..pr-1196 --stat     # -> 29 files, 1882 insertions

git config user.email dev@cuopt.local; git config user.name cuopt-dev
git merge --no-commit --no-ff pr-1196            # conflicts in ONE file only
git diff --name-only --diff-filter=U             # -> cpp/tests/routing/level1/l1_routing_test.cu
```

### 3.2 Resolve the single test-file conflict

Keep the PR's `l1_distance_breaks` instantiation; **delete** the re-added `CUOPT_TEST_PROGRAM_MAIN()`
line (upstream relocated the test-main globally). Then:

```bash
git add cpp/tests/routing/level1/l1_routing_test.cu
git commit --no-edit                             # merge commit
```

### 3.3 Rebuild with the EV feature

```bash
CUDAARCHS=86 PARALLEL_LEVEL=32 ./build.sh libcuopt cuopt --skip-grpc-build --install -v
```

### 3.4 Two required Python-integration fixes (PR predates a `main` DataModel refactor)

```bash
# Drift A: stale Cython cache -> super().add_distance_break missing. Clear caches + rebuild python.
rm -rf python/cuopt/build python/libcuopt/build python/cuopt/_skbuild
CUDAARCHS=86 PARALLEL_LEVEL=32 ./build.sh cuopt --skip-grpc-build --install -v

# Drift B: add the new setter to the deferred record-and-replay list.
#   Edit python/cuopt/cuopt/routing/_deferred.py : add "add_distance_break" to the _SETTERS tuple
#   (next to "add_vehicle_break"). Pure-python — reinstall or sync into site-packages.
```

### 3.5 Verify EV feature

```bash
export RAPIDS_DATASET_ROOT_DIR="$REPO/datasets"
python -m pytest -q python/cuopt/cuopt/tests/routing/test_distance_breaks.py --disable-warnings
# expected: 29 passed, 1 failed
# the 1 failure is test_solve_full_feature_api (multi-cycle n_cycles=2) — see report section 4.5
```

### 3.6 Reproduce the one open failure in isolation (for upstream)

```bash
python -m pytest -q \
  "python/cuopt/cuopt/tests/routing/test_distance_breaks.py::test_solve_full_feature_api" \
  --disable-warnings
# deterministic: "vehicle 1 cycle 1 break at cumulative 10.0 outside window [30.0, 40.0]"
```

---

## Appendix — session facts

| | |
|---|---|
| cuOpt | `main` 26.10.00, build HEAD `f3ebc673`, merge `448fb194`, PR merge-base `7b6e43db` |
| Toolchain | CUDA 13.3.73, GCC 14.4.0, Python 3.14.6, CMake 4.4 |
| GPU / driver | 2× NVIDIA A10, driver 595.71.05, sm_86 |
| C++ build time | ~4m35s single-arch, 32 jobs |
| Baseline routing tests | 57 passed (151 s) |
| EV (`test_distance_breaks.py`) | 29 passed / 1 failed |
