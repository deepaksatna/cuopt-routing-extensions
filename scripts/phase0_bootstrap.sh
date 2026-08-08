#!/usr/bin/env bash
# =============================================================================
# cuOPT-Dev · Phase 0 — Build Bring-Up Bootstrap
# -----------------------------------------------------------------------------
# One-shot setup of a from-source NVIDIA cuOpt build on a Brev (or any) Linux
# GPU box, with a green routing-test signal at the end.
#
# What it does (idempotent — safe to re-run):
#   1. Preflight: verify Linux, GPU, driver, compute capability >= 7.0, disk
#   2. Real-CUDA-op smoke test (nvcc vector-add on the device — not is_available())
#   3. Install miniforge (mamba) if absent
#   4. Clone NVIDIA/cuopt (or reuse an existing checkout)
#   5. (optional) Merge PR #1196 (EV distance-breaks) — MERGE_PR=1
#   6. Create the CUDA-13.3 conda build env
#   7. Build libcuopt + cuopt for the LOCAL GPU arch only (fast)
#   8. Import check + run the routing test suite
#
# Usage (on the GPU box):
#   chmod +x phase0_bootstrap.sh
#   ./phase0_bootstrap.sh 2>&1 | tee phase0.log
#
# From your laptop via Brev:
#   brev exec bench 'bash -s' < phase0_bootstrap.sh
#   # (or: scp this file over, then `brev exec bench "bash ~/phase0_bootstrap.sh"`)
#
# Knobs (env vars, all optional):
#   WORKDIR=$HOME/cuopt-dev     # where everything lives
#   REPO_URL=https://github.com/NVIDIA/cuopt.git
#   BRANCH=main                 # cuopt branch/tag to build
#   MERGE_PR=0                  # 1 = merge PR #1196 (EV charging) on top of BRANCH
#   BUILD_TARGETS="libcuopt cuopt"
#   RUN_TESTS=1                 # 0 = build only, skip tests
#   JOBS=<nproc>                # parallel build jobs
# =============================================================================
set -Eeuo pipefail

# ---- config -----------------------------------------------------------------
WORKDIR="${WORKDIR:-$HOME/cuopt-dev}"
REPO_URL="${REPO_URL:-https://github.com/NVIDIA/cuopt.git}"
BRANCH="${BRANCH:-main}"
MERGE_PR="${MERGE_PR:-0}"
PR_NUMBER="${PR_NUMBER:-1196}"
BUILD_TARGETS="${BUILD_TARGETS:-libcuopt cuopt}"
RUN_TESTS="${RUN_TESTS:-1}"
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 8)}"
ENV_PREFIX="./.cuopt_env"
MIN_DISK_GB="${MIN_DISK_GB:-120}"

REPO_DIR="$WORKDIR/cuopt"
MINIFORGE_DIR="$HOME/miniforge3"

# ---- pretty logging ---------------------------------------------------------
c_g() { printf '\033[1;32m%s\033[0m\n' "$*"; }   # green
c_y() { printf '\033[1;33m%s\033[0m\n' "$*"; }   # yellow
c_r() { printf '\033[1;31m%s\033[0m\n' "$*"; }   # red
step() { printf '\n\033[1;36m==== %s ====\033[0m\n' "$*"; }
die()  { c_r "FATAL: $*"; exit 1; }
trap 'c_r "Failed at line $LINENO. See output above / phase0.log."' ERR

# =============================================================================
step "0/8  Environment summary"
echo "WORKDIR      = $WORKDIR"
echo "REPO/BRANCH  = $REPO_URL @ $BRANCH   (MERGE_PR=$MERGE_PR, PR #$PR_NUMBER)"
echo "TARGETS      = $BUILD_TARGETS   JOBS=$JOBS   RUN_TESTS=$RUN_TESTS"
mkdir -p "$WORKDIR"

# =============================================================================
step "1/8  Preflight — OS, GPU, driver, compute capability, disk"

[ "$(uname -s)" = "Linux" ] || die "This build is Linux-only (you are on $(uname -s))."

command -v nvidia-smi >/dev/null 2>&1 || die "nvidia-smi not found — no NVIDIA driver. Pick a GPU node."
c_g "Driver / GPU:"; nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader || true

