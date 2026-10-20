from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    # PyInstaller extracts bundled Python sources into _MEIPASS. Add that path
    # so the same native GUI entry point works in source and packaged modes.
    bundle_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if str(bundle_dir) not in sys.path:
        sys.path.insert(0, str(bundle_dir))

    if "--self-test" in sys.argv:
        import numpy
        import pandas
        import rasterio
        import requests
        import gui_app
        import mosaic_core
        print(
            "Native GUI imports OK:",
            "rasterio", rasterio.__version__,
            "numpy", numpy.__version__,
            "pandas", pandas.__version__,
            "requests", requests.__version__,
            "GUI", gui_app.__file__,
            "core", mosaic_core.__file__,
        )
        return

    from gui_app import main as run_gui
    run_gui()


if __name__ == "__main__":
    main()
