# 04 — Implementation Roadmap

A phased plan that de-risks the build first, delivers the cheapest win first, and keeps us on the
**upstream-first** path so we avoid carrying a fork.

---

## Phase 0 — Build bring-up (shared prerequisite, do once)

**Goal:** a reproducible from-source build of cuOpt `main` on our GPU hardware, tests green.

Per the official `CONTRIBUTING.md`, conda is the supported path (building without conda is "very difficult"):

```bash
# On a Linux GPU box (A10 / H100), CUDA 12.x or 13.x, compute capability >= 7.0
conda env create -p ./.cuopt_env --file conda/environments/all_cuda-133_arch-$(uname -m).yaml
conda activate ./.cuopt_env
./build.sh                       # builds libcuopt, cuopt, cuopt_server, cuopt_sh_client
# faster iteration while working on routing only:
./build.sh libcuopt cuopt --skip-grpc-build
```

**Deliverable:** documented build runbook + green test baseline. **Est. 3–5 days** (first CUDA build is the
main unknown; our A10 box already has the CUDA/driver stack per prior work).

**Exit gate:** `main` builds clean and cuOpt's routing tests pass on our box.

---

## Phase 1 — Feature 3 Tier A (time-of-day, app layer) — *fastest customer value*

No solver change. Pre-compute time-bucketed matrices; solve per departure window; stitch results in the
v4 front-end / server layer. Optional warm-start between windows.

- **Effort:** days · **Risk:** very low · **Perf risk to solver:** none.
- **Deliverable:** rush-hour-aware routing demo without touching cuOpt.
- **Why first:** unblocks the customer story immediately and is independent of the build (Phase 0 not
  strictly required for Tier A).

---

## Phase 2 — Feature 1 (EV charging) — *adopt PR #1196*

1. On the Phase 0 build, create a working branch and merge `pr-1196` (already fetched as branch `pr-1196`).
2. Resolve any drift vs. `main`; build.
3. Run bundled tests: `cpp/tests/routing/unit_tests/distance_breaks.cu` (426 lines) and
   `python/cuopt/cuopt/tests/routing/test_distance_breaks.py` (487 lines).
4. Run `docs/.../examples/distance_break_example.py` end-to-end.
5. **Feature-OFF regression benchmark** (see `03` section prove-it) — must be within noise.
6. Expose `add_distance_break()` via the self-hosted server; wire the v4 front-end payload (EV stations
   already exist in `evChargingData.ts`).

- **Effort:** 1–2 weeks · **Risk:** low (code + tests exist) · **Perf when OFF:** zero (gated).
- **Upstream action:** review/upvote PR #1196; offer to help land it so we inherit it maintained.

---

## Phase 3 — Feature 2 (skill-match hardening) — *bug fix + defence in depth*

1. Author a minimal repro payload that forces infeasibility with a `vehicle_order_match` constraint; confirm
   whether a forbidden vehicle→order pair survives in the partial solution. Freeze as a regression test.
2. Ship the **server-side post-solve guard** immediately (reject/flag routes violating the input mask) —
   this protects us regardless of the upstream timeline.
3. Localise the relaxation-path defect (prize-collection allowing MISMATCH relaxation); make MISMATCH
   non-relaxable so the solver drops the *task* rather than assigning a forbidden vehicle.
4. Validate: forbidden pairs never appear; constrained problems solve at least as fast (pruning benefit).
5. File repro as a GitHub issue + fix as a PR upstream.

- **Effort:** 1–3 weeks · **Risk:** low-medium · **Perf:** neutral-to-positive.

---

## Phase 3.5 — Feature 4 Option A (server-side matrix generation) — *fast, highest business impact*

Removes the **measured** 2 GB payload wall (POC Phase 4) that caps monolithic solves at ~7,500 stops. Client
sends coordinates + K instead of a dense N×N matrix; the server builds the matrix on the GPU. No solver-core
change, so no hot-path risk. Validate with the sparse scenario in the benchmark harness (`05` section B.4): payload
must drop from GB to KB while solve time tracks the dense clustering baseline.

- **Effort:** 1–2 weeks · **Risk:** low · **Perf when unused:** zero (dense path untouched).
- **Business impact:** highest of all — unlocks the path to 100 k+ stops. Also an official POC enhancement ask.

## Phase 4 — Feature 3 Tier B (native time-dependent) — *only if funded/justified*

Extend the multi-matrix selector from `[vehicle_type]` to `[vehicle_type][time_bucket]`; select the bucket
from cumulative arrival time in the TIME dimension's forward accumulation; gate behind
`has_time_dependency`; enforce FIFO consistency; mirror PR #1196's test rigour (~450+ lines).

- **Effort:** 4–8 weeks · **Risk:** medium-high (touches TIME hot path; correctness-critical).
- **Decision gate:** only proceed if Tier A proves insufficient for a real customer requirement.

---

## Timeline & dependency view

```
Phase 0    Build bring-up        [###]                       (3–5 d, prereq for 2/3/3.5/4)
Phase 1    Time-of-day Tier A    [##]                        (days, independent) ← value first
Phase 2    EV charging (PR1196)      [########]              (1–2 wk)  depends on P0
Phase 3    Skill-match fix           [##########]            (1–3 wk)  depends on P0
Phase 3.5  Sparse: server-gen (Opt A)[########]              (1–2 wk)  depends on P0 ← highest impact
Phase 4    Time-of-day Tier B                 [############...] (4–8 wk, optional) depends on P0
Phase 5    True sparse core (Opt D)             [################...] (6–12 wk R&D, optional) depends on P0
```

Every phase is gated by the **adopted POC benchmark harness** (`05` section B): feature-OFF must reproduce the
canonical A10 baselines (FSD 65 s / MIX 70 s / HDP 102 s P95) within noise before the change is merge-ready.

---

## Governing principles

1. **Upstream-first.** Prefer landing changes in `NVIDIA/cuopt` over carrying a fork. A fork means rebasing
   every ~2 months against a fast-moving 34k-line CUDA codebase — real, recurring cost. Forking is the
   *fallback* for Feature 1 if PR #1196 stalls, not the default.
2. **Feature-gated always.** Every change ships behind a `has_*` flag so the default path equals upstream
   performance (the whole basis of `03`).
3. **Measured, not asserted.** No change is "performance-safe" until the feature-OFF regression benchmark
   passes within noise, with the numbers recorded (date / GPU / driver / dataset / method).
4. **Cheapest value first.** Tier-A time-of-day and the server-side skill guard both ship without deep solver
   work and de-risk the customer conversation while the harder pieces proceed.

---

## Hardware & licensing notes

- **Hardware:** any Linux GPU box with CUDA 12/13 and compute capability ≥ 7.0 (Volta+). Our A10 box and the
  H100 bench node both qualify.
- **License:** Apache-2.0 — modification and redistribution permitted; keep NOTICE/attribution intact if we
  ship a build.
