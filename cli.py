from __future__ import annotations

import argparse
import getpass
import os
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


def project_paths(root: Path, project_slug: str) -> tuple[Path, Path, Path]:
    project_dir = Path(root) / "data" / ("project_" + safe_id(project_slug))
    return project_dir, project_dir / "orthophotos", project_dir / "task_report.csv"


def select_completed_tasks(records: list[dict], statuses: list[str] | None = None) -> list[dict]:
    allowed = {status.upper() for status in (statuses or list(COMPLETED_DEFAULT))}
    selected = [record for record in records if str(record.get("status", "")).upper() in allowed]
    if not selected:
        selected = [
            record for record in records
            if any(word in str(record.get("status", "")).upper() for word in ("FINISH", "COMPLETE", "DONE"))
        ]
    return selected


def get_token() -> str:
    token = os.environ.get("DRONETM_TOKEN", "").strip()
    if token or not sys.stdin.isatty():
        return token
    return getpass.getpass("DroneTM bearer token (press Enter to skip): ").strip()


def download_tasks(args: argparse.Namespace, root: Path) -> int:
    slug = parse_project_slug(args.project_url)
    project_dir, photo_dir, report_path = project_paths(root, slug)
    token = get_token()
    project_uuid = resolve_project_uuid(args.base_url, slug, token, args.timeout)
    records, _payload = fetch_tasks(args.base_url, project_uuid, TASKS_PATH, token, args.timeout)
    selected = select_completed_tasks(records, args.status)
    if not selected:
        print("No tasks matched the requested completed statuses. No imagery was changed.")
        return 2

    photo_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    print(f"Project: {slug}")
    print(f"Selected {len(selected)} task(s); valid cached orthophotos will be reused.")
    for index, record in enumerate(selected, 1):
        task_id = str(record["task_id"])
        destination = photo_dir / ("task_" + safe_id(task_id) + ".tif")
        ok, message = download_orthophoto(
            args.base_url, project_uuid, task_id, PHOTO_PATH, destination,
            token=token, timeout=max(args.timeout, 90),
        )
        print(f"[{index}/{len(selected)}] {task_id}: {'OK' if ok else 'FAILED'} — {message}")
        rows.append({
            "task_id": task_id,
            "status": record.get("status", ""),
            "selected": True,
            "result": "REUSED" if ok and message.startswith("Reused") else "DOWNLOADED" if ok else "FAILED",
            "download_ok": ok,
            "message": message,
            "file_path": str(destination) if ok else "",
        })
    write_task_report(rows, project_dir / "task_report.csv")
    failures = sum(not row["download_ok"] for row in rows)
    print(f"Report: {project_dir / 'task_report.csv'}")
    print(f"Completed with {failures} failed task(s). No OAM upload was attempted.")
    return 1 if failures else 0


def show_status(args: argparse.Namespace, root: Path) -> int:
    slug = parse_project_slug(args.project_url)
    project_dir, photo_dir, report_path = project_paths(root, slug)
    files = sorted(photo_dir.glob("task_*.tif")) if photo_dir.is_dir() else []
    valid = [path for path in files if is_valid_raster(path)]
    print(f"Project folder: {project_dir}")
    print(f"Orthophoto files: {len(files)} total; {len(valid)} valid GeoTIFF(s)")
    if report_path.exists():
        print(f"Latest task report: {report_path}")
    mosaic = project_dir / "mosaic.tif"
    cog = project_dir / "mosaic.tif"
    if mosaic.exists():
        print(f"Mosaic output exists: {mosaic} ({mosaic.stat().st_size / (1024**3):.2f} GiB)")
    if cog.exists():
        print("For the validated GDAL Cloud Optimized GeoTIFF workflow, run rebuild_cog.bat separately.")
    print("Local-only mode: this command does not upload to OpenAerialMap.")
    return 0


def build_local_mosaic(args: argparse.Namespace, root: Path) -> int:
    slug = parse_project_slug(args.project_url)
    project_dir, photo_dir, report_path = project_paths(root, slug)
    sources = sorted(path for path in photo_dir.glob("task_*.tif") if is_valid_raster(path)) if photo_dir.is_dir() else []
    if not sources:
        print(f"No valid task_*.tif inputs found in {photo_dir}. Nothing was changed.", file=sys.stderr)
        return 2
    # Keep this output separate from mosaic.tif, which is the validated OSGeo4W COG target.
    output = project_dir / "mosaic-cli.tif"
    preview = project_dir / "preview-cli.png"
    print(f"Building rasterio mosaic from {len(sources)} valid source file(s).")
    summary = build_mosaic(sources, output)
    create_preview(output, preview)
    write_task_report([
        {"task_id": path.stem.removeprefix("task_"), "status": "", "selected": True,
         "result": "REUSED", "download_ok": True, "message": "Valid cached GeoTIFF",
         "file_path": str(path)}
        for path in sources
    ], report_path)
    print(f"Rasterio mosaic: {output}")
    print(f"Preview: {preview}")
    print(f"Size: {summary['width']:,} × {summary['height']:,} px; {summary['size_bytes'] / (1024**3):.2f} GiB")
    print("This output is not the OSGeo4W COG. Run rebuild_cog.bat for mosaic.vrt + validated mosaic.tif.")
    print("No source orthophotos were modified. No OAM upload was attempted.")
    return 0


def interactive(root: Path) -> int:
    parser = make_parser()
    while True:
        print("\nDroneTM Progress Mosaic — CLI (no browser/server)")
        print("1. Download completed-task orthophotos")
        print("2. Build a local rasterio mosaic (separate from the COG)")
        print("3. Show local cache status")
        print("4. Exit")
        choice = input("Choose 1–4: ").strip()
        if choice == "4":
            return 0
        if choice not in {"1", "2", "3"}:
            print("Choose 1, 2, 3, or 4.")
            continue
        args = parser.parse_args(["download" if choice == "1" else "mosaic" if choice == "2" else "status"])
        try:
            code = {"download": download_tasks, "mosaic": build_local_mosaic, "status": show_status}[args.command](args, root)
            if code:
                print(f"Operation finished with exit code {code}.")
        except (DroneTMError, OSError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
        input("Press Enter to return to the menu...")


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local DroneTM task/orthophoto workflow; no browser or localhost server.")
    subparsers = parser.add_subparsers(dest="command")
    for command in ("download", "mosaic", "status"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--project-url", default=DEFAULT_PROJECT_URL)
        sub.add_argument("--base-url", default=DEFAULT_BASE_URL)
        sub.add_argument("--timeout", type=int, default=90)
        sub.add_argument("--status", action="append", default=None,
                         help="Completed task status to include; repeat for multiple values.")
    return parser


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent
    parser = make_parser()
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list:
        if not sys.stdin.isatty():
            parser.print_help()
            return 2
        return interactive(root)
    args = parser.parse_args(args_list)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        handler = {"download": download_tasks, "mosaic": build_local_mosaic, "status": show_status}[args.command]
        return handler(args, root)
    except (DroneTMError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
