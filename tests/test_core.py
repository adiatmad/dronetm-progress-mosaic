from pathlib import Path
import csv
import io

import pytest

import numpy as np
import rasterio
from rasterio.transform import from_origin

from mosaic_core import build_mosaic, build_url, create_preview, download_orthophoto, normalize_tasks, parse_project_slug, safe_id, write_task_report


def test_normalize_list_of_task_records():
    records = normalize_tasks({"results": [{"id": 12, "state": "IMAGE_PROCESSING_FINISHED"}, {"task_id": "13", "status": "PROCESSING"}]})
    assert records[0]["task_id"] == "12"
    assert records[0]["status"] == "IMAGE_PROCESSING_FINISHED"
    assert records[1]["task_id"] == "13"


def test_normalize_mapping_of_task_states():
    records = normalize_tasks({"101": "IMAGE_PROCESSING_FINISHED", "102": "PROCESSING"})
    assert [(r["task_id"], r["status"]) for r in records] == [("101", "IMAGE_PROCESSING_FINISHED"), ("102", "PROCESSING")]


def test_nested_task_id_and_status():
    records = normalize_tasks([{"task": {"id": 77}, "status": {"state": "DONE"}}])
    assert records[0]["task_id"] == "77"
    assert records[0]["status"] == "DONE"


def test_url_join():
    assert build_url("https://example.org/", "/tasks/states/{project_id}", project_id=123) == "https://example.org/tasks/states/123"


def test_safe_id():
    assert "/" not in safe_id("../../abc 12")
    assert safe_id("abc 12") == "abc_12"


def test_build_mosaic_and_preview(tmp_path: Path):
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"
    profile = {
        "driver": "GTiff", "height": 2, "width": 2, "count": 3,
        "dtype": "uint8", "crs": "EPSG:3857", "transform": from_origin(0, 2, 1, 1),
    }
    with rasterio.open(first, "w", **profile) as dst:
        dst.write(np.full((3, 2, 2), 40, dtype=np.uint8))
    profile["transform"] = from_origin(2, 2, 1, 1)
    with rasterio.open(second, "w", **profile) as dst:
        dst.write(np.full((3, 2, 2), 180, dtype=np.uint8))

    mosaic = tmp_path / "mosaic.tif"
    summary = build_mosaic([first, second], mosaic)
    assert summary["width"] == 4
    assert summary["height"] == 2
    assert summary["source_count"] == 2
    with rasterio.open(mosaic) as src:
        assert src.crs.to_string() == "EPSG:3857"
        assert src.read(1).shape == (2, 4)

    preview = create_preview(mosaic, tmp_path / "preview.png")
    assert preview.is_file()
    assert preview.stat().st_size > 0



def test_parse_project_slug_from_drone_tm_url():
    assert parse_project_slug("https://drone.hotosm.org/projects/duut-tasi-50m-metinaro") == "duut-tasi-50m-metinaro"


def test_parse_project_slug_rejects_api_or_unrelated_url():
    import pytest
    from mosaic_core import DroneTMError

    with pytest.raises(DroneTMError):
        parse_project_slug("https://example.org/projects/duut-tasi-50m-metinaro")



def test_resolve_project_uuid_uses_project_detail_endpoint(monkeypatch):
    from mosaic_core import resolve_project_uuid

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "a8c7c6f0-6a4b-4f39-9db6-8f74e76e8c55"}

    class FakeSession:
        def get(self, url, timeout):
            assert url == "https://api.drone.hotosm.org/projects/duut-tasi-50m-metinaro"
            assert timeout == 30
            return FakeResponse()

    monkeypatch.setattr("mosaic_core.make_session", lambda token="": FakeSession())
    assert resolve_project_uuid(
        "https://api.drone.hotosm.org",
        "duut-tasi-50m-metinaro",
        token="test-token",
        timeout=30,
    ) == "a8c7c6f0-6a4b-4f39-9db6-8f74e76e8c55"



def _tiny_geotiff_bytes():
    from rasterio.io import MemoryFile

    profile = {
        "driver": "GTiff", "height": 2, "width": 2, "count": 1,
        "dtype": "uint8", "crs": "EPSG:3857", "transform": from_origin(0, 2, 1, 1),
    }
    with MemoryFile() as memory:
        with memory.open(**profile) as dst:
            dst.write(np.full((1, 2, 2), 7, dtype=np.uint8))
        return memory.read()


def test_download_reuses_valid_cached_geotiff_without_network(tmp_path, monkeypatch):
    import mosaic_core

    cached = tmp_path / "task_cached.tif"
    cached.write_bytes(_tiny_geotiff_bytes())

    def unexpected_network(*args, **kwargs):
        raise AssertionError("Valid cached GeoTIFF should not trigger a network request")

    monkeypatch.setattr(mosaic_core, "make_session", unexpected_network)
    ok, message = download_orthophoto(
        "https://api.drone.hotosm.org", "project-id", "task-id",
        "/projects/odm/export/{project_id}/{task_id}/orthophoto/",
        cached, timeout=1,
    )
    assert ok is True
    assert message == "Reused cached GeoTIFF"


def test_previously_failed_download_can_succeed_on_next_run(tmp_path, monkeypatch):
    import requests
    import mosaic_core

    destination = tmp_path / "task_retry.tif"
    raster_bytes = _tiny_geotiff_bytes()

    class FailedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            response = requests.Response()
            response.status_code = 503
            raise requests.HTTPError("503 Service Unavailable", response=response)

    class SuccessfulResponse:
        headers = {"content-type": "image/tiff"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size):
            yield raster_bytes

    class FakeSession:
        def __init__(self, response):
            self.response = response

        def get(self, *args, **kwargs):
            return self.response

    monkeypatch.setattr(mosaic_core, "make_session", lambda token="": FakeSession(FailedResponse()))
    ok, message = download_orthophoto(
        "https://api.drone.hotosm.org", "project-id", "task-id",
        "/projects/odm/export/{project_id}/{task_id}/orthophoto/",
        destination, timeout=1, attempts=1,
    )
    assert ok is False
    assert not destination.exists()

    monkeypatch.setattr(mosaic_core, "make_session", lambda token="": FakeSession(SuccessfulResponse()))
    ok, message = download_orthophoto(
        "https://api.drone.hotosm.org", "project-id", "task-id",
        "/projects/odm/export/{project_id}/{task_id}/orthophoto/",
        destination, timeout=1, attempts=1,
    )
    assert ok is True
    assert message.startswith("Downloaded")
    assert destination.exists()
    assert mosaic_core.is_valid_raster(destination)


def test_task_report_includes_download_result(tmp_path):
    report = tmp_path / "task_report.csv"
    write_task_report([{
        "task_id": "task-1", "status": "IMAGE_PROCESSING_FINISHED",
        "selected": True, "result": "REUSED", "download_ok": True,
        "message": "Reused cached GeoTIFF", "file_path": "task-1.tif",
    }], report)

    with report.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["result"] == "REUSED"
    assert rows[0]["download_ok"] == "True"
