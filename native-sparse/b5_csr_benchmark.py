"""Phase-4 benchmark, CSR mode (B5).

Same scenario + same K-NN generator as the original phase4_sparse_matrix benchmark, but the payload is
`cost_matrix_csr` (the client sends only nearest-neighbour arcs) instead of the augmented dense matrix.
The original benchmark FAILED because the augmented dense payload exceeded the 2 GB REST limit
(10k stops -> ~2,290 MB). Here we show the CSR payload is tiny and the server accepts it (PASS).
"""
import sys, json, time
import numpy as np
import requests

sys.path.insert(0, "/work/phase4")
from sparse_matrix_generator import generate_sparse_matrix, haversine_distance

BASE = "http://127.0.0.1:5000"
PAYLOAD_LIMIT_MB = 2000.0  # the original benchmark's FAIL threshold


def generate_test_locations(num_stops, seed=42):
    # identical to the original run_sparse_tests.generate_test_locations
    np.random.seed(seed)
    latitudes = np.random.uniform(33.2, 33.8, num_stops)
    longitudes = np.random.uniform(-112.3, -111.7, num_stops)
    return latitudes, longitudes


def build_csr_payload(sparse, lats, lons):
    """CSR from the K-NN graph: each row keeps its K neighbours + self(0) + depot(real dist)."""
    n = sparse.num_stops
    ni = sparse.neighbor_indices
    nd = sparse.neighbor_distances
    off = [0]; idx = []; val = []
    for i in range(n):
        arcs = {i: 0.0}                      # self
        for t in range(ni.shape[1]):
            j = int(ni[i, t])
            if j != i:
                arcs[j] = float(nd[i, t])
        if 0 not in arcs:                     # keep depot reachable
            arcs[0] = float(haversine_distance(lats[i], lons[i], lats[0], lons[0]))
        for c in sorted(arcs):
            idx.append(int(c)); val.append(float(arcs[c]))
        off.append(len(idx))
    return {"n_locations": n, "offsets": {"0": off}, "indices": {"0": idx}, "values": {"0": val}}


def run(num_stops, k, num_vehicles=50):
    print(f"\n=== Phase-4 (CSR mode): {num_stops} stops, K={k} ===")
    lats, lons = generate_test_locations(num_stops)
    t0 = time.time()
    sparse = generate_sparse_matrix(lats, lons, k_neighbors=k, precision="FP32")
    csr = build_csr_payload(sparse, lats, lons)
    body = {
        "cost_matrix_csr": csr,
        "fleet_data": {"vehicle_locations": [[0, 0]] * num_vehicles,
                       "capacities": [[num_stops // num_vehicles + 10] * num_vehicles],
                       "vehicle_max_costs": [1.0e5] * num_vehicles},
        "task_data": {"task_locations": list(range(num_stops)),
                      "demand": [[0] + [1] * (num_stops - 1)]},
        "solver_config": {"time_limit": 10},
    }
    payload = json.dumps(body)
    csr_mb = len(payload.encode("utf-8")) / (1024 * 1024)
    # the ORIGINAL augmented-dense payload that FAILED (measured, from the prior Phase-4 results)
    orig_measured = {(10000, 10): 2290.5, (10000, 20): 2292.0, (10000, 50): 2296.5}
    dense_mb = orig_measured.get((num_stops, k), (num_stops * num_stops * 23) / (1024 * 1024))
    gen_s = time.time() - t0
    print(f"  K-NN gen: {gen_s:.1f}s | CSR sparse-core: {sparse.memory_mb:.2f} MB")
    print(f"  CSR request payload: {csr_mb:.2f} MB   (original augmented-dense: ~{dense_mb:.0f} MB)")
    passed_payload = csr_mb < PAYLOAD_LIMIT_MB
    print(f"  PAYLOAD {'PASS' if passed_payload else 'FAIL'} (< {PAYLOAD_LIMIT_MB:.0f} MB) "
          f"vs original FAIL ({dense_mb:.0f} MB > 2000)")

    # submit -> confirm the server ACCEPTS the payload (the exact thing that failed before)
    try:
        r = requests.post(f"{BASE}/cuopt/request", data=payload,
                          headers={"Content-Type": "application/json", "CLIENT-VERSION": "custom"},
                          timeout=120)
        print(f"  submit HTTP status: {r.status_code}  ({'ACCEPTED' if r.status_code == 200 else r.text[:120]})")
        submit_ok = r.status_code == 200
    except Exception as e:
        print(f"  submit error: {repr(e)[:150]}")
        submit_ok = False
    return {"stops": num_stops, "k": k, "csr_mb": round(csr_mb, 3),
            "dense_mb": round(dense_mb, 1), "payload_pass": passed_payload, "submit_ok": submit_ok}


if __name__ == "__main__":
    results = []
    for k in [10, 20, 50]:
        results.append(run(10000, k))
    print("\n=== SUMMARY (Phase-4 CSR mode) ===")
    print(f"{'stops':>7} {'K':>4} {'CSR MB':>10} {'orig dense MB':>14} {'payload':>9} {'submit':>8}")
    for r in results:
        print(f"{r['stops']:>7} {r['k']:>4} {r['csr_mb']:>10} {r['dense_mb']:>14} "
              f"{'PASS' if r['payload_pass'] else 'FAIL':>9} {'200' if r['submit_ok'] else 'ERR':>8}")
    print("CSR_BENCH_DONE")
