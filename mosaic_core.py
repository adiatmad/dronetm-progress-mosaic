from __future__ import annotations
import os, re, time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, unquote
import numpy as np
import rasterio
import requests
from PIL import Image
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT

COMPLETED_DEFAULT = {"IMAGE_PROCESSING_FINISHED", "COMPLETED", "COMPLETE", "FINISHED"}

class DroneTMError(RuntimeError):
    pass

def safe_id(value: Any) -> str:
    result = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip()).strip("._-")
    if not result:
        raise ValueError("Project/task ID must contain letters or numbers.")
    return result[:120]

def build_url(base_url: str, template: str, **values: Any) -> str:
    try:
        path = template.format(**{k: str(v) for k, v in values.items()})
    except KeyError as exc:
        raise DroneTMError(f"Unknown URL placeholder: {exc}") from exc
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def parse_project_slug(project_url: str) -> str:
    """Extract a DroneTM project slug from a project page URL."""
    parsed = urlparse(project_url.strip())
    if parsed.scheme != "https" or parsed.netloc.lower() != "drone.hotosm.org":
        raise DroneTMError("Enter a DroneTM project URL like https://drone.hotosm.org/projects/project-slug.")
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "projects" or not parts[1]:
        raise DroneTMError("Project URL must use the /projects/<project-slug> format.")
    return parts[1]


def resolve_project_uuid(base_url: str, project_slug: str, token: str = "", timeout: int = 90) -> str:
    """Resolve a public project slug to the UUID required by orthophoto exports."""
    url = build_url(base_url, "/projects/{project_id}", project_id=project_slug)
    try:
        response = make_session(token).get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "unknown"
        hint = " Check that the token can access this project." if code in (401, 403) else " Check the project link and DroneTM base URL." if code == 404 else ""
        raise DroneTMError(f"Could not resolve project link (HTTP {code}).{hint}") from exc
    except ValueError as exc:
        raise DroneTMError("DroneTM project detail did not return valid JSON. Check that the base URL points to the API server, not the web frontend.") from exc
    except requests.RequestException as exc:
        raise DroneTMError(f"Could not reach DroneTM API to resolve the project link: {exc}") from exc

    if not isinstance(payload, dict):
        raise DroneTMError("DroneTM project detail returned an unexpected response.")
    identifier = payload.get("id") or payload.get("project_id")
    if not identifier:
        raise DroneTMError("DroneTM project detail did not contain a project UUID.")
    return str(identifier)


def make_session(token: str = "") -> requests.Session:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    session = requests.Session()
    retry = Retry(total=4, connect=4, read=4, backoff_factor=1,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset({"GET"}), respect_retry_after_header=True)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = "dronetm-progress-mosaic/0.1"
    if token.strip():
        session.headers["Authorization"] = "Bearer " + token.strip()
    return session

def _pick(obj: dict, keys: tuple[str, ...]):
    return next((obj[k] for k in keys if k in obj and obj[k] is not None), None)

def normalize_tasks(payload: Any) -> list[dict[str, Any]]:
    candidate = payload
    if isinstance(candidate, dict):
        for key in ("tasks", "results", "data", "items", "states"):
            if key in candidate:
                candidate = candidate[key]
                break
    if isinstance(candidate, list):
        iterable = candidate
    elif isinstance(candidate, dict):
        iterable = []
        for key, value in candidate.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("task_id", key)
            else:
                row = {"task_id": key, "status": value}
            iterable.append(row)
    else:
        raise DroneTMError("Expected a list or JSON object of task states.")
    records, seen = [], set()
    for item in iterable:
        if isinstance(item, (str, int)):
            task_id, status, raw = str(item), "", {"task_id": item}
        elif isinstance(item, dict):
            value = _pick(item, ("task_id", "taskId", "id", "task"))
            if isinstance(value, dict):
                value = _pick(value, ("id", "task_id"))
            if value is None:
                continue
            state = _pick(item, ("state", "status", "task_state", "task_status", "taskStatus", "processing_state", "processing_status"))
            if isinstance(state, dict):
                state = _pick(state, ("state", "status", "name"))
            task_id, status, raw = str(value), str(state or "").strip(), item
        else:
            continue
        if task_id not in seen:
            records.append({"task_id": task_id, "status": status, "raw": raw})
            seen.add(task_id)
    if not records:
        raise DroneTMError("No task IDs recognized. Check the task-state response schema.")
    return records

