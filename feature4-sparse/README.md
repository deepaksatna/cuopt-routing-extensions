# Feature 4 — Sparse (K-NN) Cost-Matrix Support  *(separate workstream)*

This is the **4th challenge**, kept deliberately separate from the three already validated
(EV charging, skill-match, time-of-day). It is the one genuine multi-week R&D item in the study.

> **The other three challenges are done and preserved separately:**
> - EV charging (F1) + skill-match (F2) + time-of-day (F3) — validated on the H200.
> - Their code lives on git branch **`feature/ev-distance-breaks-pr1196`** (commits `f2a75bdb`,
>   `59432cf9`) and their evidence in **`cuOPT-Dev/worklog/`** + **`cuOPT-Dev/phase1-time-of-day/`**.
> - Sparse work here will use its **own branch off `main`** (independent of the EV branch) so the two
>   never entangle.

## The problem (measured in the an internal POC — see `analysis/05`)

- cuOpt's solver core consumes a **dense N×N** cost matrix (`matrix[i*n + j]`, O(1) coalesced load).
- The API expands even a sparse K-NN input to dense before solving, so the **JSON payload** grows as
  `~36·N²` bytes → **2 GB payload wall at ~7,500 stops**; 10k stops ≈ 3.5 GB (fails).
- GPU memory (320 GB) was never the bottleneck — the **payload** is.

## What we will test / build here (ranked, per `analysis/05` section A.3)

| Option | Idea | Solves payload wall? | Solves GPU O(N²)? | Effort |
|--------|------|:---:|:---:|:---:|
| **A. Server-side matrix generation** | client sends coords + K; server builds matrix on GPU | ✅ | ✗ | Low-Med |
| B. Binary payload encoding | MessagePack/binary vs JSON | ~ | ✗ | Low |
| C. Sparse-in, dense-solve (waypoint) | accept K-NN, densify on server | ✅ | ✗ | Med |
| **D. True sparse solver core** | cost lookup reads CSR/K-NN directly | ✅ | ✅ (O(N·K)) | High |

## Test plan (this folder)

1. **Dense N×N baseline** (`dense_nxn_test.py`): measure dense solve + matrix build across N
   (e.g. 500 / 1k / 2.5k / 5k / 7.5k / 10k) on the H200 — reproduce the payload/memory growth law and
   find where dense stops being practical. This is the control the sparse work must beat.
2. **Waypoint / CSR sparse ingestion** (`waypoint_csr_test.py`): exercise cuOpt's existing
   `waypoint_matrix` CSR path (`cpp/include/cuopt/routing/distance_engine/waypoint_matrix.hpp`) —
   K-NN in, cost matrix out — and confirm it densifies before the solver (the nuance in `analysis/05`
   section A.2).
3. **Option A prototype**: server-side matrix generation from coordinates + K (payload → KB), solve
   with the generated matrix; compare solve time vs the dense baseline at the same N.
4. **(Stretch) Option D notes**: gate `has_sparse_cost`, coalesced K-NN layout, benchmark the inner
   cost load — the only place "no perf impact" needs *measured* proof, not the feature-gate guarantee.

## Status

- [ ] Folder scaffolded (this README)
- [ ] Dense N×N baseline measured
- [ ] Waypoint/CSR path exercised
- [ ] Option A prototype
- [ ] Option D investigation (stretch)

*Uses the same built cuOpt on the H200 (`~/cuopt-dev/cuopt/.cuopt_env`). Keep on a separate git branch
off `main`.*
