from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_vbs_launcher_uses_full_windows_powershell_path():
    launcher = _read("launch_latest.vbs")
    assert r"\System32\WindowsPowerShell\v1.0\powershell.exe" in launcher
    assert "update_and_run.ps1" in launcher
    assert "WScript.Shell" in launcher


def test_updater_pins_commit_and_stages_before_activation():
    updater = _read("update_and_run.ps1")
    assert "/commits/main" in updater
    assert "/archive/$latestSha.zip" in updater
    assert "robocopy.exe" in updater
    assert "/MIR" in updater
    assert '$PreserveDirs = @("data", ".git"' in updater
    assert '$PreserveFiles = @(".env", ".env.local"' in updater
    assert "Invoke-DependencyInstall -StagePath $StageRoot" in updater
    assert "import numpy, rasterio, requests; import mosaic_core; import gui_app" in updater
    assert "[IO.File]::Replace" in updater
    assert "Restoring the previous install pointer atomically" in updater
    assert "Copy-Item -LiteralPath $backup -Destination $destination -Force" not in updater
    assert "No OpenAerialMap upload or publication is performed" in updater


def test_updater_has_ci_fault_injection_for_dependency_and_post_swap_failures():
    updater = _read("update_and_run.ps1")
    rollback_test = _read("tests/windows/test_updater_rollback.ps1")
    assert "$TestFailDependencyInstall" in updater
    assert "$TestFailAfterSwap" in updater
    assert "-TestFailDependencyInstall" in rollback_test
    assert "-TestFailAfterSwap" in rollback_test
    assert "did not restore the prior install pointer" in rollback_test
    assert "must-survive" in rollback_test


def test_cog_script_validates_candidates_before_replacing_outputs():
    script = _read("rebuild_cog.ps1")
    validate_at = script.index("Validating candidate COG")
    archive_at = script.index('move /y "%PROJECT_DIR%\\mosaic.tif" "%PROJECT_DIR%\\mosaic.backup-%STAMP%.tif"')
    assert validate_at < archive_at
    assert "gdalbuildvrt -overwrite -strict -resolution average" in script
    assert "gdal_translate -of COG -co COMPRESS=DEFLATE -co OVERVIEWS=AUTO" in script
    assert "validate_cloud_optimized_geotiff.py" in script
    assert "rio cogeo validate" in script
    assert "mosaic.backup-%STAMP%.tif" in script
    assert "mosaic.backup-%STAMP%.vrt" in script
    assert 'set "NEW_VRT=0"' in script
    assert 'set "NEW_TIF=0"' in script


def test_cog_workflow_has_no_oam_upload_endpoint():
    script = _read("rebuild_cog.ps1").lower()
    assert "/api/v1/s3/createmultipart" not in script
    assert "openaerialmap.org/api" not in script
    assert "does not upload to openaerialmap" in script.lower()