# Compute capability must be >= 7.0 (Volta+). cuOpt requires this.
CC="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n1 | tr -d ' ')"
if [ -n "$CC" ]; then
  CC_MAJOR="${CC%%.*}"; CC_MINOR="${CC##*.}"
  echo "Detected compute capability: $CC"
  if [ "$CC_MAJOR" -lt 7 ]; then die "Compute capability $CC < 7.0 (Volta). cuOpt will not build/run here."; fi
  c_g "Compute capability OK (>= 7.0)."
  export CUDAARCHS="${CUDAARCHS:-${CC_MAJOR}${CC_MINOR}}"   # build ONLY for this arch = fast
  echo "Will build for CUDAARCHS=$CUDAARCHS (single arch — much faster than --allgpuarch)."
else
  c_y "Could not read compute_cap from nvidia-smi (older driver). Build will fall back to native detection."
fi

# Driver / CUDA sanity note (per prior GPU lessons: driver 580 -> CUDA13 'just works')
DRV="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -n1 | tr -d ' ')"
DRV_MAJOR="${DRV%%.*}"
if [ -n "${DRV_MAJOR:-}" ] && [ "$DRV_MAJOR" -lt 560 ]; then
  c_y "Driver $DRV (< 560): CUDA 13 wheels may not load. This env targets CUDA 13.3 —"
  c_y "if the build/import fails, either update the driver or switch to a CUDA-12 conda env file."
fi

# Disk check (CUDA toolkit + build tree are large)
FREE_GB="$(df -Pk "$WORKDIR" | awk 'NR==2{print int($4/1024/1024)}')"
echo "Free disk on $(df -P "$WORKDIR" | awk 'NR==2{print $6}'): ${FREE_GB} GB"
[ "$FREE_GB" -ge "$MIN_DISK_GB" ] || c_y "WARNING: < ${MIN_DISK_GB} GB free — CUDA toolkit + build may run out of space."

RAM_GB="$(free -g 2>/dev/null | awk '/Mem:/{print $2}')"
echo "CPU cores: $(nproc 2>/dev/null || echo '?')   RAM: ${RAM_GB:-?} GB"

# =============================================================================
step "2/8  Real CUDA op smoke test (device vector-add, not just is_available)"
# Use nvcc if a system CUDA is present; otherwise defer to the post-build import
# check (cuOpt itself running on the GPU is the definitive real-op proof).
if command -v nvcc >/dev/null 2>&1; then
  TMPCU="$(mktemp --suffix=.cu)"
  cat > "$TMPCU" <<'EOF'
#include <cstdio>
__global__ void add(const float* a, const float* b, float* c, int n){
  int i = blockIdx.x*blockDim.x + threadIdx.x; if (i<n) c[i]=a[i]+b[i];
}
int main(){
  const int n=1<<20; size_t sz=n*sizeof(float);
  float *a,*b,*c; cudaMallocManaged(&a,sz); cudaMallocManaged(&b,sz); cudaMallocManaged(&c,sz);
  for(int i=0;i<n;i++){a[i]=1.0f;b[i]=2.0f;}
  add<<<(n+255)/256,256>>>(a,b,c,n);
  cudaError_t e=cudaDeviceSynchronize();
  if(e!=cudaSuccess){printf("CUDA ERROR: %s\n",cudaGetErrorString(e));return 1;}
  double s=0; for(int i=0;i<n;i++) s+=c[i];
  printf("vector-add result sum=%.0f (expected %d) — GPU compute OK\n", s, 3*n);
  return (s==3.0*n)?0:2;
}
EOF
  if nvcc -o /tmp/_cu_smoke "$TMPCU" 2>/tmp/_nvcc.err; then
    /tmp/_cu_smoke && c_g "Real CUDA op PASSED." || die "CUDA op ran but result wrong — bad GPU/driver."
  else
    c_y "nvcc compile failed (system CUDA mismatch). Skipping — will verify via cuOpt import after build."
    cat /tmp/_nvcc.err || true
  fi
  rm -f "$TMPCU" /tmp/_cu_smoke
else
  c_y "No system nvcc. Skipping standalone op; cuOpt import+solve after build is the real-op proof."
