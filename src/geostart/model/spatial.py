from dataclasses import dataclass
from math import ceil

import h3
import numpy as np
import pandas as pd

from geostart.model.demand import GRID_RADIUS_MARGIN, distances_m

PARENT_LEVELS = 2


@dataclass(frozen=True)
class CellNeighborhood:
    coordinates: np.ndarray
    parents: tuple[str, ...]
    neighbors: dict[str, np.ndarray]
    max_distance_m: float

    @classmethod
    def build(cls, cells: list[str], radius_m: float) -> "CellNeighborhood":
        resolution = max(0, h3.get_resolution(cells[0]) - PARENT_LEVELS)
        parents = tuple(h3.cell_to_parent(cell, resolution) for cell in cells)
        groups = pd.Series(np.arange(len(cells))).groupby(pd.Series(parents), sort=False).indices
        radius = ceil(radius_m / h3.average_hexagon_edge_length(resolution, unit="m")) + GRID_RADIUS_MARGIN
        neighbors = {}
        for parent in groups:
            selected = [groups[item] for item in h3.grid_disk(parent, radius) if item in groups]
            neighbors[parent] = np.sort(np.concatenate(selected))
        return cls(np.array([h3.cell_to_latlng(cell) for cell in cells]), parents, neighbors, radius_m)

    def edges(self, source_indices: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        parents = pd.Series([self.parents[index] for index in source_indices])
        groups = pd.Series(source_indices).groupby(parents, sort=False)
        edges = []
        for parent, sources in groups:
            neighbors = self.neighbors[parent]
            origins = np.repeat(sources.to_numpy(), len(neighbors))
            destinations = np.tile(neighbors, len(sources))
            distances = distances_m(self.coordinates[origins], self.coordinates[destinations])
            inside = distances <= self.max_distance_m
            edges.append((origins[inside], destinations[inside], distances[inside]))
        origins, destinations, distances = (
            np.concatenate([edge[index] for edge in edges]) for index in range(3)
        )
        order = np.lexsort((destinations, origins))
        return origins[order].astype(np.int64), destinations[order].astype(np.int64), distances[order]
