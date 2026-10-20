from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_vbs_launcher_uses_full_windows_powershell_path():
    launcher = _read("launch_latest.vbs")
    assert r"\System32\WindowsPowerShell\v1.0\powershell.exe" in launcher
    assert "update_and_run.ps1" in launcher
    assert "WScript.Shell" in launcher


def test_updater_pins_commit_and_preserves_user_data():
    updater = _read("update_and_run.ps1")
    assert "/commits/main" in updater
    assert "/zipball/$latestSha" in updater
    for protected in ('"data"', '".venv"', '".git"', '".streamlit"', '".env"'):
        assert protected in updater
    assert "Rolling back application files" in updater


def test_cog_script_validates_candidate_before_replacing_outputs():
    script = _read("rebuild_cog.ps1")
    validate_at = script.index("gdal driver cog validate")
    replace_at = script.index("Candidate validated. Replacing final outputs")
    assert validate_at < replace_at
    assert "gdalbuildvrt -overwrite -strict -resolution average" in script
    assert "gdal_translate -of COG" in script
    assert "BIGTIFF=YES" in script
    assert "60 GiB" in script
    assert 'set "NEW_VRT=0"' in script
    assert 'set "NEW_TIF=0"' in script
    assert "mosaic.backup-%STAMP%.tif" in script
    assert "mosaic.backup-%STAMP%.vrt" in script


def test_cog_workflow_has_no_oam_upload_endpoint():
    script = _read("rebuild_cog.ps1").lower()
    assert "/api/v1/s3/createmultipart" not in script
    assert "openaerialmap.org/api" not in script
    assert "does not upload to openaerialmap" in script
