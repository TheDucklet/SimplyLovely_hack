from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "docker" / "web" / "basemap" / "style.json"
SOURCE = "protomaps"
TILES_URL = "/basemap/tiles/geostart/{z}/{x}/{y}.mvt"
GLYPHS_URL = "/basemap/fonts/{fontstack}/{range}.pbf"
MAX_ZOOM = 14
FONT = ["Noto Sans Medium"]
FONT_ITALIC = ["Noto Sans Italic"]
ATTRIBUTION = "Protomaps © участники OpenStreetMap"
MINOR_PLACES = ["locality", "isolated_dwelling", "farm", "allotments"]
LABEL = ["coalesce", ["get", "name:ru"], ["get", "name"]]

COLORS = {
    "background": "#eef0ec",
    "earth": "#f4f4f1",
    "park": "#e1eadb",
    "forest": "#d9e4d2",
    "urban": "#ecebe7",
    "industrial": "#e8e6e3",
    "special": "#ebe8ec",
    "water": "#c4d3dc",
    "building": "#e2e0dc",
    "road_casing": "#d8d6d1",
    "road": "#ffffff",
    "highway": "#fbf3e2",
    "rail": "#c9c7c2",
    "boundary": "#b9b4c4",
    "label": "#55585d",
    "water_label": "#6c8797",
    "halo": "#ffffff",
}


def kinds(*values: str) -> list:
    return ["in", ["get", "kind"], ["literal", list(values)]]


def layer(layer_id: str, kind: str, source_layer: str, **parts: object) -> dict:
    spec: dict = {"id": layer_id, "type": kind, "source": SOURCE, "source-layer": source_layer}
    spec.update({key.replace("_", "-"): value for key, value in parts.items()})
    return spec


def width(*stops: float) -> list:
    return ["interpolate", ["exponential", 1.6], ["zoom"], *stops]


def road_layers() -> list[dict]:
    classes = [
        ("minor", kinds("minor_road", "other"), (12, 0.4, 14, 1.6, 18, 12)),
        ("medium", kinds("medium_road"), (10, 0.5, 14, 2.4, 18, 16)),
        ("major", kinds("major_road"), (8, 0.6, 14, 3.2, 18, 22)),
        ("highway", kinds("highway"), (6, 0.6, 14, 4.2, 18, 28)),
    ]
    casings = []
    fills = []
    for name, condition, stops in classes:
        surface = ["all", condition, ["!", ["boolean", ["get", "is_tunnel"], False]]]
        casings.append(
            layer(
                f"roads-{name}-casing",
                "line",
                "roads",
                filter=surface,
                layout={"line-cap": "round", "line-join": "round"},
                paint={"line-color": COLORS["road_casing"], "line-width": width(*_casing(stops))},
            )
        )
        fills.append(
            layer(
                f"roads-{name}",
                "line",
                "roads",
                filter=surface,
                layout={"line-cap": "round", "line-join": "round"},
                paint={
                    "line-color": COLORS["highway"] if name == "highway" else COLORS["road"],
                    "line-width": width(*stops),
                },
            )
        )
    paths = layer(
        "roads-path",
        "line",
        "roads",
        minzoom=14,
        filter=kinds("path"),
        paint={"line-color": COLORS["road_casing"], "line-width": 0.8, "line-dasharray": [2, 1.5]},
    )
    rail = layer(
        "roads-rail",
        "line",
        "roads",
        minzoom=11,
        filter=kinds("rail"),
        paint={"line-color": COLORS["rail"], "line-width": width(11, 0.6, 18, 2.4)},
    )
    return [paths, rail, *casings, *fills]


def _casing(stops: tuple[float, ...]) -> list[float]:
    return [value if index % 2 == 0 else value + 1.2 for index, value in enumerate(stops)]


