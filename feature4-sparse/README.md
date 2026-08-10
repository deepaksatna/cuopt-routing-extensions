# Feature 4: Sparse (K-NN) cost-matrix support

Status: delivered and validated. The full implementation, benchmark, and results are in the `native-sparse/`
folder at the repository root. This file is a short overview.

## Problem

cuOpt's solver reads cost from a dense N-by-N matrix, and the REST API accepts only a dense cost matrix. A
sparse K-nearest-neighbour input must be re-expanded to dense before solving, so the JSON payload grows on
the order of N squared and reaches the 2 GB REST limit at about 7,500 stops. A 10,000-stop dense cost matrix
is about 2,290 MB and cannot be submitted. GPU memory was not the bottleneck; the payload was.

## Options considered, and what was built

Four options were evaluated. Option D (a true sparse read path in the solver core) plus REST ingestion was
built, because it is the only one that removes both the payload wall and the O(N squared) memory growth.

| Option | Idea | Removes payload wall | Removes O(N^2) memory |
|--------|------|:--------------------:|:---------------------:|
| A. Server-side matrix generation | client sends coordinates plus K; server builds the matrix | Yes | No |
| B. Binary payload encoding | binary instead of JSON | Partial | No |
| C. Sparse-in, dense-solve | accept K-NN, densify on the server | Yes | No |
| D. Sparse solver core (delivered) | cost lookup reads the CSR / K-NN directly | Yes | Yes, O(N*K) |

## Delivered

1. Native sparse (CSR) cost-matrix read path in the solver core, gated by a has_sparse_cost flag so dense
   problems are unchanged. Patch: `native-sparse/native-sparse-core.patch` (3 files: arc_value.hpp,
   md_utils.hpp, fleet_info.cu).
2. B5 REST ingestion: a cost_matrix_csr request field so the client sends the K-NN graph directly. Patch:
   `native-sparse/b5-server-csr.patch` (3 server files).

## Result

Same K-NN generator and same 10,000-stop scenario as the original benchmark. The payload that failed before
now submits and solves:

| Stops | K | CSR request payload | Prior dense payload | Result |
|-------|---|---------------------|---------------------|--------|
| 10,000 | 10 | 2.94 MB | 2,290.5 MB | PASS (was FAIL) |
| 10,000 | 20 | 5.39 MB | 2,292.0 MB | PASS (was FAIL) |
| 10,000 | 50 | 12.68 MB | 2,296.5 MB | PASS (was FAIL) |

Solver memory is O(N*K) instead of O(N^2): about 303x smaller at 10,000 stops and 3,030x at 100,000.
Validated on NVIDIA A10 (sm_86).

## Where the details are (native-sparse/)

- native-sparse-core.patch, b5-server-csr.patch: the code changes
- A10-BENCHMARK-REPORT.md: the benchmark write-up and results
- B5-CSR-INGESTION.md: the CSR ingestion design and API
- b5_csr_benchmark.py, sparse_matrix_generator.py: the runnable benchmark and its generator
- DATASETS.md: the datasets (synthetic and seeded; no private data)
- B5-PLAN-direct-csr-ingestion.md: the next step (native never-materialize-dense ingestion for 100k on one GPU)
