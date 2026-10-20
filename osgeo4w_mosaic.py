from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mosaic_core import DroneTMError, create_preview, is_valid_raster, parse_project_slug, safe_id


def run_checked(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one GDAL command and surface its output on failure."""
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise DroneTMError(
            f"Required command not found: {command[0]}. Run this from OSGeo4W Shell "
            "and confirm the GDAL command-line tools are installed."
        ) from exc
    if result.returncode:
        details = (result.stderr or result.stdout or "No command output").strip()
        raise DroneTMError(f"Command failed ({result.returncode}): {command[0]}\n{details}")
    return result


def gdal_info(path: Path) -> dict[str, Any]:
    result = run_checked(["gdalinfo", "-json", str(path)])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise DroneTMError(f"gdalinfo did not return valid JSON for {path}") from exc
    if not payload.get("size") or not payload.get("bands") or not payload.get("coordinateSystem", {}).get("wkt"):
        raise DroneTMError(f"Raster is missing size, bands, or CRS: {path}")
    return payload


def crs_key(info: dict[str, Any]) -> str:
    cs = info.get("coordinateSystem", {})
    authority = cs.get("dataAxisToSRSAxisMapping")
    # WKT is the fallback when GDAL does not expose an authority identifier.
    return str(cs.get("wkt", ""))


def target_srs(info: dict[str, Any]) -> str:
    cs = info.get("coordinateSystem", {})
    ids = cs.get("id", {})
    if ids.get("authority") and ids.get("code") is not None:
        return f"{ids['authority']}:{ids['code']}"
    wkt = cs.get("wkt")
    if not wkt:
        raise DroneTMError("Cannot determine target CRS from the first valid orthophoto.")
    return wkt


def build_gdal_outputs(project_dir: Path, source_paths: list[Path]) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    project_dir.mkdir(parents=True, exist_ok=True)
    valid_paths = [p.resolve() for p in source_paths if is_valid_raster(p)]
    if not valid_paths:
        raise DroneTMError("No valid cached orthophotos are available for mosaicking.")

    infos = [(path, gdal_info(path)) for path in valid_paths]
    first_crs = crs_key(infos[0][1])
    srs = target_srs(infos[0][1])
    work_dir = project_dir / "gdal_work"
    warped_dir = work_dir / "warped"
    warped_dir.mkdir(parents=True, exist_ok=True)
    vrt_sources: list[Path] = []
    for index, (path, info) in enumerate(infos):
        if crs_key(info) == first_crs:
            vrt_sources.append(path)
            continue
        warped = warped_dir / f"warped_{index:04d}.vrt"
        temporary = warped.with_suffix(".part.vrt")
        run_checked([
            "gdalwarp", "-overwrite", "-of", "VRT", "-t_srs", srs,
            "-r", "bilinear", str(path), str(temporary),
        ])
        gdal_info(temporary)
        os.replace(temporary, warped)
        vrt_sources.append(warped.resolve())

    vrt_path = project_dir / "mosaic.vrt"
    vrt_temporary = project_dir / "mosaic.part.vrt"
    vrt_temporary.unlink(missing_ok=True)
    run_checked(["gdalbuildvrt", "-overwrite", "-resolution", "highest",
                 str(vrt_temporary), *[str(p) for p in vrt_sources]])
    vrt_info = gdal_info(vrt_temporary)
    cog_path = project_dir / "mosaic.tif"
    cog_temporary = project_dir / "mosaic.part.tif"
    cog_temporary.unlink(missing_ok=True)
    try:
        run_checked([
            "gdal_translate", "-of", "COG", "-co", "COMPRESS=DEFLATE",
            "-co", "BIGTIFF=IF_SAFER", "-co", "OVERVIEWS=AUTO",
            str(vrt_temporary), str(cog_temporary),
        ])
        cog_info = gdal_info(cog_temporary)
        layout = cog_info.get("metadata", {}).get("IMAGE_STRUCTURE", {}).get("LAYOUT", "")
        if layout.upper() != "COG":
            raise DroneTMError(
                "GDAL created an output but gdalinfo did not report IMAGE_STRUCTURE:LAYOUT=COG. "
                "The existing mosaic.tif was not replaced."
            )
        if cog_info.get("size") != vrt_info.get("size"):
            raise DroneTMError("COG dimensions differ from the VRT; refusing to publish outputs.")
        os.replace(vrt_temporary, vrt_path)
        os.replace(cog_temporary, cog_path)
    except Exception:
        cog_temporary.unlink(missing_ok=True)
        vrt_temporary.unlink(missing_ok=True)
        raise

    preview = create_preview(cog_path, project_dir / "preview.png")
    prep_dir = project_dir / "oam_preparation"
    prep_dir.mkdir(parents=True, exist_ok=True)
    (prep_dir / "gdalinfo.json").write_text(
        json.dumps(cog_info, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    readiness = {
        "status": "LOCAL_VALIDATION_COMPLETE_REVIEW_REQUIRED",
        "upload_performed": False,
        "cog_layout_verified": layout.upper() == "COG",
        "source_count": len(valid_paths),
        "cog_path": str(cog_path),
        "vrt_path": str(vrt_path),
        "metadata_review_required": [
            "title and description",
            "capture date or date range",
            "license and attribution",
            "geographic extent and CRS suitability",
            "source project/task provenance",
            "OAM-specific upload requirements at time of submission",
        ],
        "note": "This report records local raster checks only; it does not guarantee OAM acceptance.",
    }
    (prep_dir / "readiness_report.json").write_text(
        json.dumps(readiness, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return {
        "source_count": len(valid_paths),
        "vrt": str(vrt_path),
        "cog": str(cog_path),
        "preview": str(preview),
        "width": cog_info["size"][0],
        "height": cog_info["size"][1],
        "bands": len(cog_info["bands"]),
        "crs": srs,
        "size_bytes": cog_path.stat().st_size,
        "cog_layout": layout,
        "oam_report": str(prep_dir / "readiness_report.json"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download DroneTM orthophotos, then build a GDAL VRT and validated COG in OSGeo4W Shell."
    )
    parser.add_argument("--project-url", default="https://drone.hotosm.org/projects/duut-tasi-50m-metinaro")
    parser.add_argument("--base-url", default="https://api.drone.hotosm.org")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--token", default="", help=argparse.SUPPRESS)
    args = parser.parse_args()

    slug = parse_project_slug(args.project_url)
    project_dir = Path(args.output_dir) if args.output_dir else Path("data") / f"project_{safe_id(slug)}"
    downloader = Path(__file__).with_name("download_all_processed.py")
    command = [
        sys.executable, str(downloader), "--project-url", args.project_url,
        "--base-url", args.base_url, "--timeout", str(args.timeout),
        "--output-dir", str(project_dir), "--no-mosaic",
    ]
    if args.token:
        command.extend(["--token", args.token])
    print("Step 1/2: downloading/checking orthophotos (valid cached files are reused)...", flush=True)
    download = subprocess.run(command, check=False)
    report = project_dir / "task_report.csv"
    photo_dir = project_dir / "orthophotos"
    if not report.is_file() or not photo_dir.is_dir():
        print("Download stage did not produce the expected task report/cache. GDAL processing stopped.")
        return download.returncode or 1
    paths = sorted(photo_dir.glob("*.tif"))
    valid = [p for p in paths if is_valid_raster(p)]
    if not valid:
        print("No valid orthophotos found. GDAL processing stopped.")
        return 1

    print(f"Step 2/2: building VRT and COG from {len(valid)} valid cached orthophotos...", flush=True)
    try:
        summary = build_gdal_outputs(project_dir, valid)
    except (DroneTMError, OSError) as exc:
        print(f"GDAL PROCESSING FAILED: {exc}")
        print("Cached orthophotos and task_report.csv were preserved.")
        return 1
    print("GDAL outputs validated.")
    print(f"VRT: {summary['vrt']}")
    print(f"COG: {summary['cog']}")
    print(f"Preview: {summary['preview']}")
    print(f"Dimensions: {summary['width']:,} x {summary['height']:,}; bands: {summary['bands']}; CRS: {summary['crs']}")
    print(f"COG size: {summary['size_bytes'] / 1048576:.1f} MiB; GDAL layout: {summary['cog_layout']}")
    print(f"OAM preparation report: {summary['oam_report']}")
    print("No OpenAerialMap upload was attempted.")
    return 0 if download.returncode == 0 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DroneTMError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
