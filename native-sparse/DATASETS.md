# Benchmark datasets — how to reproduce

Every benchmark in this repo is reproducible without any private data. Two kinds of input are used.

## 1. Sparse payload benchmark (native sparse / B5) — synthetic, seeded

`b5_csr_benchmark.py` generates its own stops and K-NN cost graph — nothing to download.

- **Generator:** `sparse_matrix_generator.py` (ships in this folder). Builds a K-nearest-neighbour sparse
  matrix from stop coordinates using a KD-tree + Haversine distance — the **same generator the original
  Phase-4 benchmark used**, so results are directly comparable.
- **Locations:** 10,000 stops drawn from a fixed uniform box with **`numpy` seed 42**
  (lat 33.2–33.8, lon −112.3 to −111.7), identical to the original run.
- **Run:**
  ```bash
  # with the enhanced cuOpt server (cost_matrix_csr) reachable at BASE
  python b5_csr_benchmark.py     # 10k stops, K = 10 / 20 / 50
  ```
- **What it measures:** the CSR request payload (MB) vs the original augmented-dense payload, and whether
  the server accepts it (HTTP 200). Results: `b5_csr_results.json`.

## 2. Regression + gap-to-BKS benchmark (EV / capability #1) — standard academic instances

`../benchmark/` uses cuOpt's **own** methodology and the **standard public** routing instances — no custom
data, so NVIDIA can reproduce exactly.

- **Instances:** Solomon (e.g. `r107`, BKS cost 1080.92 / 11 vehicles) and Gehring-Homberger 200–1000.
- **Source:** fetched at test time via cuOpt's own **`datasets/get_test_data.sh`** (that is why `datasets/`
  is git-ignored here — the data belongs to cuOpt, not this repo).
- **Metric:** gap to Best-Known Solution, `|((achieved − BKS)/BKS) × 100|`, 5% regression threshold — the
  same rule cuOpt's regression harness uses.
- **Run:** see `../benchmark/README.md` (EV feature OFF vs ON on the same instance → no quality regression).

## 3. Capabilities #2 / #3 (skill-match, time-of-day) — self-generated

`../feature2-skill-match/` and `../feature3-time-of-day/` scripts build their own small problems with
`numpy` (no external data) and print the measured result (prize-pattern partial solution; 2.21× rush penalty).

---

**Summary for reviewers:** the sparse benchmark is synthetic + seeded (generator included); the regression
benchmark uses standard Solomon/Gehring-Homberger instances via cuOpt's own fetch script; the other two
capabilities self-generate. Nothing here needs private or customer data.
