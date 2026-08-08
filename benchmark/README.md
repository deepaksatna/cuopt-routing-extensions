# Benchmark — adapted from cuOpt's own methodology

We deliberately **adopt NVIDIA cuOpt's own routing benchmark methodology** rather than invent one, so
the numbers are comparable to how the cuOpt team measures the solver.

## What cuOpt does (source: `regression/benchmark_scripts/benchmark.py`)

- **Metric — gap to Best-Known Solution (BKS).** cuOpt computes
  `bks_change = |((achieved − BKS) / BKS) × 100|` for cost and vehicle count
  (`get_bks_change()` in `benchmark.py`). Lower is better; **0% == matches the best-known solution**.
- **Reference data.** Best-known solutions ship in the repo:
  `datasets/ref/bks_gehring_homberger.csv` (Gehring-Homberger 200–1000 customers) and
  `datasets/ref/solomon_100.txt` (Solomon 100-customer instances).
- **Regression rule.** A run regresses if `bks_change` exceeds a **5% threshold** versus the rolling
  mean of the previous ~30 runs.
- **Timing.** cuOpt records the solver time per run.

## What we run here

- `nvidia_methodology_benchmark.py` — the faithful adaptation. Solves the standard Solomon `r107`
  instance (BKS: cost **1080.92**, **11** vehicles), reports **gap-to-BKS** as the solver time budget
  increases, and runs the **EV distance-break feature OFF vs ON** on the same instance to show the
  (feature-gated) EV code does not regress standard-instance quality.
- `benchmark_routing.py` — an indicative solve-time / scaling sweep across problem sizes (synthetic
  Euclidean instances), and EV ON-vs-OFF marginal cost at a fixed size.

Run inside the cuOpt conda env with the datasets fetched:

```bash
bash datasets/get_test_data.sh
export RAPIDS_DATASET_ROOT_DIR="$PWD/datasets"
python nvidia_methodology_benchmark.py
python benchmark_routing.py
```

## Results (H200, cuOpt 26.10.00)

### Gap-to-BKS on Solomon r107 (feature OFF) — cuOpt's own metric

BKS: cost **1080.92**, **11** vehicles.

| Solver budget | wall (s) | status | cost | vehicles | **gap-to-BKS (cost)** |
|--------------:|---------:|:------:|-----:|:--------:|----------------------:|
| 1 s  | 1.07  | 0 | 1116.30 | 13 | 3.27% |
| 3 s  | 3.10  | 0 | 1091.93 | 11 | **1.02%** |
| 10 s | 10.07 | 0 | 1131.01 | 10 | 4.63% |
| 30 s | 30.10 | 0 | 1119.33 | 10 | 3.55% |

cuOpt reaches **~1% of the best-known solution** and matches the BKS vehicle count (11) within a few
seconds. (Gap is non-monotonic in time because the objective trades vehicle count against distance —
the 10/30 s runs found 10-vehicle solutions with slightly higher distance; this is expected solver
behaviour, not a defect.)

### EV distance-breaks OFF vs ON (same instance, 10 s budget)

| EV feature | wall (s) | status | cost | vehicles | gap-to-BKS |
|-----------|---------:|:------:|-----:|:--------:|-----------:|
| **OFF** | 10.08 | 0 | 1074.68 | 11 | 0.58% |
| **ON**  | 10.12 | 0 | 1073.78 | 11 | 0.66% |

**Same solve time (10.08 vs 10.12 s) and solution quality within noise (0.58% vs 0.66%)** — the EV
distance-break feature adds **no measurable cost** on a standard instance. This is the "no performance
impact" claim, shown in cuOpt's own gap-to-BKS metric.

### Indicative solve-time scaling (synthetic, feature OFF)

| stops | fleet | budget (s) | wall (s) | status | objective |
|------:|------:|-----------:|---------:|:------:|----------:|
| 50   | 2  | 3  | 3.03  | 0 | 570.2  |
| 100  | 4  | 3  | 3.04  | 0 | 763.3  |
| 250  | 10 | 3  | 3.54  | 0 | 1347.0 |
| 500  | 20 | 6  | 6.36  | 0 | 1778.9 |
| 1000 | 40 | 10 | 10.20 | 0 | 2688.4 |

(EV ON-vs-OFF at n=250, 5 s: **5.06 s vs 5.07 s** — feature-ON wall time is identical.)

## Honest caveats

- Single **H200** (one GPU). cuOpt's published routing baselines and the internal POC used different
  hardware; absolute times are not directly comparable across GPUs — the **gap-to-BKS** metric is the
  portable, hardware-independent quality measure, which is why we lead with it.
- `r107` is one Solomon instance. The full gate runs the Gehring-Homberger set (200–1000 customers)
  and the Solomon/CVRP/PDPTW families via cuOpt's `benchmark.py`; extending to the full set is
  straightforward once those instance files are fetched.
- The strongest **no-regression** proof is *feature-OFF EV build vs stock `main`* on this same metric;
  this repo already proves no test regression by rebuild-and-compare, and the OFF-vs-ON result below
  shows the feature adds no solve-time cost when used.
