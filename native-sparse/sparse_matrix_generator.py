#!/usr/bin/env python3
"""
Sparse Matrix Generator Module
Generate K-nearest neighbor sparse matrices for massive payload reduction.

Full matrix: N × N entries
Sparse matrix (K=20): N × K entries

10,000 stops:
  Full: 100M × 8 bytes = 800 MB
  Sparse: 10,000 × 20 × 8 bytes = 1.6 MB (500x reduction!)
"""

import numpy as np
from typing import Dict, List, Tuple, Any
from scipy.spatial import cKDTree
from dataclasses import dataclass

@dataclass
class SparseMatrixData:
    """Container for sparse matrix representation."""
    num_stops: int
    k_neighbors: int
    neighbor_indices: np.ndarray  # Shape: (num_stops, k_neighbors)
    neighbor_distances: np.ndarray  # Shape: (num_stops, k_neighbors)
    precision: str
    memory_mb: float
    full_matrix_mb: float
    reduction_factor: float

def haversine_distance(
    lat1: float, lon1: float,
    lat2: float, lon2: float
) -> float:
    """Calculate Haversine distance between two points."""
    r = 6371.0  # Earth radius in km

    lat1_rad = np.radians(lat1)
    lat2_rad = np.radians(lat2)
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)

    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2) ** 2
    c = 2 * np.arcsin(np.sqrt(a))

    return r * c

def generate_sparse_matrix(
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    k_neighbors: int = 20,
    precision: str = "FP32"
) -> SparseMatrixData:
    """
    Generate sparse distance matrix using K nearest neighbors.

    Uses KD-tree for efficient nearest neighbor search.

    Args:
        latitudes: Array of stop latitudes
        longitudes: Array of stop longitudes
        k_neighbors: Number of nearest neighbors per stop
        precision: "FP32" or "FP64"

    Returns:
        SparseMatrixData containing neighbor indices and distances
    """
    num_stops = len(latitudes)
    dtype = np.float32 if precision == "FP32" else np.float64
    bytes_per_element = 4 if precision == "FP32" else 8

    # Build KD-tree for efficient neighbor search
    # Note: KD-tree uses Euclidean distance, we'll compute actual Haversine after
    coordinates = np.column_stack([latitudes, longitudes])
    tree = cKDTree(coordinates)

    # Find K+1 neighbors (including self)
    k_search = min(k_neighbors + 1, num_stops)
    _, indices = tree.query(coordinates, k=k_search)

    # Initialize arrays
    neighbor_indices = np.zeros((num_stops, k_neighbors), dtype=np.int32)
    neighbor_distances = np.zeros((num_stops, k_neighbors), dtype=dtype)

    # Compute actual Haversine distances to neighbors
    for i in range(num_stops):
        neighbor_count = 0
        for j in indices[i]:
            if j == i:  # Skip self
                continue
            if neighbor_count >= k_neighbors:
                break

            dist = haversine_distance(
                latitudes[i], longitudes[i],
                latitudes[j], longitudes[j]
            )
            neighbor_indices[i, neighbor_count] = j
            neighbor_distances[i, neighbor_count] = dist
            neighbor_count += 1

    # Calculate memory usage
    sparse_memory_mb = (
        (num_stops * k_neighbors * 4) +  # Indices (int32)
        (num_stops * k_neighbors * bytes_per_element)  # Distances
    ) / (1024 * 1024)

    full_matrix_mb = (num_stops * num_stops * bytes_per_element) / (1024 * 1024)
    reduction = full_matrix_mb / sparse_memory_mb if sparse_memory_mb > 0 else 0

    return SparseMatrixData(
        num_stops=num_stops,
        k_neighbors=k_neighbors,
        neighbor_indices=neighbor_indices,
        neighbor_distances=neighbor_distances,
        precision=precision,
        memory_mb=sparse_memory_mb,
        full_matrix_mb=full_matrix_mb,
        reduction_factor=reduction
    )

