# Sample benchmark input data (10,000 stops)

Concrete input files for the native-sparse benchmark, so reviewers can inspect the exact numbers without
running the generator. These are produced by the committed generator from a fixed seed, so they are fully
reproducible.

## Files

- `stops_10k_seed42.csv` - the 10,000 stop coordinates. Columns: stop_id, latitude, longitude.
  Generated with numpy seed 42 from a uniform box (latitude 33.2 to 33.8, longitude -112.3 to -111.7, the
  Phoenix, Arizona area). Stop 0 is the depot.
- `knn_csr_10k_k10.csv` - the K-nearest-neighbour sparse cost graph for those stops at K=10, in edge-list
  form. Columns: from_stop, to_stop, cost_km. This is the sparse content that the `cost_matrix_csr` payload
  carries. It has 119,991 arcs (about 12 per stop = K nearest, plus the depot and self), versus 100,000,000
  entries for the equivalent dense 10,000 by 10,000 matrix.

## How they were generated

```bash
python - <<'PY'
import numpy as np, sys, os
sys.path.insert(0, "..")            # native-sparse/ has sparse_matrix_generator.py
from sparse_matrix_generator import generate_sparse_matrix
np.random.seed(42)
lat = np.random.uniform(33.2, 33.8, 10000)
lon = np.random.uniform(-112.3, -111.7, 10000)
sp  = generate_sparse_matrix(lat, lon, k_neighbors=10, precision="FP32")
# sp.neighbor_indices / sp.neighbor_distances -> the edge list above
PY
```

Cost is Haversine distance in kilometres. The benchmark (`../b5_csr_benchmark.py`) builds the CSR
offsets/indices/values from exactly this data and submits it as `cost_matrix_csr`.

## Relationship to the dense matrix

The same 10,000 stops as a dense cost matrix is 10,000 x 10,000 = 100,000,000 float32 entries (about 0.4 GB
in memory, about 2,290 MB as JSON), which exceeds the 2 GB REST limit. The CSR edge list here is about
2 MB. That is the payload reduction the native-sparse feature delivers.
