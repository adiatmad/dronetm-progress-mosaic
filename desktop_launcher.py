from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path


def main() -> None:
    # PyInstaller extracts bundled app files into _MEIPASS. Keep outputs in
    # the user's current working directory, not in the temporary extraction dir.
    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    app_path = bundle_dir / "app.py"
    if not app_path.is_file():
        raise SystemExit("Bundled app.py is missing. Please download a fresh build.")

    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    os.environ.setdefault("STREAMLIT_SERVER_HEADLESS", "true")
    os.environ.setdefault("STREAMLIT_SERVER_ADDRESS", "127.0.0.1")
    os.environ.setdefault("STREAMLIT_SERVER_PORT", "8501")
    os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")

    def open_browser() -> None:
        # Streamlit can take a few seconds to start on first launch.
        time.sleep(2.5)
        webbrowser.open("http://127.0.0.1:8501")

    threading.Thread(target=open_browser, daemon=True).start()

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit",
        "run",
        str(app_path),
        "--global.developmentMode=false",
        "--server.headless=true",
        "--server.address=127.0.0.1",
        "--server.port=8501",
        "--server.fileWatcherType=none",
        "--browser.gatherUsageStats=false",
    ]
    stcli.main()


if __name__ == "__main__":
    main()