def area_layers() -> list[dict]:
    return [
        layer("earth", "fill", "earth", paint={"fill-color": COLORS["earth"]}),
        layer(
            "landcover-forest",
            "fill",
            "landcover",
            filter=kinds("forest", "scrub"),
            paint={"fill-color": COLORS["forest"], "fill-opacity": 0.6},
        ),
        layer(
            "landuse-urban",
            "fill",
            "landuse",
            filter=kinds("residential", "neighbourhood", "urban_area"),
            paint={"fill-color": COLORS["urban"]},
        ),
        layer(
            "landuse-industrial",
            "fill",
            "landuse",
            filter=kinds(
                "industrial", "commercial", "railway", "military", "aerodrome", "runway", "apron", "platform"
            ),
            paint={"fill-color": COLORS["industrial"]},
        ),
        layer(
            "landuse-special",
            "fill",
            "landuse",
            filter=kinds("hospital", "school", "university", "college", "kindergarten"),
            paint={"fill-color": COLORS["special"]},
        ),
        layer(
            "landuse-park",
            "fill",
            "landuse",
            filter=kinds(
                "park",
                "garden",
                "grassland",
                "grass",
                "meadow",
                "cemetery",
                "zoo",
                "playground",
                "pitch",
                "golf_course",
                "nature_reserve",
                "national_park",
                "recreation_ground",
                "village_green",
                "allotments",
            ),
            paint={"fill-color": COLORS["park"]},
        ),
        layer(
            "landuse-forest",
            "fill",
            "landuse",
            filter=kinds("forest", "wood", "orchard", "farmland", "scrub"),
            paint={"fill-color": COLORS["forest"]},
        ),
        layer(
            "water",
            "fill",
            "water",
            filter=["==", ["geometry-type"], "Polygon"],
            paint={"fill-color": COLORS["water"]},
        ),
        layer(
            "water-line",
            "line",
            "water",
            minzoom=10,
            filter=["==", ["geometry-type"], "LineString"],
            paint={"line-color": COLORS["water"], "line-width": width(10, 0.6, 18, 6)},
        ),
        layer(
            "buildings",
            "fill",
            "buildings",
            minzoom=13,
            paint={
                "fill-color": COLORS["building"],
                "fill-opacity": ["interpolate", ["linear"], ["zoom"], 13, 0, 14.5, 1],
            },
        ),
    ]


def boundary_layers() -> list[dict]:
    return [
        layer(
            "boundaries",
            "line",
            "boundaries",
            filter=kinds("country", "region"),
            paint={"line-color": COLORS["boundary"], "line-width": 1, "line-dasharray": [3, 2]},
        )
    ]


def label_layers() -> list[dict]:
    text_paint = {
        "text-color": COLORS["label"],
        "text-halo-color": COLORS["halo"],
        "text-halo-width": 1.4,
    }
    water_paint = {**text_paint, "text-color": COLORS["water_label"]}
    water_layout = {"text-field": LABEL, "text-font": FONT_ITALIC, "text-size": 12}
    return [
        layer(
            "labels-water-line",
            "symbol",
            "water",
            minzoom=12,
            filter=["all", ["has", "name"], ["==", ["geometry-type"], "LineString"]],
            layout={**water_layout, "symbol-placement": "line"},
            paint=water_paint,
        ),
        layer(
            "labels-water-area",
            "symbol",
            "water",
            minzoom=11,
            filter=["all", ["has", "name"], ["==", ["geometry-type"], "Point"]],
            layout={**water_layout, "text-max-width": 8},
            paint=water_paint,
        ),
        layer(
            "labels-roads",
            "symbol",
            "roads",
            minzoom=13,
            filter=["all", ["has", "name"], kinds("highway", "major_road", "medium_road", "minor_road")],
            layout={
                "text-field": LABEL,
                "text-font": FONT,
                "text-size": ["interpolate", ["linear"], ["zoom"], 13, 10, 17, 13],
                "symbol-placement": "line",
                "text-max-angle": 30,
            },
            paint=text_paint,
        ),
        layer(
            "labels-neighbourhood",
            "symbol",
            "places",
            minzoom=12,
            filter=kinds("neighbourhood", "macrohood"),
            layout={
                "text-field": LABEL,
                "text-font": FONT,
                "text-size": 12,
                "text-transform": "uppercase",
                "text-letter-spacing": 0.08,
                "text-max-width": 8,
            },
            paint={**text_paint, "text-color": "#7a7d82"},
        ),
        layer(
            "labels-locality",
            "symbol",
            "places",
            filter=[
                "all",
                kinds("locality"),
                ["!", ["in", ["get", "kind_detail"], ["literal", MINOR_PLACES]]],
            ],
            layout={
                "text-field": LABEL,
                "text-font": FONT,
                "text-size": ["interpolate", ["linear"], ["zoom"], 6, 11, 12, 16],
                "text-max-width": 8,
                "symbol-sort-key": ["-", 0, ["coalesce", ["get", "population_rank"], 0]],
            },
            paint=text_paint,
        ),
    ]


def build_style(bounds: list[float] | None = None) -> dict:
    source: dict = {
        "type": "vector",
        "tiles": [TILES_URL],
        "minzoom": 0,
        "maxzoom": MAX_ZOOM,
        "attribution": ATTRIBUTION,
    }
    if bounds:
        source["bounds"] = bounds
    return {
        "version": 8,
        "name": "GeoStart offline",
        "glyphs": GLYPHS_URL,
        "sources": {SOURCE: source},
        "layers": [
            {"id": "background", "type": "background", "paint": {"background-color": COLORS["background"]}},
            *area_layers(),
            *boundary_layers(),
            *road_layers(),
            *label_layers(),
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Стиль офлайн-подложки для MapLibre")
    parser.add_argument("--output", type=Path, default=STYLE_PATH)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    style = build_style()
    args.output.write_text(json.dumps(style, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{args.output}: {len(style['layers'])} слоёв")


if __name__ == "__main__":
    main()
