from __future__ import annotations

import argparse
import gzip
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from pmtiles.tile import Compression, TileType, deserialize_directory, deserialize_header, zxy_to_tileid
from pmtiles.writer import Writer
from shapely.geometry import shape

from geostart.config import load_cities
from geostart.settings import data_dir

BUILD = "20261117"
SOURCE_URL = f"https://build.protomaps.com/{BUILD}.pmtiles"
MAX_ZOOM = 14
MARGIN_DEG = 0.02
CHUNK_BYTES = 20_000
THREADS = 32
ATTEMPTS = 12
BATCH_BYTES = 20_000_000
HEADER_BYTES = 16_384


class RangeReader:
    def __init__(self, url: str, threads: int) -> None:
        self.url = url
        self.pool = ThreadPoolExecutor(threads)
        self.client = httpx.Client(
            timeout=httpx.Timeout(15, connect=10), limits=httpx.Limits(max_keepalive_connections=0)
        )
        self.retries = 0

    def chunk(self, start: int, end: int) -> bytes:
        for attempt in range(ATTEMPTS):
            try:
                response = self.client.get(self.url, headers={"Range": f"bytes={start}-{end - 1}"})
                if response.status_code == 206 and len(response.content) == end - start:
                    return response.content
            except httpx.HTTPError:
                pass
            self.retries += 1
            time.sleep(min(10.0, 0.5 * (attempt + 1)))
        raise OSError(f"не удалось скачать байты {start}-{end}")

    def read(self, spans: list[tuple[int, int]]) -> list[bytes]:
        pieces = [
            (begin, min(begin + CHUNK_BYTES, start + length))
            for start, length in spans
            for begin in range(start, start + length, CHUNK_BYTES)
        ]
        loaded = dict(zip(pieces, self.pool.map(lambda piece: self.chunk(*piece), pieces), strict=True))
        return [
            b"".join(
                loaded[(begin, min(begin + CHUNK_BYTES, start + length))]
                for begin in range(start, start + length, CHUNK_BYTES)
            )
            for start, length in spans
        ]


def city_boxes(margin: float) -> list[tuple[float, float, float, float]]:
    boxes = []
    for city in load_cities():
        path = data_dir() / "processed" / city.code / "boundary.geojson"
        geometry = json.loads(path.read_text(encoding="utf-8"))
        if geometry.get("type") == "FeatureCollection":
            geometry = geometry["features"][0]["geometry"]
        elif geometry.get("type") == "Feature":
            geometry = geometry["geometry"]
        west, south, east, north = shape(geometry).bounds
        boxes.append((west - margin, south - margin, east + margin, north + margin))
    return boxes


def tile_x(lon: float, zoom: int) -> int:
    return int((lon + 180) / 360 * 2**zoom)


def tile_y(lat: float, zoom: int) -> int:
    rad = math.radians(lat)
    return int((1 - math.log(math.tan(rad) + 1 / math.cos(rad)) / math.pi) / 2 * 2**zoom)


def wanted_tiles(boxes: list[tuple[float, float, float, float]], max_zoom: int) -> set[int]:
    return {
        zxy_to_tileid(zoom, x, y)
        for zoom in range(max_zoom + 1)
        for west, south, east, north in boxes
        for x in range(tile_x(west, zoom), tile_x(east, zoom) + 1)
        for y in range(tile_y(north, zoom), tile_y(south, zoom) + 1)
    }


def find_entry(entries: list, tile_id: int):
    low, high = 0, len(entries) - 1
    while low <= high:
        middle = (low + high) // 2
        if entries[middle].tile_id < tile_id:
            low = middle + 1
        elif entries[middle].tile_id > tile_id:
            high = middle - 1
        else:
            return entries[middle]
    if high >= 0:
        entry = entries[high]
        if entry.run_length == 0 or tile_id - entry.tile_id < entry.run_length:
            return entry
    return None


