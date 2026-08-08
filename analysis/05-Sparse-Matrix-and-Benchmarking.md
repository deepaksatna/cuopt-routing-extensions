# 05 — Sparse-Matrix Support (Feature 4) & the Performance-Benchmark Harness

This document adds the fourth capability — **native sparse (K-NN) cost-matrix support** — and adopts the
existing **an internal cuOpt POC benchmarking methodology** as the harness that proves "no regression /
net improvement" for every feature in this study.

Sources of record:
- Benchmark data: `benchmark-ai-packs/CuOPT-small/payload_optimisation/REPORT_A100_Payload_Optimization.md`
  and `EMAIL_Product_Team_CuOPT_Findings.md`
- Benchmark methodology: `benchmark-ai-packs/performance/docs/AI_Accelerator_CuOPT_POC_Product_Benchmarking.md`
- Solver source: `cuOPT-Dev/cuopt-src` @ main (VERSION 26.10.00)

---

## Part A — Feature 4: Native Sparse-Matrix Support

### A.1 The problem, quantified (measured, not theoretical)

The 8×A100 payload-optimization POC ("Phase 4: Sparse Matrix") measured this directly:

| Stops | K-NN | Sparse size | **Actual payload sent** | Result |
|-------|------|-------------|-------------------------|--------|
| 10,000 | K=10 | 0.76 MB | **2,290 MB** | FAIL |
| 10,000 | K=20 | 1.53 MB | **2,292 MB** | FAIL |
| 10,000 | K=50 | 3.81 MB | **2,296 MB** | FAIL |

The dense-payload growth law measured in the same POC:

```
Payload ≈ 36 × N²  bytes     (JSON encoding of 2 × N×N matrices)
7,500 stops  → 2,074 MB  → EXCEEDS the 2 GB API limit
10,000 stops → 3,540 MB  → fails without clustering
```

**Conclusion from the data:** the K-NN sparse matrix is 0.76 MB, but because the API expands it to dense
before solving, the real payload stays ~2,290 MB and fails. The 2 GB payload ceiling — not GPU memory
(320 GB was never the bottleneck) — is what caps scale at ~7,500 stops monolithic. This is why the POC team
flagged native sparse support as the **highest-impact enterprise-scale feature**.

### A.2 What the source actually shows (important nuance)

cuOpt is **not** entirely dense-only on input. It already ships a **sparse CSR graph ingestion path**:

```
// cpp/include/cuopt/routing/distance_engine/waypoint_matrix.hpp:21
"A waypoint matrix ... an incomplete graph ... can be passed to waypoint matrix.
 The waypoint matrix can then return a cost matrix that can be used by the solver."
// offsets: host pointer of size V+1  (CSR row offsets)   (line 53)
```

So sparse-in exists — but the waypoint matrix **densifies to an N×N cost matrix before the solver runs**.
And the solver core consumes a **dense pointer**:

```cpp
// cpp/include/cuopt/routing/data_model_view.hpp:77
void add_cost_matrix(f_t const* matrix, uint8_t vehicle_type = 0);   // dense N×N
```

The innermost hot loop reads costs as an O(1) dense index (`matrix[i*n + j]`). **This is the real reason the
benchmark team's "dense required" finding is correct — the solver evaluates arc costs against a dense array.**

### A.3 Design options (honest, ranked by depth)

| Option | What it changes | Solves the 2 GB payload wall? | Solves GPU-memory O(N²)? | Effort |
|--------|-----------------|-------------------------------|--------------------------|--------|
| **A. Server-side matrix generation** | Client sends coordinates + K; server builds the matrix on the GPU | **Yes** (payload → KB) | No (still dense in GPU) | Low-Med |
| **B. Binary payload encoding** | MessagePack/binary instead of JSON | Partially (~30–50 %) | No | Low |
| **C. Sparse ingestion, dense solve** (waypoint-style) | Accept K-NN, densify on server | **Yes** for payload | No | Medium |
| **D. True sparse solver core** | Cost lookup reads CSR/K-NN directly; no densification | **Yes** | **Yes** — O(N·K) memory | **High** |

**Recommendation:** ship **A (server-side generation)** first — it removes the *measured* bottleneck (the
2 GB **payload** limit, which is what actually failed) with modest effort and no solver-core risk, and it is
one of the POC's own enhancement requests. Pursue **D (true sparse core)** only as a funded R&D track,
because it rewrites the cost lookup in the innermost kernel and is where performance can regress if done
naively (see A.4).

### A.4 Performance stance — this is the one feature where "no impact" needs care

Unlike Features 1–3, sparse support (Option D) changes the **hot cost lookup itself**:

- Dense today: `cost = matrix[i*n + j]` — a single coalesced O(1) load. Extremely GPU-friendly.
- Sparse (K-NN): resolving `cost(i, j)` means searching i's K neighbours for j — not O(1), and potentially
  divergent/uncoalesced if stored naively.

Therefore **Option D must be gated and benchmarked, not assumed free**:
- Gate behind `has_sparse_cost` (same idiom as `has_distance_window`) so dense problems are byte-for-byte
  upstream.