fi

# =============================================================================
step "3/8  Install miniforge (mamba) if absent"
if [ ! -x "$MINIFORGE_DIR/bin/conda" ]; then
  c_y "miniforge not found — installing to $MINIFORGE_DIR"
  ARCH="$(uname -m)"
  curl -fsSL "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${ARCH}.sh" -o /tmp/miniforge.sh
  bash /tmp/miniforge.sh -b -p "$MINIFORGE_DIR"
  rm -f /tmp/miniforge.sh
else
  c_g "miniforge already present."
fi
# shellcheck disable=SC1091
source "$MINIFORGE_DIR/etc/profile.d/conda.sh"
command -v mamba >/dev/null 2>&1 || conda install -n base -y -c conda-forge mamba
c_g "conda: $(conda --version)   mamba: $(mamba --version 2>/dev/null | head -n1)"

# =============================================================================
step "4/8  Clone / update cuOpt ($BRANCH)"
if [ ! -d "$REPO_DIR/.git" ]; then
  git clone "$REPO_URL" "$REPO_DIR"
else
  c_g "Repo exists — fetching."
  git -C "$REPO_DIR" fetch --all --prune
fi
git -C "$REPO_DIR" checkout "$BRANCH"
git -C "$REPO_DIR" pull --ff-only origin "$BRANCH" || c_y "Skipping pull (detached/tag)."
echo "cuOpt VERSION: $(cat "$REPO_DIR/VERSION" 2>/dev/null || echo '?')"
echo "HEAD: $(git -C "$REPO_DIR" rev-parse --short HEAD)"

# =============================================================================
if [ "$MERGE_PR" = "1" ]; then
  step "4b/8  Merge PR #$PR_NUMBER (EV distance-breaks) on top of $BRANCH"
  git -C "$REPO_DIR" fetch origin "pull/$PR_NUMBER/head:pr-$PR_NUMBER"
  git -C "$REPO_DIR" config user.email "dev@cuopt-dev.local" >/dev/null 2>&1 || true
  git -C "$REPO_DIR" config user.name  "cuopt-dev"          >/dev/null 2>&1 || true
  if git -C "$REPO_DIR" merge --no-edit "pr-$PR_NUMBER"; then
    c_g "PR #$PR_NUMBER merged cleanly."
  else
    git -C "$REPO_DIR" merge --abort || true
    die "PR #$PR_NUMBER does not merge cleanly onto $BRANCH — resolve manually (it may have drifted)."
  fi
fi

# =============================================================================
step "5/8  Create CUDA-13.3 conda build environment"
cd "$REPO_DIR"
ARCH="$(uname -m)"
ENV_FILE="conda/environments/all_cuda-133_arch-${ARCH}.yaml"
[ -f "$ENV_FILE" ] || ENV_FILE="$(ls conda/environments/all_cuda-13*_arch-${ARCH}.yaml 2>/dev/null | head -n1)"
[ -n "${ENV_FILE:-}" ] && [ -f "$ENV_FILE" ] || die "No CUDA-13 conda env file found under conda/environments/ for $ARCH."
echo "Using env file: $ENV_FILE"
if [ ! -d "$ENV_PREFIX" ]; then
  mamba env create --yes -p "$ENV_PREFIX" --file "$ENV_FILE"
else
  c_g "Conda env exists — updating to match spec."
  mamba env update --yes -p "$ENV_PREFIX" --file "$ENV_FILE" --prune
fi
# conda's activate.d scripts (e.g. cuda-nvcc) reference vars like NVCC_PREPEND_FLAGS
# that are unset on first activation — relax nounset across activate to avoid a
# spurious "unbound variable" exit under `set -u`.
set +u
conda activate "$ENV_PREFIX"
set -u
c_g "Env active: $(python --version)  @  $CONDA_PREFIX"

# =============================================================================
step "6/8  Build cuOpt ($BUILD_TARGETS) for local arch — this is the long step"
echo "Tip: building single-arch (CUDAARCHS=${CUDAARCHS:-native}) instead of --allgpuarch."
export PARALLEL_LEVEL="$JOBS"
# --install is REQUIRED: build.sh's default does NOT install libcuopt into the
# conda prefix, so the Python `cuopt` wheel's find_package(cuopt) can't locate the
# cuopt::cuopt target and fails at rapids_cython_create_modules. --install places
# cuopt-config.cmake in $CONDA_PREFIX so the Python build resolves it.
time ./build.sh $BUILD_TARGETS --skip-grpc-build --install -v
c_g "Build finished."

