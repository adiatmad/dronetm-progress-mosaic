import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_gui_is_python_syntax_valid_and_does_not_import_streamlit():
    source = (ROOT / "gui_app.py").read_text(encoding="utf-8")
    ast.parse(source)
    assert "import streamlit" not in source
    assert "tkinter" in source
    assert "Thread(" in source or "threading.Thread(" in source


def test_native_updater_launches_gui_not_localhost_streamlit():
    source = (ROOT / "update_and_run.ps1").read_text(encoding="utf-8")
    assert '"gui_app.py"' in source
    assert "streamlit run" not in source.lower()
    assert '"gui_app.py"' in source[source.index("$Required"):source.index("$PreserveDirs")]


def test_streamlit_fallback_does_not_load_whole_mosaic_for_download():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert 'open(mosaic_path, "rb")' not in source
    assert 'data=handle' not in source
    assert "Open project output folder" in source


def test_cog_rebuild_stays_separate_and_has_no_oam_upload():
    source = (ROOT / "rebuild_cog.ps1").read_text(encoding="utf-8")
    assert "gdalbuildvrt" in source
    assert "gdal_translate" in source
    assert "gdal driver cog validate" in source
    assert "does not upload to OpenAerialMap" in source