def fetch_tasks(base_url: str, project_id: str, path_template: str, token: str = "", timeout: int = 90):
    url = build_url(base_url, path_template, project_id=safe_id(project_id))
    try:
        response = make_session(token).get(url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "unknown"
        hint = " Check authentication." if code in (401, 403) else " Check the base URL and route." if code == 404 else ""
        raise DroneTMError(f"DroneTM returned HTTP {code}.{hint}") from exc
    except requests.RequestException as exc:
        raise DroneTMError(f"Could not reach DroneTM: {exc}") from exc
    except ValueError as exc:
        raise DroneTMError("Task endpoint did not return valid JSON.") from exc
    return normalize_tasks(payload), payload

def is_valid_raster(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 16:
            return False
        with rasterio.open(path) as src:
            return src.width > 0 and src.height > 0 and src.count > 0 and src.crs is not None
    except Exception:
        return False

def download_orthophoto(base_url: str, project_id: str, task_id: str, path_template: str,
                        destination: Path, token: str = "", timeout: int = 180, attempts: int = 3):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if is_valid_raster(destination):
        return True, "Reused cached GeoTIFF"
    destination.unlink(missing_ok=True)
    url = build_url(base_url, path_template, project_id=safe_id(project_id), task_id=safe_id(task_id))
    session = make_session(token)
    temporary = destination.with_suffix(destination.suffix + ".part")
    error = "Download failed"
    for attempt in range(1, attempts + 1):
        try:
            with session.get(url, stream=True, timeout=timeout) as response:
                response.raise_for_status()
                if "application/json" in response.headers.get("content-type", "").lower():
                    raise DroneTMError("The endpoint returned JSON instead of a GeoTIFF. The orthophoto may not be ready.")
                with temporary.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            output.write(chunk)
            if not is_valid_raster(temporary):
                raise DroneTMError("Response is not a readable georeferenced raster; it may be an error page or unavailable orthophoto.")
            os.replace(temporary, destination)
            return True, f"Downloaded ({destination.stat().st_size / 1048576:.1f} MiB)"
        except (requests.RequestException, OSError, DroneTMError) as exc:
            error = str(exc)
            temporary.unlink(missing_ok=True)
            if attempt < attempts:
                time.sleep(attempt)
    return False, error

def build_mosaic(source_paths: list[Path], output_path: Path) -> dict[str, Any]:
    paths = [Path(p) for p in source_paths if is_valid_raster(Path(p))]
    if not paths:
        raise DroneTMError("No valid GeoTIFFs available. Download at least one orthophoto.")
    datasets, virtuals = [], []
    try:
        datasets = [rasterio.open(path) for path in paths]
        target_crs = datasets[0].crs
        by_name = {}
        for ds in datasets:
            if ds.crs != target_crs:
                vrt = WarpedVRT(ds, crs=target_crs, resampling=Resampling.bilinear)
                virtuals.append(vrt)
                by_name[ds.name] = vrt
        sources = [by_name.get(ds.name, ds) for ds in datasets]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_name(output_path.stem + ".part.tif")
        # Write in bounded chunks instead of allocating the full mosaic in RAM.
        merge(
            sources,
            method="first",
            dst_path=temporary,
            mem_limit=256,
            dst_kwds={"compress": "deflate", "BIGTIFF": "IF_SAFER"},
        )
        os.replace(temporary, output_path)
        with rasterio.open(output_path) as result:
            return {"path": str(output_path), "width": result.width, "height": result.height,
                    "bands": result.count, "crs": str(result.crs), "bounds": tuple(result.bounds),
                    "size_bytes": output_path.stat().st_size, "source_count": len(paths)}
    except Exception as exc:
        if isinstance(exc, DroneTMError):
            raise
        raise DroneTMError(f"Could not build mosaic: {exc}") from exc
    finally:
        for vrt in virtuals:
            vrt.close()
        for ds in datasets:
            ds.close()

def create_preview(mosaic_path: Path, preview_path: Path, max_dimension: int = 1400) -> Path:
    with rasterio.open(mosaic_path) as src:
        scale = min(1.0, max_dimension / max(src.width, src.height))
        width, height = max(1, int(src.width * scale)), max(1, int(src.height * scale))
        data = src.read(out_shape=(src.count, height, width), resampling=Resampling.average, masked=True)
        channels = []
        for index in range(min(3, data.shape[0])):
            band = np.asarray(data[index].astype(np.float32).filled(np.nan), dtype=np.float32)
            valid = np.isfinite(band)
            if not valid.any():
                channels.append(np.zeros(band.shape, dtype=np.uint8))
                continue
            low, high = np.nanpercentile(band[valid], [2, 98])
            if high <= low:
                high = low + 1
            scaled = np.clip((band - low) / (high - low), 0, 1)
            scaled[~valid] = 0
            channels.append((scaled * 255).astype(np.uint8))
        if len(channels) == 1:
            rgb = np.repeat(channels[0][..., None], 3, axis=2)
        elif len(channels) == 2:
            rgb = np.stack((channels[0], channels[1], channels[1]), axis=2)
        else:
            rgb = np.stack(channels, axis=2)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, mode="RGB").save(preview_path, format="PNG", optimize=True)
    return preview_path

def write_task_report(rows: list[dict[str, Any]], path: Path) -> Path:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["task_id", "status", "selected", "download_ok", "message", "file_path"]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path
