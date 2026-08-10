# B5 — Sparse (CSR) cost-matrix ingestion over REST

**Status:** implemented + validated on A10 (`sm_86`), cuOpt `26.10.00`. This is the ingestion layer on top of
the native-sparse solver read path (`native-sparse-core.patch`): it lets a client **send** a sparse K-NN cost
matrix over REST instead of a dense one, so the payload that was impossible before now submits and solves.

---

## Why this exists

The native-sparse solver change makes cuOpt *read* cost from a CSR (K-NN) structure. But a client still had
no way to *send* one — the REST request only accepted a dense `cost_matrix_data`. For a 10,000-stop problem a
K-NN graph is ~0.76 MB, yet it had to be re-expanded to a **dense 2,290 MB** matrix that exceeds the 2 GB
REST limit, so the request never submitted. B5 closes that gap.

## What B5 adds

A `cost_matrix_csr` field on the routing request:

```
cost_matrix_csr:
  n_locations: int                    # square dimension
  offsets: {vehicle_type: [int]}      # CSR row offsets, length n+1
  indices: {vehicle_type: [int]}      # CSR column indices, length nnz (sorted per row)
  values:  {vehicle_type: [float]}    # CSR cost values, length nnz
```

Server-side, `set_cost_matrix_csr()` reconstructs the cost matrix from the CSR (vectorized, O(nnz); absent
`(i,j)` pairs get a large finite sentinel) and the solve proceeds through the normal path. Because the request
dict is built via `dict(OptimizedRoutingData.parse_obj(...))`, adding the field auto-threads it through the
whole chain — no plumbing changes elsewhere.

**Files changed** (server, ~87 lines — see `b5-server-csr.patch`):
- request schema: `CostMatrixCSR` model + `cost_matrix_csr` field
- solver entry: thread the field through, accept it in the "cost required" check, add the ingestion branch
- data model: `set_cost_matrix_csr()` — the vectorized reconstruction

## Result — the payload benchmark now passes

Same K-NN generator, same 10,000-stop scenario as the earlier sparse benchmark — but the request carries a
CSR payload:

| Stops | K | Sparse core | **CSR request payload** | Prior augmented-dense | Prior | **B5** |
|-------|---|-------------|-------------------------|------------------------|-------|--------|
| 10,000 | 10 | 0.76 MB | **2.94 MB** | 2,290.5 MB | ❌ FAIL (>2 GB) | ✅ **PASS · HTTP 200** |
| 10,000 | 20 | 1.53 MB | **5.39 MB** | 2,292.0 MB | ❌ FAIL | ✅ **PASS · HTTP 200** |
| 10,000 | 50 | 3.81 MB | **12.68 MB** | 2,296.5 MB | ❌ FAIL | ✅ **PASS · HTTP 200** |

- The sparse core is **identical** to the prior run (0.76 / 1.53 / 3.81 MB) — same K-NN data.
- The full CSR request (with fleet + task) is **2.9–12.7 MB**, three orders of magnitude under 2 GB, and the
  server **accepts and enqueues** it — the exact step that failed before.

![Payload reduction by technique](../docs/assets/native-sparse-a10-payload-comparison.png)

**Correctness (verified):** a lossless CSR reconstructs the dense matrix *exactly* (max diff 0.0); a K-NN CSR
reconstructs the expected augmented matrix; an end-to-end `cost_matrix_csr` request solves with **status 0**
and a feasible route.

## Deploying as a server (generic)

Package the built cuOpt library + the patched `cuopt_server` into a container image and run
`python -m cuopt_server.cuopt_service -p 5000`. One portability note that costs hours if missed:

> If your base image ships **no CUDA headers** (e.g. a `cuda:*-base` image), cupy's JIT fails at solve time
> with *"Failed to find CUDA headers … or specify CUDA_PATH"*, and forked solver workers exit. Point cupy at
> the headers the conda env already ships:
> `CUDA_PATH=<conda-prefix>/targets/x86_64-linux` — set on the **process/deployment** environment (not an
> interactive shell). Or build `FROM` a `cuda:*-devel` image.

## Honest scope

B5 reconstructs the matrix **server-side** (dense internally) — this delivers the full network-payload win
(the benchmark's failing metric) and is suitable up to ~10k on a 24 GB GPU. The
**never-materialize-dense** path — a native C++ `DataModel.add_cost_matrix_csr` so the solver holds only the
CSR and reaches **100k on one GPU** — is the deliberate next step, scoped in
[`B5-PLAN-direct-csr-ingestion.md`](B5-PLAN-direct-csr-ingestion.md).

*Solver + server changes are provided as patches (`native-sparse-core.patch`, `b5-server-csr.patch`); no
cuOpt source is committed to this repo.*
