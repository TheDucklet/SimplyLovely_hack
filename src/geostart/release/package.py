import zipfile
from pathlib import Path

from geostart.quality.checks import errors, run_checks
from geostart.quality.report import render_report
from geostart.release.manifest import build_manifest, file_hash, read_manifest, write_manifest
from geostart.release.rebuild import MANIFEST_NAME

QUALITY_NAME = "quality.md"


class QualityError(RuntimeError):
    pass


def package(root: Path, output_dir: Path, with_basemap: bool, force: bool = False) -> Path:
    quality = run_checks(root)
    if errors(quality) and not force:
        raise QualityError(
            f"Ошибок качества данных {len(errors(quality))}, архив не собран."
            " Подробности выводит python -m geostart.quality check"
        )
    manifest = build_manifest(root)
    if not with_basemap:
        manifest["files"] = {
            name: digest for name, digest in manifest["files"].items() if "basemap/" not in name
        }
    write_manifest(manifest, root / MANIFEST_NAME)
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"geostart_data_{manifest['version']}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(root / MANIFEST_NAME, f"data/{MANIFEST_NAME}")
        bundle.writestr(f"data/{QUALITY_NAME}", render_report(root, quality))
        for name in manifest["files"]:
            source = root / name
            stored = zipfile.ZIP_STORED if name.endswith(".pmtiles") else zipfile.ZIP_DEFLATED
            bundle.write(source, f"data/{name}", compress_type=stored)
    checksum = archive.with_name(archive.name + ".sha256")
    checksum.write_text(f"{file_hash(archive)}  {archive.name}\n", encoding="utf-8")
    return archive


def verify(root: Path) -> list[str]:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.exists():
        return [f"нет {manifest_path}"]
    problems = []
    for name, digest in read_manifest(manifest_path)["files"].items():
        path = root / name
        if not path.exists():
            problems.append(f"нет файла {name}")
        elif file_hash(path) != digest:
            problems.append(f"контрольная сумма не совпадает у {name}")
    return problems
