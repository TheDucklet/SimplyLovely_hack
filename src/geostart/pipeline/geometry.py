import geopandas as gpd
import h3
import pandas as pd
import shapely
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.ops import polygonize, unary_union

GEOGRAPHIC_CRS = "EPSG:4326"
METRIC_CRS = "EPSG:32637"
MKAD_SNAP_TOLERANCE_DEGREES = 0.0005


class BoundaryNotFoundError(RuntimeError):
    pass


def mkad_polygon(mkad_ways: pd.DataFrame) -> Polygon:
    lines = [LineString(coordinates) for coordinates in mkad_ways["coordinates"]]
    merged = unary_union(lines).buffer(MKAD_SNAP_TOLERANCE_DEGREES).boundary
    candidates = list(polygonize(merged))
    if not candidates:
        raise BoundaryNotFoundError("Не удалось замкнуть контур МКАД по линиям OSM, проверьте выгрузку")
    return max(candidates, key=lambda polygon: polygon.area)


def admin_polygon(
    boundaries: pd.DataFrame, name: str, admin_levels: tuple[str, ...]
) -> Polygon | MultiPolygon:
    matched = boundaries[(boundaries["name"] == name) & boundaries["admin_level"].isin(admin_levels)]
    if matched.empty:
        raise BoundaryNotFoundError(f"Административная граница «{name}» не найдена в выгрузке OSM")
    largest = matched.assign(geometry=shapely.from_wkb(matched["wkb"]))
    largest = largest.assign(area=shapely.area(largest["geometry"])).sort_values("area", ascending=False)
    return largest.iloc[0]["geometry"]


def hex_cells(boundary: Polygon | MultiPolygon, resolution: int) -> list[str]:
    return sorted(h3.geo_to_cells(boundary.__geo_interface__, resolution))


def hex_frame(cells: list[str]) -> gpd.GeoDataFrame:
    centers = [h3.cell_to_latlng(cell) for cell in cells]
    polygons = [Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(cell)]) for cell in cells]
    return gpd.GeoDataFrame(
        {"h3": cells, "lat": [lat for lat, _ in centers], "lon": [lon for _, lon in centers]},
        geometry=polygons,
        crs=GEOGRAPHIC_CRS,
    )


def points_frame(frame: pd.DataFrame, lon_column: str = "lon", lat_column: str = "lat") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        frame, geometry=gpd.points_from_xy(frame[lon_column], frame[lat_column]), crs=GEOGRAPHIC_CRS
    )
