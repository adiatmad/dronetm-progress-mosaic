from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from mosaic_core import (
    COMPLETED_DEFAULT,
    DroneTMError,
    build_mosaic,
    create_preview,
    download_orthophoto,
    fetch_tasks,
    is_valid_raster,
    parse_project_slug,
    resolve_project_uuid,
    safe_id,
    write_task_report,
)

DEFAULT_PROJECT_URL = "https://drone.hotosm.org/projects/duut-tasi-50m-metinaro"
DEFAULT_BASE_URL = "https://api.drone.hotosm.org"
TASKS_PATH = "/tasks/states/{project_id}"
PHOTO_PATH = "/projects/odm/export/{project_id}/{task_id}/orthophoto/"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download all completed DroneTM task orthophotos and build a local progress mosaic."
    )
    parser.add_argument("--project-url", default=DEFAULT_PROJECT_URL, help="DroneTM project page URL")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="DroneTM API base URL")
    parser.add_argument("--token", default=None, help="Bearer token (prefer the interactive prompt to avoid shell history)")
    parser.add_argument("--timeout", type=int, default=180, help="Request timeout in seconds (default: 180)")
    parser.add_argument("--no-mosaic", action="store_true", help="Download orthophotos but skip mosaic generation")
    args = parser.parse_args()

    try:
        slug = parse_project_slug(args.project_url)
        token = args.token if args.token is not None else getpass.getpass(
            "DroneTM bearer token (press Enter if not required): "
        )
        print(f"Project: {slug}")
        print("Resolving project ID...")
        project_uuid = resolve_project_uuid(args.base_url.rstrip("/"), slug, token, args.timeout)
        tasks, _ = fetch_tasks(args.base_url.rstrip("/"), project_uuid, TASKS_PATH, token, args.timeout)

        completed = [
            task for task in tasks
            if (task.get("status") or "").strip().upper() in COMPLETED_DEFAULT
            or any(word in (task.get("status") or "").strip().upper() for word in ("FINISH", "COMPLETE", "DONE"))
        ]
        if not completed:
            print(f"No completed/processed tasks found among {len(tasks)} task records.")
            print("Observed statuses:", ", ".join(sorted({(t.get("status") or "(blank)") for t in tasks})))
            return 2

        project_dir = Path("data") / ("project_" + safe_id(slug))
        photo_dir = project_dir / "orthophotos"
        photo_dir.mkdir(parents=True, exist_ok=True)
        report_path = project_dir / "task_report.csv"
        rows = []
        total = len(completed)
        print(f"Found {total} completed/processed tasks. Downloading (valid cached GeoTIFFs are reused)...")

        for index, task in enumerate(completed, start=1):
            task_id = str(task["task_id"])
            destination = photo_dir / ("task_" + safe_id(task_id) + ".tif")
            print(f"[{index}/{total}] Task {task_id} [{task.get('status') or 'status unknown'}]")
            ok, message = download_orthophoto(
                args.base_url.rstrip("/"), project_uuid, task_id, PHOTO_PATH,
                destination, token, timeout=max(args.timeout, 90),
            )
            print(f"    {'OK' if ok else 'FAILED'}: {message}")
            rows.append({
                "task_id": task_id,
                "status": task.get("status", ""),
                "selected": True,
                "download_ok": ok,
                "message": message,
                "file_path": str(destination) if ok else "",
            })
            write_task_report(rows, report_path)

        successful = [photo_dir / ("task_" + safe_id(row["task_id"]) + ".tif")
                      for row in rows if row["download_ok"]]
        print(f"\nDownload summary: {len(successful)}/{total} orthophotos available.")
        print(f"Task report: {report_path.resolve()}")

        if successful and not args.no_mosaic:
            mosaic_path = project_dir / "mosaic.tif"
            preview_path = project_dir / "preview.png"
            print("Building mosaic from all valid downloaded/cached completed-task orthophotos...")
            summary = build_mosaic(successful, mosaic_path)
            create_preview(mosaic_path, preview_path)
            print(f"Mosaic: {mosaic_path.resolve()}")
            print(f"Preview: {preview_path.resolve()}")
            print(f"Sources: {summary['source_count']} | Size: {summary['width']} x {summary['height']} | CRS: {summary['crs']}")

        return 0 if len(successful) == total else 1
    except (DroneTMError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
