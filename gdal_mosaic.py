from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any


class GDALProcessingError(RuntimeError):
    """Raised when GDAL is unavailable or a raster operation fails."""


def require_gdal_command(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise GDALProcessingError(
            f"Required GDAL command '{name}' was not found on PATH. "
            "Open OSGeo4W Shell (from the QGIS installation) and run this command there."
        )
    return executable


def run_gdal(args: list[str], *, capture_output: bool = True) -> subprocess.CompletedProcess[str]:
    require_gdal_command(args[0])
    try:
        result = subprocess.run(
            args,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=capture_output,
        )
    except OSError as exc:
        raise GDALProcessingError(f"Could not start {args[0]}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        raise GDALProcessingError(
            f"{args[0]} failed with exit code {result.returncode}"
            + (f": {detail[-4000:]}" if detail else ".")
        )
    return result


def read_gdalinfo(path: Path) -> dict[str, Any]:
    result = run_gdal(["gdalinfo", "-json", str(path)])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GDALProcessingError(f"gdalinfo returned invalid JSON for {path}.") from exc
    if not isinstance(payload, dict) or not payload.get("size"):
        raise GDALProcessingError(f"gdalinfo did not report raster dimensions for {path}.")
    if not payload.get("coordinateSystem", {}).get("wkt"):
        raise GDALProcessingError(f"Raster has no reported CRS: {path}")
    return payload


def _crs_key(info: dict[str, Any]) -> str:
    coordinate_system = info.get("coordinateSystem", {})
    authority = coordinate_system.get("id") or coordinate_system.get("ID")
    if isinstance(authority, dict) and authority.get("authority") and authority.get("code"):
        return f"{authority['authority']}:{authority['code']}"

    wkt = str(coordinate_system["wkt"]).strip()
    # Some GDAL versions omit the JSON id field but include the authority ID in the WKT.
    matches = re.findall(r'ID\["(EPSG|ESRI|OGC)",\s*"?([A-Za-z0-9._-]+)"?\]', wkt, flags=re.IGNORECASE)
    if matches:
        authority_name, code = matches[-1]
        return f"{authority_name.upper()}:{code}"
    return wkt

def _validated_info(path: Path) -> dict[str, Any]:
    info = read_gdalinfo(path)
    if len(info.get("bands", [])) < 1:
        raise GDALProcessingError(f"Raster has no bands: {path}")
    if int(info["size"][0]) <= 0 or int(info["size"][1]) <= 0:
        raise GDALProcessingError(f"Raster has invalid dimensions: {path}")
    return info


def _atomic_replace_outputs(staged_vrt: Path, staged_cog: Path, vrt_path: Path, cog_path: Path) -> None:
    # Both staged outputs are validated before either existing final output is replaced.
    vrt_path.parent.mkdir(parents=True, exist_ok=True)
    cog_path.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staged_vrt, vrt_path)
    try:
        os.replace(staged_cog, cog_path)
    except OSError as exc:
        raise GDALProcessingError(
            f"Could not replace final COG at {cog_path}. The new VRT may already have been installed; "
            "the previous COG was not deliberately deleted."
        ) from exc