- For the sparse path, store K-NN in a layout that keeps neighbour lookups coalesced (sorted neighbour lists,
  CSR with binary search or a hashed lookup), and treat any (i, j) not in the K-NN set as "not directly
  connected" (routing rarely needs the full N² anyway).
- **Net effect can be positive at scale:** at 100 k stops the dense matrix is ~infeasible to hold/transfer;
  a sparse core makes previously-impossible problems solvable — the honest "even improve" here is *enabling
  scale that dense cannot reach*, not making small problems faster.

| Metric | Assessment |
|--------|-----------|
| Effort | Option A: 1–2 wk · Option D: 6–12 wk (R&D) |
| Risk | A: low · D: high (touches innermost cost load) |
| Perf when OFF (dense) | Zero — gated |
| Perf when ON | A: none (dense solve, tiny payload) · D: layout-dependent; must be measured |
| Business impact | **Highest of all four** — unlocks 100 k+ stops |

---

## Part B — The Performance-Benchmark Harness (adopted from the POC)

We do not invent a benchmark. We adopt the **an internal cuOpt POC Product Benchmarking** methodology as
the standing harness that gates every feature in this study, extended with a **feature-OFF regression gate**.

### B.1 Scenario-first philosophy (kept as-is)
Identify business scenario → define realistic constraints → generate representative data → run with fixed
scenario behaviour → **report in business terms** ("100 technicians optimized in 65 s"). This keeps
performance claims meaningful to customers, not just to engineers.

### B.2 Canonical scenarios & measured baselines (cuOpt v25.10, 2×VM.GPU.A10.2 / 4×A10 24 GB)

| Scenario | Fleet | Stops | Avg | P95 | Success |
|----------|-------|-------|-----|-----|---------|
| FIELD_SERVICE_DISPATCH | 100 | 130 | 62.4 s | 65.0 s | 100 % |
| MIXED_DENSITY | 100 | 500 | 64.9 s | 70.3 s | 100 % |
| HIGH_DENSITY_PARCEL | 100 | 2,500 | 101.9 s | 102.4 s | 100 % |

These are the **reference numbers our modified build must reproduce within noise when features are OFF.**

### B.3 Metric tiers (the pass/fail contract)

| Tier | Meaning | Examples & targets |
|------|---------|--------------------|
| **P0** | Deal-breakers | Success ≥99 % · P95 ≤120/180/300 s (FSD/MIX/HDP) · Infeasible <5 % · Conflict reduction >90 % |
| **P1** | Differentiation | Throughput >0.01 job/s · objective improvement >10 % · replan latency <2× · route stability ≥70 % |
| **P2** | Optimization | Solve/vehicle ≤1000 ms · queue depth <2× GPU count · response CoV <15 % |

### B.4 Feature-specific benchmark additions

| Feature | Extra scenario to run | Extra metric to record |
|---------|-----------------------|------------------------|
| 1 EV charging | Baseline vs **Advanced/EV profile** (POC already runs 9 baseline + 9 EV) | Δ solve time with distance-breaks ON vs OFF |
| 2 Skill match | Constrained fleet with `vehicle_order_match` forcing infeasibility | **Infeasible-job rate must stay honest** (no forbidden pairs served); solve time ON vs OFF |
| 3 Time-of-day | Multi-window (rush vs off-peak) matrices | Per-window solve time; app-layer stitch overhead |
| 4 Sparse (A/D) | 10 k / 50 k / 100 k stops | **Payload size** (target: KB not GB) and solve time vs dense clustering baseline |

### B.5 The regression gate (new, non-negotiable)
Before any feature is declared "performance-safe":
1. Build stock `main` and our feature build; run B.2 scenarios on both with the feature **compiled but OFF**.
2. **Require P0/P1/P2 within noise (±few %) of the B.2 baselines.** Fail ⇒ the feature is not merge-ready.
3. Then measure the feature **ON** cost curve and record it (date / GPU / driver / dataset / method) per the
   standing "always capture benchmark numbers" practice — never "it's fast."

Hardware note: the POC baseline is 4×A10 (24 GB); the payload/scale work used 8×A100 (40 GB). Use A10 for
functional + regression gating and A100/H100 for scale (Feature 4) runs.

---

## Part C — Updated capability picture (now four features)

| # | Capability | Verdict | Effort | Perf when OFF | Business impact |
|---|------------|---------|--------|---------------|-----------------|
| 1 | EV charging | Adopt PR #1196 | 1–2 wk | Zero | Medium |
| 2 | Skill-match | Fix + guard | 1–3 wk | Neutral→faster | Medium-High |
| 3 | Time-of-day | App-layer now / native later | Days / 4–8 wk | Zero | Medium |
| 4 | **Sparse matrix** | **Server-gen now / true sparse R&D** | 1–2 wk / 6–12 wk | Zero (dense gated) | **Highest (100 k+ stops)** |

**Sequencing impact:** Feature 4 Option A (server-side matrix generation) is a **fast, high-value** addition
that belongs alongside the time-of-day Tier-A and skill-guard quick wins. True sparse core (Option D) is the
one genuine multi-month R&D item and the only place where "no performance impact" requires measured proof
rather than the feature-gate guarantee alone.