def sparse_to_cuopt_format(
    sparse_data: SparseMatrixData,
    include_depot: bool = True
) -> Dict[str, Any]:
    """
    Convert sparse matrix to cuOpt-compatible format.

    For cuOpt, we need to provide distances in a format that
    allows the solver to understand connectivity.

    Note: cuOpt may require special handling for sparse matrices.
    This function creates a hybrid format.
    """
    num_stops = sparse_data.num_stops
    k = sparse_data.k_neighbors

    # Create sparse representation
    # Format: For each location, list of (neighbor_index, distance) pairs
    sparse_cost_matrix = {}
    sparse_time_matrix = {}

    for i in range(num_stops):
        neighbors = {}
        time_neighbors = {}

        for j in range(k):
            neighbor_idx = int(sparse_data.neighbor_indices[i, j])
            distance = float(sparse_data.neighbor_distances[i, j])
            travel_time = distance / 30 * 3600  # 30 km/h average

            neighbors[str(neighbor_idx)] = distance
            time_neighbors[str(neighbor_idx)] = travel_time

        # Always include depot (index 0) if not already included
        if include_depot and i != 0 and "0" not in neighbors:
            depot_dist = haversine_distance(
                0, 0,  # Will be computed properly
                0, 0
            )
            # We need actual depot coordinates here
            # For now, use the first location as depot

        sparse_cost_matrix[str(i)] = neighbors
        sparse_time_matrix[str(i)] = time_neighbors

    return {
        "cost_matrix_sparse": sparse_cost_matrix,
        "time_matrix_sparse": sparse_time_matrix,
        "is_sparse": True,
        "k_neighbors": k
    }

def create_augmented_full_matrix(
    sparse_data: SparseMatrixData,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
    fallback_distance: float = 1000.0
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Create full matrix from sparse data with fallback for non-neighbors.

    For stops that aren't K-nearest neighbors, we use a large
    fallback distance to discourage those routes while keeping
    the matrix valid for cuOpt.

    Args:
        sparse_data: Sparse matrix data
        latitudes: Stop latitudes
        longitudes: Stop longitudes
        fallback_distance: Distance to use for non-neighbors (km)

    Returns:
        Tuple of (cost_matrix, time_matrix)
    """
    n = sparse_data.num_stops
    dtype = np.float32 if sparse_data.precision == "FP32" else np.float64

    # Initialize with fallback distance
    cost_matrix = np.full((n, n), fallback_distance, dtype=dtype)
    np.fill_diagonal(cost_matrix, 0)  # Zero diagonal

    # Fill in actual distances for neighbors
    for i in range(n):
        for j in range(sparse_data.k_neighbors):
            neighbor_idx = sparse_data.neighbor_indices[i, j]
            distance = sparse_data.neighbor_distances[i, j]
            cost_matrix[i, neighbor_idx] = distance
            # Make symmetric
            cost_matrix[neighbor_idx, i] = distance

    # Time matrix (30 km/h average)
    time_matrix = cost_matrix / 30 * 3600

    return cost_matrix, time_matrix

def analyze_connectivity(sparse_data: SparseMatrixData) -> Dict[str, Any]:
    """
    Analyze the connectivity of the sparse graph.
    Checks if all stops are reachable from depot.
    """
    from collections import deque

    n = sparse_data.num_stops
    visited = set()
    queue = deque([0])  # Start from depot
    visited.add(0)

    # BFS to find all reachable nodes
    while queue:
        node = queue.popleft()
        for neighbor_idx in sparse_data.neighbor_indices[node]:
            if neighbor_idx not in visited:
                visited.add(neighbor_idx)
                queue.append(neighbor_idx)

    unreachable = set(range(n)) - visited

    return {
        "total_stops": n,
        "reachable_from_depot": len(visited),
        "unreachable_stops": len(unreachable),
        "is_fully_connected": len(unreachable) == 0,
        "unreachable_indices": list(unreachable)[:10]  # First 10 only
    }

def print_sparse_stats(sparse_data: SparseMatrixData):
    """Print statistics about the sparse matrix."""

    print("\n" + "="*60)
    print("SPARSE MATRIX STATISTICS")
    print("="*60)
    print(f"Number of stops: {sparse_data.num_stops:,}")
    print(f"K neighbors: {sparse_data.k_neighbors}")
    print(f"Precision: {sparse_data.precision}")
    print("-"*40)
    print(f"Sparse matrix memory: {sparse_data.memory_mb:.2f} MB")
    print(f"Full matrix would be: {sparse_data.full_matrix_mb:.2f} MB")
    print(f"Reduction factor: {sparse_data.reduction_factor:.0f}x")
    print("="*60)

if __name__ == "__main__":
    # Test sparse matrix generation
    print("Testing Sparse Matrix Generator...")

    # Generate test locations
    np.random.seed(42)
    num_stops = 10000
    latitudes = np.random.uniform(33.2, 33.8, num_stops)
    longitudes = np.random.uniform(-112.3, -111.7, num_stops)

    print(f"\nGenerating sparse matrix for {num_stops:,} stops...")

    for k in [10, 20, 50]:
        sparse_data = generate_sparse_matrix(
            latitudes, longitudes,
            k_neighbors=k,
            precision="FP32"
        )

        print_sparse_stats(sparse_data)

        # Check connectivity
        connectivity = analyze_connectivity(sparse_data)
        print(f"Connectivity: {connectivity['reachable_from_depot']}/{connectivity['total_stops']} "
              f"reachable from depot")
