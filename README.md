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

1. Install **Python 3.11 or 3.12 (64-bit)** from [python.org](https://www.python.org/downloads/windows/). During setup, enable **Add Python to PATH**.
2. Download this repository: click **Code → Download ZIP**, then extract it.
3. Double-click `run_windows.bat`. The first run creates a virtual environment and installs dependencies.
4. The app opens in your browser. If it does not, open the URL printed in the terminal (usually `http://localhost:8501`).
5. Enter your DroneTM API base URL and project ID. Use the base URL for your own DroneTM deployment, not the API path itself.
6. Click **Load tasks**, review the task list and statuses, then click **Download selected orthophotos**.
7. Click **Build mosaic**. Download the GeoTIFF, preview PNG, and task report from the app.

You can also start it manually:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

## API settings

Defaults are based on the currently documented DroneTM-style routes, but deployments can differ. Check the API docs for your instance if requests return 404 or 401.

- Task-state path template: `/api/tasks/states/{project_id}`
- Per-task orthophoto path template: `/api/projects/odm/export/{project_id}/{task_id}/orthophoto/`

The app lets you change both templates. The base URL should look like `https://your-drone-tm.example.org`, without the route suffix. A bearer token is optional and is only sent to the server you configure. Do not paste credentials into public issues or screenshots.

The task parser accepts common list/dictionary response shapes. If your deployment returns an unusual schema, download the API response from your browser/API docs and open an issue with a **redacted** sample (remove tokens, private URLs, and personal data).

## Local files and reruns

Files are saved under `data/project_<PROJECT_ID>/`:

- `orthophotos/`: validated per-task GeoTIFFs
- `mosaic.tif`: generated mosaic
- `preview.png`: quicklook image
- `task_report.csv`: status, download outcome, and file path for each task

Re-running the download step reuses valid cached files. Delete that project's folder only if you intentionally want to clear its local cache and generated outputs. Large orthophotos can require substantial free disk space and memory; build the mosaic after enough source files have downloaded.

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

MIT. See [LICENSE](LICENSE).
