# DroneTM Progress Mosaic

A local-first tool for turning completed DroneTM task orthophotos into a project-wide progress mosaic. It is designed for Windows users and keeps imagery on your computer unless you explicitly upload or share it.

## What it does

- Connects to a DroneTM API endpoint you configure.
- Finds task records and lets you select which states count as completed.
- Downloads task orthophotos with retries and resumable local caching.
- Validates downloaded rasters before keeping them.
- Merges compatible GeoTIFFs into a georeferenced mosaic, handling different source CRSs by warping to a common CRS.
- Shows a preview and exports a CSV task/download report.
- Keeps the download cache so a rerun does not need to download files that are already valid.

## Quick start (Windows)

### Single-file desktop build (experimental)

The `Windows desktop executable` GitHub Actions workflow builds `DroneTM-Progress-Mosaic.exe` on a Windows runner. To request a build, open **Actions → Windows desktop executable → Run workflow** in GitHub. Download the `DroneTM-Progress-Mosaic-Windows-x64` artifact from that run. A `v*` tag also attaches the executable to a GitHub Release.

This packaging path remains **experimental until a Windows build completes and the executable is smoke-tested**. The workflow runs unit tests, verifies bundled dependency imports, and checks that the executable entry point targets the native Tkinter GUI rather than a localhost browser server. CI does not interact with the GUI or prove it can connect to your DroneTM account or download a real orthophoto. The first real-project run remains an acceptance check.

### Source-run fallback

