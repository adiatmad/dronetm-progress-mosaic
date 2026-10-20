import json
from pathlib import Path

import pytest

from osgeo4w_mosaic import DroneTMError, crs_key, gdal_info, target_srs


def test_target_srs_prefers_authority_code():
    info = {"coordinateSystem": {"id": {"authority": "EPSG", "code": 32748}, "wkt": "example"}}
    assert target_srs(info) == "EPSG:32748"


def test_target_srs_uses_wkt_when_authority_missing():
    info = {"coordinateSystem": {"wkt": "LOCAL_CS[\"test\"]"}}
    assert target_srs(info) == 'LOCAL_CS["test"]'


def test_target_srs_rejects_missing_crs():
    with pytest.raises(DroneTMError, match="Cannot determine target CRS"):
        target_srs({"coordinateSystem": {}})


def test_gdal_info_parses_valid_json(monkeypatch, tmp_path):
    import osgeo4w_mosaic

    raster = tmp_path / "input.tif"
    raster.touch()
    expected = {
        "size": [10, 20],
        "bands": [{"type": "Byte"}],
        "coordinateSystem": {"wkt": "EPSG WKT"},
    }

    class Result:
        stdout = json.dumps(expected)

    monkeypatch.setattr(osgeo4w_mosaic, "run_checked", lambda command: Result())
    assert gdal_info(raster) == expected


def test_gdal_info_rejects_missing_crs(monkeypatch, tmp_path):
    import osgeo4w_mosaic

    raster = tmp_path / "input.tif"
    raster.touch()

    class Result:
        stdout = json.dumps({"size": [10, 20], "bands": [{"type": "Byte"}], "coordinateSystem": {}})

    monkeypatch.setattr(osgeo4w_mosaic, "run_checked", lambda command: Result())
    with pytest.raises(DroneTMError, match="missing size, bands, or CRS"):
        gdal_info(raster)
