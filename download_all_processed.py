from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from mosaic_core import (
    COMPLETED_DEFAULT,
    DroneTMError,
    download_orthophoto,
    fetch_tasks,
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
        description="Download orthophotos for all completed/processed DroneTM tasks."
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

    print(f"Found {len(tasks)} task records; downloading {len(completed)} completed/processed tasks.")
    report_rows = []
    succeeded = 0
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
        print(f"    {'OK' if ok else 'FAILED'}: {message}")
        succeeded += int(ok)
        report_rows.append({
            "task_id": task_id,
            "status": task.get("status", ""),
            "selected": True,
            "download_ok": ok,
            "message": message,
            "file_path": str(destination) if ok else "",
        })

    write_task_report(report_rows, report_path)
    print(f"\nFinished: {succeeded}/{len(completed)} orthophotos available.")
    print(f"Orthophotos: {photo_dir.resolve()}")
    print(f"Task report: {report_path.resolve()}")
    print("Existing valid GeoTIFFs are reused; failed tasks are listed in the CSV report.")
    return 0 if succeeded == len(completed) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DroneTMError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