def build_gdal_mosaic(
    source_paths: list[Path],
    vrt_path: Path,
    cog_path: Path,
    readiness_report_path: Path,
    gdalinfo_report_path: Path,
    *,
    target_crs: str | None = None,
) -> dict[str, Any]:
    """Build a VRT and physical COG using GDAL CLI, preserving old outputs until validation."""
    paths = sorted({Path(path).resolve() for path in source_paths})
    if not paths:
        raise GDALProcessingError("No input GeoTIFFs were supplied.")
    for command in ("gdalinfo", "gdalbuildvrt", "gdal_translate", "gdalwarp"):
        require_gdal_command(command)

    source_info = [_validated_info(path) for path in paths]
    source_crs = [_crs_key(info) for info in source_info]
    if target_crs:
        effective_crs = target_crs.strip()
        if not effective_crs:
            raise GDALProcessingError("The target CRS cannot be blank.")
    elif len(set(source_crs)) == 1:
        effective_crs = source_crs[0]
    else:
        raise GDALProcessingError(
            "Input orthophotos use different CRSs. No target CRS was specified, so processing stopped "
            "rather than guessing. Rerun with --target-crs (for example, EPSG:32748 only if verified "
            "as the correct project CRS)."
        )

    vrt_path = Path(vrt_path).resolve()
    cog_path = Path(cog_path).resolve()
    readiness_report_path = Path(readiness_report_path).resolve()
    gdalinfo_report_path = Path(gdalinfo_report_path).resolve()
    vrt_path.parent.mkdir(parents=True, exist_ok=True)
    cog_path.parent.mkdir(parents=True, exist_ok=True)
    readiness_report_path.parent.mkdir(parents=True, exist_ok=True)
    gdalinfo_report_path.parent.mkdir(parents=True, exist_ok=True)

    # Warped VRT inputs must outlive the temporary build directory because the final mosaic.vrt
    # references them. Use a unique persistent directory; failed runs can leave harmless orphaned
    # intermediates rather than corrupting a previous mosaic.
    persistent_warp_dir = None
    build_sources: list[Path] = []
    if target_crs or len(set(source_crs)) > 1:
        warp_root = vrt_path.parent / "warped_sources"
        warp_root.mkdir(parents=True, exist_ok=True)
        persistent_warp_dir = Path(tempfile.mkdtemp(prefix="run-", dir=str(warp_root)))
        for index, path in enumerate(paths, start=1):
            warped_vrt = persistent_warp_dir / f"warped_{index:04d}.vrt"
            run_gdal([
                "gdalwarp", "-overwrite", "-of", "VRT", "-t_srs", effective_crs,
                "-r", "bilinear", str(path), str(warped_vrt),
            ])
            _validated_info(warped_vrt)
            build_sources.append(warped_vrt)
    else:
        build_sources = paths

    with tempfile.TemporaryDirectory(prefix=".gdal-mosaic-", dir=str(vrt_path.parent)) as work_dir_text:
        work_dir = Path(work_dir_text)

        source_list = work_dir / "source_files.txt"
        source_list.write_text(
            "".join(f"{path}\n" for path in build_sources),
            encoding="utf-8",
        )
        # Stage outputs beside their final destinations: gdalbuildvrt may encode source paths
        # relative to the VRT location, so moving a VRT out of a temporary subdirectory would
        # invalidate those references.
        stage_id = uuid.uuid4().hex
        staged_vrt = vrt_path.with_name(f".{vrt_path.stem}.stage-{stage_id}.vrt")
        staged_cog = cog_path.with_name(f".{cog_path.stem}.stage-{stage_id}.tif")
        try:
            run_gdal([
                "gdalbuildvrt", "-overwrite", "-input_file_list", str(source_list), str(staged_vrt)
            ])
            vrt_info = _validated_info(staged_vrt)
            run_gdal([
                "gdal_translate", "-of", "COG",
                "-co", "COMPRESS=DEFLATE",
                "-co", "BIGTIFF=IF_SAFER",
                "-co", "OVERVIEWS=AUTO",
                str(staged_vrt), str(staged_cog),
            ])
            cog_info = _validated_info(staged_cog)
            layout = str(cog_info.get("metadata", {}).get("IMAGE_STRUCTURE", {}).get("LAYOUT", "")).upper()
            if layout != "COG":
                raise GDALProcessingError(
                    "GDAL created a GeoTIFF but did not report IMAGE_STRUCTURE LAYOUT=COG. "
                    "The existing final outputs were left in place. Check the GDAL version and COG driver."
                )
    
            width, height = map(int, cog_info["size"])
            bands = len(cog_info.get("bands", []))
            if width != int(vrt_info["size"][0]) or height != int(vrt_info["size"][1]):
                raise GDALProcessingError("The COG dimensions do not match the staged VRT dimensions.")
            if bands != len(vrt_info.get("bands", [])):
                raise GDALProcessingError("The COG band count does not match the staged VRT.")
    
            report = {
                "schema_version": 1,
                "status": "RASTER_VALIDATION_PASSED_METADATA_REVIEW_REQUIRED",
                "upload_performed": False,
                "human_review_required": True,
                "source_count": len(paths),
                "source_files": [str(path) for path in paths],
                "source_crs": sorted(set(source_crs)),
                "output_crs": effective_crs,
                "vrt": {
                    "path": str(vrt_path),
                    "size": vrt_info["size"],
                    "band_count": len(vrt_info.get("bands", [])),
                },
                "cog": {
                    "path": str(cog_path),
                    "size": cog_info["size"],
                    "band_count": bands,
                    "layout": layout,
                    "driver": cog_info.get("driverShortName"),
                    "size_bytes": staged_cog.stat().st_size,
                    "corner_coordinates": cog_info.get("cornerCoordinates"),
                },
                "checks": {
                    "all_sources_readable_and_georeferenced": True,
                    "mixed_crs_handled_explicitly": bool(target_crs or len(set(source_crs)) > 1),
                    "vrt_readable_and_georeferenced": True,
                    "cog_readable_and_georeferenced": True,
                    "cog_layout_reported_by_gdal": layout == "COG",
                    "vrt_and_cog_dimensions_match": True,
                    "vrt_and_cog_band_counts_match": True,
                },
                "metadata_to_confirm_before_oam": [
                    "title",
                    "capture date or date range",
                    "license and usage rights",
                    "provider and attribution",
                    "description and processing method",
                    "coverage footprint and spatial reference",
                    "resolution and band interpretation",
                    "duplicate/overlap check against existing imagery",
                ],
                "notes": [
                    "This report checks local raster properties only; it does not guarantee OAM acceptance.",
                    "The VRT depends on the listed source files remaining at their current paths.",
                    "No imagery or metadata was uploaded to OpenAerialMap.",
                ],
            }
            staged_report = work_dir / "readiness_report.json"
            staged_gdalinfo = work_dir / "gdalinfo.json"
            staged_report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            staged_gdalinfo.write_text(json.dumps(cog_info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            _atomic_replace_outputs(staged_vrt, staged_cog, vrt_path, cog_path)
            # Install the reports last, after the raster outputs have passed validation.
            os.replace(staged_report, readiness_report_path)
            os.replace(staged_gdalinfo, gdalinfo_report_path)
        finally:
            # Failed GDAL runs can leave large partial files; never leave those staging outputs behind.
            staged_vrt.unlink(missing_ok=True)
            staged_cog.unlink(missing_ok=True)

    return {
        "path": str(cog_path),
        "vrt_path": str(vrt_path),
        "width": width,
        "height": height,
        "bands": bands,
        "crs": effective_crs,
        "size_bytes": cog_path.stat().st_size,
        "source_count": len(paths),
        "cog_layout": layout,
        "readiness_report_path": str(readiness_report_path),
        "gdalinfo_report_path": str(gdalinfo_report_path),
    }
