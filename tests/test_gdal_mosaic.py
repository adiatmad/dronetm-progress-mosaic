import json
from pathlib import Path
import subprocess

import pytest

import gdal_mosaic
from gdal_mosaic import GDALProcessingError, build_gdal_mosaic


def _info(path: Path, *, crs="EPSG:32748", layout="COG"):
    info = {
        "size": [4, 2],
        "coordinateSystem": {"wkt": crs},
        "bands": [{"band": 1}, {"band": 2}, {"band": 3}],
        "driverShortName": "GTiff",
        "cornerCoordinates": {"upperLeft": [0, 2], "lowerRight": [4, 0]},
    }
    if path.suffix.lower() == ".tif":
        info["metadata"] = {"IMAGE_STRUCTURE": {"LAYOUT": layout}}
    return info


def _mock_gdal(monkeypatch, *, layout="COG", crs_by_name=None):
    crs_by_name = crs_by_name or {}

    def require(command):
        return command

    def read(path):
        crs = crs_by_name.get(Path(path).name, "EPSG:32748")
        return _info(Path(path), crs=crs, layout=layout)

    def run(args, capture_output=True):
        command = args[0]
        if command == "gdalbuildvrt":
            Path(args[-1]).write_text("<VRTDataset/>", encoding="utf-8")
        elif command == "gdal_translate":
            Path(args[-1]).write_bytes(b"mock-cog")
        elif command == "gdalwarp":
            Path(args[-1]).write_text("<VRTDataset/>", encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(gdal_mosaic, "require_gdal_command", require)
    monkeypatch.setattr(gdal_mosaic, "_validated_info", read)
    monkeypatch.setattr(gdal_mosaic, "run_gdal", run)


def test_builds_vrt_cog_and_readiness_reports(tmp_path, monkeypatch):
    _mock_gdal(monkeypatch)
    source = tmp_path / "task 1.tif"
    source.write_bytes(b"source")
    vrt = tmp_path / "mosaic.vrt"
    cog = tmp_path / "mosaic.tif"
    report = tmp_path / "oam_preparation" / "readiness_report.json"
    gdalinfo_report = tmp_path / "oam_preparation" / "gdalinfo.json"

    result = build_gdal_mosaic([source], vrt, cog, report, gdalinfo_report)

    assert vrt.is_file()
    assert cog.read_bytes() == b"mock-cog"
    assert json.loads(report.read_text(encoding="utf-8"))["upload_performed"] is False
    assert json.loads(gdalinfo_report.read_text(encoding="utf-8"))["size"] == [4, 2]
    assert result["cog_layout"] == "COG"
    assert result["source_count"] == 1


def test_rejects_mixed_crs_without_guessing_target(tmp_path, monkeypatch):
    _mock_gdal(monkeypatch, crs_by_name={"second.tif": "EPSG:4326"})
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"
    first.write_bytes(b"source")
    second.write_bytes(b"source")

    with pytest.raises(GDALProcessingError, match="different CRSs"):
        build_gdal_mosaic(
            [first, second],
            tmp_path / "mosaic.vrt",
            tmp_path / "mosaic.tif",
            tmp_path / "report.json",
            tmp_path / "gdalinfo.json",
        )


def test_failed_cog_validation_preserves_existing_outputs(tmp_path, monkeypatch):
    _mock_gdal(monkeypatch, layout="IFD")
    source = tmp_path / "task.tif"
    source.write_bytes(b"source")
    vrt = tmp_path / "mosaic.vrt"
    cog = tmp_path / "mosaic.tif"
    vrt.write_text("old-vrt", encoding="utf-8")
    cog.write_bytes(b"old-cog")

    with pytest.raises(GDALProcessingError, match="LAYOUT=COG"):
        build_gdal_mosaic(
            [source],
            vrt,
            cog,
            tmp_path / "report.json",
            tmp_path / "gdalinfo.json",
        )

    assert vrt.read_text(encoding="utf-8") == "old-vrt"
    assert cog.read_bytes() == b"old-cog"