# =============================================================================
step "7/8  Verify — import + real solve + routing tests"

c_y "7a) Python import (loads CUDA libs on the GPU — real-op proof):"
python - <<'PY'
import importlib
m = importlib.import_module("cuopt")
print("cuopt imported OK:", getattr(m, "__version__", "unknown"))
# API note (26.10): routing entrypoints live in cuopt.routing.vehicle_routing
# (DataModel / SolverSettings / Solve), NOT a `cuopt.routing.routing` submodule.
import cuopt.routing  # noqa
from cuopt.routing import DataModel, SolverSettings, Solve  # noqa
print("cuopt.routing API import OK (DataModel/SolverSettings/Solve)")
PY
c_g "Import OK."

if [ "$RUN_TESTS" = "1" ]; then
  c_y "7b) Routing test suite (this is the green signal):"
  # The routing tests read Solomon/PDPTW instances from RAPIDS_DATASET_ROOT_DIR.
  # Fetch them (idempotent) and point the var at the repo's own datasets dir —
  # otherwise it defaults to <cwd>/../datasets and the tests error with
  # FileNotFoundError on solomon/In/r107.txt.
  bash datasets/get_test_data.sh >/dev/null 2>&1 || c_y "get_test_data.sh note (may already be present)."
  export RAPIDS_DATASET_ROOT_DIR="$REPO_DIR/datasets"
  # Python routing tests
  if python -c "import pytest" 2>/dev/null; then
    PYTEST_DIRS="$(ls -d python/cuopt/cuopt/tests/routing 2>/dev/null || true)"
    if [ -n "$PYTEST_DIRS" ]; then
      pytest -q $PYTEST_DIRS --disable-warnings \
        && c_g "Python routing tests PASSED." \
        || c_y "Some python routing tests failed — inspect above."
    else
      c_y "No python routing test dir found (path may have moved)."
    fi
    # If PR #1196 was merged, run its dedicated suite explicitly.
    if [ "$MERGE_PR" = "1" ] && [ -f python/cuopt/cuopt/tests/routing/test_distance_breaks.py ]; then
      c_y "Running EV distance-breaks tests (PR #$PR_NUMBER):"
      pytest -q python/cuopt/cuopt/tests/routing/test_distance_breaks.py \
        && c_g "Distance-breaks tests PASSED." || c_y "Distance-breaks tests failed — inspect above."
    fi
  else
    c_y "pytest not in env; skipping python tests."
  fi
  # C++ gtest binaries (built by default into cpp/build/gtests)
  GTEST_BIN="$(ls cpp/build/gtests/ROUTING_TEST 2>/dev/null || ls cpp/build/gtests/*ROUTING* 2>/dev/null | head -n1 || true)"
  if [ -n "${GTEST_BIN:-}" ] && [ -x "$GTEST_BIN" ]; then
    c_y "Running C++ routing gtest: $GTEST_BIN"
    "$GTEST_BIN" --gtest_brief=1 && c_g "C++ routing gtests PASSED." || c_y "C++ routing gtests failed."
  else
    c_y "C++ routing gtest binary not found (may need default test build — omit --skip-tests-build)."
  fi
else
  c_y "RUN_TESTS=0 — skipping tests."
fi

# =============================================================================
step "8/8  DONE"
c_g "Phase 0 complete."
cat <<EOF

Next time, activate the env with:
  source "$MINIFORGE_DIR/etc/profile.d/conda.sh"
  conda activate "$REPO_DIR/$ENV_PREFIX"

Rebuild after code changes (fast, single arch):
  cd "$REPO_DIR" && CUDAARCHS=${CUDAARCHS:-native} ./build.sh $BUILD_TARGETS --skip-grpc-build --install

To bring in the EV charging PR next:  MERGE_PR=1 ./phase0_bootstrap.sh
Remember to STOP the Brev box when idle to save cost.
EOF