def resolve_tiles(
    reader: RangeReader, header: dict, root: list, wanted: set[int]
) -> dict[int, tuple[int, int]]:
    pending = dict.fromkeys(wanted, root)
    resolved: dict[int, tuple[int, int]] = {}
    leaves: dict[tuple[int, int], list] = {}
    while pending:
        needed: dict[tuple[int, int], list[int]] = {}
        for tile_id, entries in pending.items():
            entry = find_entry(entries, tile_id)
            if entry is None:
                continue
            if entry.run_length > 0:
                resolved[tile_id] = (entry.offset, entry.length)
            else:
                needed.setdefault((entry.offset, entry.length), []).append(tile_id)
        missing = [key for key in needed if key not in leaves]
        spans = [(header["leaf_directory_offset"] + offset, length) for offset, length in missing]
        for key, raw in zip(missing, reader.read(spans), strict=True):
            leaves[key] = deserialize_directory(raw)
        pending = {tile_id: leaves[key] for key, tile_ids in needed.items() for tile_id in tile_ids}
    return resolved


def download_blobs(
    reader: RangeReader, header: dict, blobs: list[tuple[int, int]]
) -> dict[tuple[int, int], bytes]:
    total = sum(length for _, length in blobs)
    loaded: dict[tuple[int, int], bytes] = {}
    batch: list[tuple[int, int]] = []
    for index, blob in enumerate(blobs):
        batch.append(blob)
        if sum(length for _, length in batch) >= BATCH_BYTES or index == len(blobs) - 1:
            spans = [(header["tile_data_offset"] + offset, length) for offset, length in batch]
            loaded.update(zip(batch, reader.read(spans), strict=True))
            done = sum(length for _, length in loaded)
            print(f"тайлы {done / 1e6:.1f} из {total / 1e6:.1f} МБ, повторов {reader.retries}", flush=True)
            batch = []
    return loaded


def write_archive(
    output: Path,
    resolved: dict[int, tuple[int, int]],
    blobs: dict[tuple[int, int], bytes],
    boxes: list[tuple[float, float, float, float]],
    metadata: dict,
    max_zoom: int,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(".part")
    with partial.open("wb") as stream:
        writer = Writer(stream)
        for tile_id in sorted(resolved):
            writer.write_tile(tile_id, blobs[resolved[tile_id]])
        writer.finalize(
            {
                "tile_type": TileType.MVT,
                "tile_compression": Compression.GZIP,
                "min_zoom": 0,
                "max_zoom": max_zoom,
                "min_lon_e7": int(min(box[0] for box in boxes) * 1e7),
                "min_lat_e7": int(min(box[1] for box in boxes) * 1e7),
                "max_lon_e7": int(max(box[2] for box in boxes) * 1e7),
                "max_lat_e7": int(max(box[3] for box in boxes) * 1e7),
                "center_zoom": 10,
                "center_lon_e7": int(37.6173 * 1e7),
                "center_lat_e7": int(55.7558 * 1e7),
            },
            {**metadata, "geostart:source": SOURCE_URL, "geostart:max_zoom": max_zoom},
        )
    partial.replace(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Вырезка подложки Protomaps по городам сервиса")
    parser.add_argument("--output", type=Path, default=data_dir() / "basemap" / "geostart.pmtiles")
    parser.add_argument("--max-zoom", type=int, default=MAX_ZOOM)
    parser.add_argument("--source", default=SOURCE_URL)
    parser.add_argument("--threads", type=int, default=THREADS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    started = time.time()
    reader = RangeReader(args.source, args.threads)
    (head,) = reader.read([(0, HEADER_BYTES)])
    header = deserialize_header(head[:127])
    root = deserialize_directory(head[header["root_offset"] : header["root_offset"] + header["root_length"]])
    (raw_metadata,) = reader.read([(header["metadata_offset"], header["metadata_length"])])
    metadata = json.loads(gzip.decompress(raw_metadata))
    boxes = city_boxes(MARGIN_DEG)
    wanted = wanted_tiles(boxes, args.max_zoom)
    resolved = resolve_tiles(reader, header, root, wanted)
    blobs = sorted(set(resolved.values()))
    size = sum(length for _, length in blobs) / 1e6
    print(
        f"тайлов {len(wanted)}, найдено {len(resolved)}, уникальных {len(blobs)}, {size:.1f} МБ", flush=True
    )
    if args.dry_run:
        return
    loaded = download_blobs(reader, header, blobs)
    write_archive(args.output, resolved, loaded, boxes, metadata, args.max_zoom)
    megabytes = args.output.stat().st_size / 1e6
    print(f"{args.output}: {megabytes:.1f} МБ за {time.time() - started:.0f} с", flush=True)


if __name__ == "__main__":
    main()
