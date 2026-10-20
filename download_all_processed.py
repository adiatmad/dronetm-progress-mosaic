from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from gdal_mosaic import GDALProcessingError, build_gdal_mosaic
from mosaic_core import (
    COMPLETED_DEFAULT,
    DroneTMError,
    create_preview,
    download_orthophoto,
    fetch_tasks,
    is_valid_raster,
    parse_project_slug,
    resolve_project_uuid,
    safe_id,
    write_task_report,
)

DEFAULT_BASE_URL = "https://api.drone.hotosm.org"
DEFAULT_TASKS_PATH = "/tasks/states/{project_id}"
DEFAULT_PHOTO_PATH = "/projects/odm/export/{project_id}/{task_id}/orthophoto/"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download processed DroneTM orthophotos and build a local progress mosaic."
    )
    parser.add_argument(
        "--project-url",
        default="https://drone.hotosm.org/projects/duut-tasi-50m-metinaro",
        help="DroneTM project page URL",
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", default="", help="Bearer token; omit to be prompted securely")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output-dir", default="")
    parser.add_argument(
        "--no-mosaic",
        action="store_true",
        help="Only download orthophotos; do not build mosaic or preview",
    )
    parser.add_argument(
        "--target-crs",
        default="",
        help="Explicit target CRS (e.g. EPSG:32748) when reprojection is needed; never guessed",
    )
    args = parser.parse_args()

    token = args.token.strip() or getpass.getpass(
        "DroneTM bearer token (press Enter if not required): "
    ).strip()
    slug = parse_project_slug(args.project_url)
    project_key = safe_id(slug)
    project_dir = Path(args.output_dir) if args.output_dir else Path("data") / f"project_{project_key}"
    photo_dir = project_dir / "orthophotos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    report_path = project_dir / "task_report.csv"
    mosaic_path = project_dir / "mosaic.tif"
    vrt_path = project_dir / "mosaic.vrt"
    preview_path = project_dir / "preview.png"
    oam_dir = project_dir / "oam_preparation"
    readiness_report_path = oam_dir / "readiness_report.json"
    gdalinfo_report_path = oam_dir / "gdalinfo.json"

    print(f"Project: {slug}")
    print("Resolving project ID and loading task states...")
    project_uuid = resolve_project_uuid(args.base_url, slug, token, args.timeout)
    tasks, _ = fetch_tasks(
        args.base_url, project_uuid, DEFAULT_TASKS_PATH, token, args.timeout
    )

    completed = [
        task for task in tasks
        if task.get("status", "").strip().upper() in COMPLETED_DEFAULT
        or any(word in task.get("status", "").upper() for word in ("FINISH", "COMPLETE", "DONE"))
    ]
    if not completed:
        print("No tasks matched the default completed/processed status rules.")
        print("Statuses returned by DroneTM:")
        for status in sorted({t.get("status", "") or "(blank)" for t in tasks}):
            print(f"  - {status}")
        return 2

    print(f"Found {len(tasks)} task records; downloading/checking {len(completed)} completed/processed tasks.")
    report_rows = []
    succeeded = 0
    downloaded = 0
    reused = 0
    failed = 0
    for index, task in enumerate(completed, 1):
        task_id = task["task_id"]
        destination = photo_dir / f"task_{safe_id(task_id)}.tif"
        print(f"[{index}/{len(completed)}] Task {task_id} ({task.get('status') or 'status unknown'})")
        ok, message = download_orthophoto(
            args.base_url,
            project_uuid,
            task_id,
            DEFAULT_PHOTO_PATH,
            destination,
            token,
            timeout=max(args.timeout, 90),
        )
        result = "FAILED"
        if ok and message.startswith("Reused cached"):
            result = "REUSED"
            reused += 1
        elif ok:
            result = "DOWNLOADED"
            downloaded += 1
        else:
            failed += 1
        print(f"    {result}: {message}")
        succeeded += int(ok)
        report_rows.append({
            "task_id": task_id,
            "status": task.get("status", ""),
            "selected": True,
            "result": result,
            "download_ok": ok,
            "message": message,
            "file_path": str(destination.resolve()) if ok else "",
        })

    write_task_report(report_rows, report_path)
    print(f"\nFinished: {succeeded}/{len(completed)} orthophotos available.")
    print(f"This run: {downloaded} newly downloaded; {reused} reused from cache; {failed} still unavailable.")
    print("Failed tasks are retried automatically the next time you run this command; successful cached GeoTIFFs are not downloaded again.")
    print(f"Orthophotos: {photo_dir.resolve()}")
    print(f"Task report: {report_path.resolve()}")

    if args.no_mosaic:
        print("Mosaic step skipped (--no-mosaic).")
        return 0 if succeeded == len(completed) else 1

    available_paths = [
        photo_dir / f"task_{safe_id(task['task_id'])}.tif"
        for task in completed
        if is_valid_raster(photo_dir / f"task_{safe_id(task['task_id'])}.tif")
    ]
    if not available_paths:
        print("No valid GeoTIFFs are available; cannot build a mosaic.")
        return 1

    print(f"\nBuilding GDAL VRT and Cloud Optimized GeoTIFF from {len(available_paths)} valid orthophotos...")
    try:
        summary = build_gdal_mosaic(
            available_paths,
            vrt_path,
            mosaic_path,
            readiness_report_path,
            gdalinfo_report_path,
            target_crs=args.target_crs or None,
        )
        create_preview(mosaic_path, preview_path)
        print("GDAL mosaic built and validated.")
        print(f"VRT: {vrt_path.resolve()}")
        print(f"Cloud Optimized GeoTIFF: {mosaic_path.resolve()}")
        print(f"Preview: {preview_path.resolve()}")
        print(f"GDAL metadata: {gdalinfo_report_path.resolve()}")
        print(f"OAM preparation report (review required): {readiness_report_path.resolve()}")
        print(
            f"Dimensions: {summary['width']:,} x {summary['height']:,} px; "
            f"bands: {summary['bands']}; CRS: {summary['crs']}; "
            f"source orthophotos: {summary['source_count']}; "
            f"size: {summary['size_bytes'] / 1048576:.1f} MiB; "
            f"COG layout: {summary['cog_layout']}"
        )
    except (DroneTMError, GDALProcessingError) as exc:
        print(f"MOSAIC FAILED: {exc}")
        print("Downloaded orthophotos and task_report.csv are preserved.")
        print("No OAM upload was attempted.")
        return 1

    if succeeded != len(completed):
        print("Mosaic was built from available files, but one or more task orthophotos remain unavailable; see task_report.csv.")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DroneTMError, GDALProcessingError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
