# Native sparse cuOpt — production usage guide

How to build, deploy, and use the native-sparse cuOpt build — with an honest split between **what works
today (validated prototype)** and **what to add for a clean production API**.

---

## 1. Where the code is

| Artifact | Location |
|----------|----------|
| Solver C++ changes (the actual feature) | branch `feature/native-sparse-core` off cuOpt `main` (`f3ebc673`), **uncommitted working tree** — preserved as `native-sparse-core.patch` (3 files, ~175 lines) |
| Files touched | `cpp/src/routing/utilities/md_utils.hpp` (CSR storage + `build_csr`), `cpp/src/routing/arc_value.hpp` (sparse lookup + `BIG_COST`), `cpp/src/routing/fleet_info.cu` (`CUOPT_SPARSE_K` hook) |
| Evidence / results | `OPTION-D-RESULTS.md`, `native-sparse-*.png`, `logs/` |
| Reproduction scripts | `dense_nxn_baseline.py`, `sparse_e2e_test.py`, and the tuning scripts |

Everything is gated behind a `has_sparse_cost` flag — **a dense problem is byte-for-byte identical to
upstream cuOpt** (proven: 57 py + 40 C++ routing tests green with the flag off).

---

## 2. Build & deploy

```bash
# 1. Get cuOpt at the validated base and apply the native-sparse patch
git clone https://github.com/NVIDIA/cuopt.git && cd cuopt
git checkout f3ebc673                 # the validated base
git apply /path/to/native-sparse-core.patch

# 2. Build from source (single-arch for your GPU; see cuOPT-Dev/scripts/phase0_bootstrap.sh)
mamba env create --yes -p ./.cuopt_env --file conda/environments/all_cuda-133_arch-$(uname -m).yaml
conda activate ./.cuopt_env
CUDAARCHS=<your_arch> ./build.sh libcuopt cuopt --skip-grpc-build --install   # e.g. 90 (H200), 86 (A10)
```

**Packaging for production:** wrap the built `libcuopt` + `cuopt` wheel into your container image (the
same way you'd ship any custom cuOpt build), or install the wheel into your serving environment. The
self-hosted cuOpt server can be built the same way (drop `--skip-grpc-build`).

---

## 3. How to use it **today** (validated prototype)

The prototype is driven by an environment variable + one solver setting. It builds a **top-K CSR from
the cost matrix on the GPU** and solves through the sparse read path.

```python
import os
import cudf
from cuopt.routing import DataModel, SolverSettings, Solve

# (a) turn on native sparse: keep the K nearest neighbours per node (K-NN cost graph)
os.environ["CUOPT_SPARSE_K"] = "50"          # tune K to your instance (see section 5)

# (b) build the model as usual
dm = DataModel(n_locations, n_fleet, n_orders)
dm.add_cost_matrix(cost_df)                  # cudf DataFrame (GPU)
dm.add_transit_time_matrix(time_df)
dm.set_order_locations(order_locations)

# (c) THE FIX: make "using a missing arc" infeasible so the solver eliminates it.
#     Set a per-vehicle max route cost ABOVE any real route but BELOW the sparse sentinel (1e6).
dm.set_vehicle_max_costs(cudf.Series([max_route_cost] * n_fleet, dtype="float32"))

settings = SolverSettings(); settings.set_time_limit(10)
sol = Solve(dm, settings)
assert sol.get_status() == 0 and sol.get_total_objective() < 1e5   # < sentinel => no missing arcs
```

- **What this buys you:** the solver reads cost from an O(N·K) CSR instead of a dense N×N matrix — the
  path to problem sizes where the dense matrix won't fit in GPU memory.
- **Measured:** fully feasible, near-optimal (+1.8% to +6.2% vs dense) up to n=1000; memory saving
  8×→20× and growing with N. No lookup-speed penalty.

> Prototype caveats (see section 4): `CUOPT_SPARSE_K` is process-global; the CSR is built *from* the
> dense matrix (so this build still allocates dense once); only the **cost** matrix is sparse (time
> matrix stays dense). These are exactly what the production API removes.

---

## 4. Production-ready path (what to add)

Turn the prototype into a first-class feature — a bounded list:

1. **Direct CSR ingestion API** — `DataModel.add_cost_matrix_csr(offsets, indices, values)` (C++ +
   Cython + Python + server proto). The client sends the K-NN graph directly; the server **never
   materialises the dense matrix** → real O(N·K) memory at 100k+. (Replaces the `CUOPT_SPARSE_K` hook.)
2. **`SPARSE_ARC` infeasibility dimension** — productionises "the fix": a dedicated dimension that drives
   missing-arc usage to zero, so you don't co-opt `set_vehicle_max_costs` and it composes with real
   max-cost limits. (Mirror the existing `dim_t` machinery.)
3. **Sparse the transit-time matrix too** — same treatment as cost, or support distance-only models.
4. **Connectivity-preserving CSR builder** — K-NN + a spanning overlay so small K stays feasible.

None of these is an open-ended rewrite; each mirrors machinery cuOpt already has.

---

## 5. Operational notes (tuning for production)

| Knob | Guidance |
|------|----------|
| **K (neighbours/node)** | Start ~30–50; increase until `objective < sentinel` (no missing arcs). K/N shrinks as N grows, so K is roughly sub-linear — pick per data density. Real (clustered) delivery data needs smaller K than random. |
| **max route cost** | Set above your largest real route cost but well below the sparse sentinel (`1e6`). Generous rule of thumb: the dense total objective (per-vehicle it's far above any single route). |
| **Sentinel `BIG_COST`** | `1e6` in this build (navigable). If your real costs are large, scale it so it stays >> a real route but not so large the local search can't gradient (avoid `1e30`). |
| **Validation** | After solve, check `status == 0` **and** `objective < sentinel`. An objective near/above the sentinel means the solution still traverses missing arcs (raise K or the max-cost fix). |

---

## 6. Using the *other three* capabilities in production

This native-sparse build is Feature 4. The other three (validated separately, see the repo root):
- **EV charging (Feature 1)** — `DataModel.add_distance_break(...)` from PR #1196 (+ our integration
  fixes). Single-cycle is production-ready.
- **Skill-match (Feature 2)** — set `set_order_prizes(all=1)`; the solver returns a clean partial
  solution honouring constraints (NVIDIA-endorsed pattern, no source change).
- **Time-of-day (Feature 3)** — application-layer Tier A: one solve per departure window with
  time-bucketed matrices (`phase1-time-of-day/`).