1. Install **Python 3.11 or 3.12 (64-bit)** from [python.org](https://www.python.org/downloads/windows/). During setup, enable **Add Python to PATH**.
2. Download this repository: click **Code → Download ZIP**, then extract it.
3. Double-click `run_windows.bat`. The first run creates a virtual environment and installs dependencies.
4. The legacy Streamlit interface opens in your browser. For the recommended native GUI, double-click `launch_latest.vbs` instead; it updates the source safely and launches `gui_app.py` without localhost.
5. Paste the DroneTM project page link (for example, `https://drone.hotosm.org/projects/duut-tasi-50m-metinaro`). Paste a DroneTM bearer token if your deployment requires one. The app resolves the public project slug to the internal UUID needed by the orthophoto export API. Keep the default API base URL (`https://api.drone.hotosm.org`); the project page itself is hosted on `drone.hotosm.org`.
6. Click **Load tasks**, review the task list and statuses, then click **Download selected orthophotos**.
7. Click **Build mosaic**. Download the GeoTIFF, preview PNG, and task report from the app.

You can also start it manually:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

## One-click local workflows (Windows)

After extracting the repository into your local project folder, you can use these two separate launchers:

- **`launch_latest.vbs`** — double-click to check GitHub's latest `main` commit, update the application files when the commit changes, install/update dependencies only when required, then start the local Streamlit app. It uses the full Windows PowerShell path, so PowerShell does not need to be on PATH.
- **`rebuild_cog.bat`** — double-click to rebuild `mosaic.vrt` and a physical `mosaic.tif` Cloud Optimized GeoTIFF from existing local `task_*.tif` files. It uses the project's default `data/project_duut-tasi-50m-metinaro/orthophotos` folder; if that folder is missing, it asks you for the source folder.

### Updater safety

The updater resolves the current `main` commit through GitHub's commits API and downloads `zipball/<exact-40-character-SHA>`. It mirrors the archive into a **new staging directory** with `robocopy /MIR`, excluding `data/`, `.git/`, `.venv/`, `.streamlit/`, local configuration and raster outputs. It installs dependencies and runs an import smoke test in staging before creating a timestamped sibling release under `.installations/`. The active release is selected by an atomically replaced `.launcher-state.json` pointer; prior release folders are retained. A dependency failure leaves the old pointer untouched, while a post-switch failure atomically restores the old pointer rather than copying source files back over a live install. Local `data/`, source orthophotos and the root environment are not overwritten. The first launch needs internet access and supported 64-bit Python 3.11 or 3.12.

GitHub Actions includes a Windows fault-injection test that deliberately fails the staged dependency step and a second test that fails immediately after pointer activation. Both must prove that the prior release remains selected and the local data sentinel survives.

### COG rebuild behavior

The COG launcher:
1. Checks for local `task_*.tif` inputs and at least 60 GiB free on the output drive. This is a minimum safety gate, not a guarantee that every mosaic will fit.
2. Builds a timestamped temporary VRT with `gdalbuildvrt`, then a temporary COG using `gdal_translate -of COG -co COMPRESS=DEFLATE -co OVERVIEWS=AUTO`.
3. Validates the candidate using `validate_cloud_optimized_geotiff.py` when available, otherwise `rio cogeo validate`, with GDAL's COG validator as a final supported fallback.
4. Only after validation, archives existing `mosaic.vrt` and `mosaic.tif` and moves the candidates into place. If either replacement fails, it removes any new output and restores the archived outputs.
5. Writes a build log in the project output folder. No upload to OpenAerialMap is attempted.

The script does not download task imagery, alter source orthophotos, or upload to OpenAerialMap. The current overlap behavior is standard GDAL VRT source priority, **not alpha-aware blending**. Review the mosaic preview, coverage, gaps, and seams before publication. If you need alpha-aware blending, treat that as a separate implementation requiring a verified blending method and test imagery.

### Acceptance checks before relying on these launchers

- Run `python -m pytest -q` for the existing application tests and launcher-contract tests.
- On Windows, test the VBS updater once with internet access and a supported Python installation; verify that `data/` and `.venv/` remain in place.
- Test the COG launcher with a small disposable folder of test rasters before using the full project. Verify COG validation, output metadata, and backup/rollback behavior.
- Re-run each launcher to confirm the no-update path works. No OAM upload should occur.

## Native GUI and large-mosaic memory behavior\n\nThe recommended `launch_latest.vbs` path starts a Tkinter Windows desktop window directly. It does not create a localhost server or consume a browser tab. The existing Streamlit `app.py` remains available as a legacy fallback. Its mosaic output section now shows the local file path and opens the project folder instead of passing the full GeoTIFF into a download widget; this avoids the reported `MemoryError` caused by reading the entire large mosaic into application memory.\n\nFor a separate command-line-style COG rebuild, double-click `rebuild_cog.bat`. It runs the OSGeo4W/GDAL workflow on the existing local orthophotos.\n\n## API settings

Defaults are based on the currently documented DroneTM-style routes, but deployments can differ. Check the API docs for your instance if requests return 404 or 401.

- API base URL: `https://api.drone.hotosm.org` (the web app uses `https://drone.hotosm.org`).
- Task-state path template: `/tasks/states/{project_id}`
- Per-task orthophoto path template: `/projects/odm/export/{project_id}/{task_id}/orthophoto/`

The app lets you change both templates. The base URL must point to the API server, not the frontend; for HOT’s public instance use `https://api.drone.hotosm.org`, without the route suffix. A bearer token is sent only to the DroneTM host you configure. Project UUID resolution uses the project detail endpoint, which accepts the project slug on the current HOT DroneTM API. Do not paste credentials into public issues or screenshots.

The task parser accepts common list/dictionary response shapes. If your deployment returns an unusual schema, download the API response from your browser/API docs and open an issue with a **redacted** sample (remove tokens, private URLs, and personal data).

## Local files and reruns

Files are saved under `data/project_<PROJECT_ID>/`:

- `orthophotos/`: validated per-task GeoTIFFs
- `mosaic.tif`: generated mosaic
- `preview.png`: quicklook image
- `task_report.csv`: status, result (`DOWNLOADED`, `REUSED`, or `FAILED`), download outcome, and file path for each task

**Safe to rerun:** every run refreshes DroneTM's task list. A valid cached GeoTIFF is reused without a network download; failed or invalid files are retried on the next run, and newly processed tasks are picked up automatically. The report is a current-run snapshot, not a historical log. A failed download stays visible as `FAILED`; it is not permanently skipped or treated as a valid image. A retry can only succeed once DroneTM actually serves a valid orthophoto. Delete that project's folder only if you intentionally want to clear its local cache and generated outputs. Large orthophotos can require substantial free disk space and memory; build the mosaic after enough source files have downloaded.

## Limitations (important)

- A task marked complete may not have an orthophoto available yet. The app reports failures and continues with other tasks.
- The mosaic can be large. Ensure the output disk has enough free space.
- This tool **does not automatically publish to OpenAerialMap**. Publishing and replacing an existing OAM item need separate, verified handling to avoid duplicate or misleading datasets.
- API routes and authentication can vary by DroneTM deployment. Successful task discovery and at least one valid orthophoto download are the acceptance checks for your instance.

## Development and checks

```powershell
py -m pip install -r requirements-dev.txt
py -m pytest
```

## License

GNU General Public License v3.0 (GPL-3.0). See [LICENSE](LICENSE).
