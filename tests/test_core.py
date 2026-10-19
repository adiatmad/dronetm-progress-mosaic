from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from mosaic_core import build_mosaic, build_url, create_preview, normalize_tasks, parse_project_slug, safe_id


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
    assert build_url("https://example.org/", "/api/tasks/states/{project_id}", project_id=123) == "https://example.org/api/tasks/states/123"


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
