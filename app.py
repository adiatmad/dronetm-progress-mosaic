from __future__ import annotations
from pathlib import Path
import pandas as pd
import streamlit as st
import rasterio

from mosaic_core import COMPLETED_DEFAULT, DroneTMError, build_mosaic, create_preview, download_orthophoto, fetch_tasks, is_valid_raster, safe_id, write_task_report

st.set_page_config(page_title="DroneTM Progress Mosaic", page_icon="🗺️", layout="wide")
st.title("🗺️ DroneTM Progress Mosaic")
st.caption("Download completed-task orthophotos, build a georeferenced mosaic, and export a progress report — locally.")

with st.sidebar:
    st.header("DroneTM connection")
    base_url = st.text_input("DroneTM base URL", value="https://drone.hotosm.org").strip().rstrip("/")
    project_id = st.text_input("Project ID", placeholder="e.g. 123").strip()
    token = st.text_input("Bearer token (optional)", type="password", help="Only sent to the DroneTM host above.")
    timeout = st.number_input("Request timeout (seconds)", min_value=15, max_value=600, value=90, step=15)
    st.divider()
    st.subheader("API route templates")
    tasks_path = st.text_input("Task states path", value="/api/tasks/states/{project_id}")
    photo_path = st.text_input("Task orthophoto path", value="/api/projects/odm/export/{project_id}/{task_id}/orthophoto/")
    st.caption("If a route returns 404, check your DroneTM instance's API docs and edit the template.")

if not project_id:
    st.info("Enter a project ID in the sidebar to begin.")
    st.markdown("**Workflow**\n1. Load and review task states.\n2. Select completed tasks.\n3. Download imagery; valid cached files are reused.\n4. Build the mosaic and download the GeoTIFF and report.")
    st.stop()

try:
    project_key = safe_id(project_id)
except ValueError as exc:
    st.error(str(exc))
    st.stop()

project_dir = Path("data") / ("project_" + project_key)
photo_dir = project_dir / "orthophotos"
mosaic_path = project_dir / "mosaic.tif"
preview_path = project_dir / "preview.png"
report_path = project_dir / "task_report.csv"

if "task_records" not in st.session_state:
    st.session_state.task_records = []
if "task_project_key" not in st.session_state:
    st.session_state.task_project_key = None
if "mosaic_summary" not in st.session_state:
    st.session_state.mosaic_summary = {}

col_a, col_b = st.columns([1, 3])
with col_a:
    load_clicked = st.button("Load tasks", type="primary", use_container_width=True)
with col_b:
    st.caption("Local cache: " + str(project_dir))

if load_clicked:
    if not base_url.startswith(("https://", "http://")):
        st.error("Base URL must start with https:// or http://.")
    else:
        with st.spinner("Contacting DroneTM and reading task states…"):
            try:
                tasks, _payload = fetch_tasks(base_url, project_id, tasks_path, token)
                st.session_state.task_records = tasks
                st.session_state.task_project_key = project_key
                st.success("Loaded " + str(len(tasks)) + " task records.")
            except DroneTMError as exc:
                st.error(str(exc))

records = st.session_state.task_records if st.session_state.task_project_key == project_key else []
eligible = []
if records:
    states = sorted({r["status"] for r in records if r.get("status")})
    suggested = [s for s in states if s.upper() in COMPLETED_DEFAULT]
    if not suggested:
        suggested = [s for s in states if any(word in s.upper() for word in ("FINISH", "COMPLETE", "DONE"))]
    with st.expander("Review task selection", expanded=True):
        selected_states = st.multiselect("Statuses eligible for download", options=states, default=suggested)
        default_ids = [r["task_id"] for r in records if r.get("status") in selected_states]
        eligible = st.multiselect("Tasks to include", options=[r["task_id"] for r in records], default=default_ids)
    table = []
    for record in records:
        path = photo_dir / ("task_" + safe_id(record["task_id"]) + ".tif")
        table.append({"Task ID": record["task_id"], "Status": record.get("status") or "(not provided)",
                      "Selected": record["task_id"] in eligible, "Cached valid GeoTIFF": is_valid_raster(path)})
    st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)
    st.caption(str(len(eligible)) + " task(s) selected. Verify statuses before downloading.")

    if st.button("Download selected orthophotos", type="primary", disabled=not eligible):
        photo_dir.mkdir(parents=True, exist_ok=True)
        report_rows = []
        progress = st.progress(0)
        status_line = st.empty()
        selected_records = [r for r in records if r["task_id"] in eligible]
        for index, record in enumerate(selected_records):
            task_id = record["task_id"]
            destination = photo_dir / ("task_" + safe_id(task_id) + ".tif")
            status_line.write("Processing task " + task_id + " (" + str(index + 1) + "/" + str(len(eligible)) + ")…")
            ok, message = download_orthophoto(base_url, project_id, task_id, photo_path, destination,
                                               token, timeout=max(int(timeout), 90))
            report_rows.append({"task_id": task_id, "status": record.get("status", ""), "selected": True,
                                "download_ok": ok, "message": message, "file_path": str(destination) if ok else ""})
            progress.progress((index + 1) / len(selected_records))
        write_task_report(report_rows, report_path)
        count = sum(bool(row["download_ok"]) for row in report_rows)
        st.success("Finished: " + str(count) + "/" + str(len(report_rows)) + " selected orthophoto(s) are available.")
        failures = [r for r in report_rows if not r["download_ok"]]
        if failures:
            st.warning("Some orthophotos were unavailable or invalid. They are listed below; retry later if processing is still underway.")
            st.dataframe(pd.DataFrame(failures), use_container_width=True, hide_index=True)
        st.rerun()

st.divider()
st.subheader("Build the progress mosaic")
available = []
for record in records:
    path = photo_dir / ("task_" + safe_id(record["task_id"]) + ".tif")
    if is_valid_raster(path):
        available.append((record["task_id"], path, record.get("status", "")))

if available:
    st.write(str(len(available)) + " valid cached orthophoto(s) are available for this project.")
    cached_ids = [item[0] for item in available]
    mosaic_ids = st.multiselect("Source tasks for this mosaic", options=cached_ids, default=cached_ids)
    if st.button("Build mosaic", type="primary", disabled=not mosaic_ids):
        with st.spinner("Merging orthophotos. Large projects can take several minutes and need extra disk space."):
            try:
                summary = build_mosaic([p for task_id, p, _ in available if task_id in mosaic_ids], mosaic_path)
                create_preview(mosaic_path, preview_path)
                write_task_report([{"task_id": task_id, "status": status, "selected": task_id in mosaic_ids,
                                    "download_ok": True, "message": "Valid cached GeoTIFF", "file_path": str(path)}
                                   for task_id, path, status in available], report_path)
                st.session_state.mosaic_summary = summary
                st.success("Mosaic built successfully.")
            except DroneTMError as exc:
                st.error(str(exc))

if mosaic_path.exists() and is_valid_raster(mosaic_path):
    st.divider()
    st.subheader("Mosaic output")
    if preview_path.exists():
        st.image(str(preview_path), caption="Quicklook only — use the GeoTIFF for geospatial analysis.", use_container_width=True)
    with open(mosaic_path, "rb") as handle:
        st.download_button("Download mosaic GeoTIFF", data=handle.read(),
                           file_name="project_" + project_key + "_mosaic.tif", mime="image/tiff",
                           use_container_width=True)
    if preview_path.exists():
        st.download_button("Download preview PNG", data=preview_path.read_bytes(),
                           file_name="project_" + project_key + "_preview.png", mime="image/png")
    if report_path.exists():
        st.download_button("Download task report CSV", data=report_path.read_bytes(),
                           file_name="project_" + project_key + "_task_report.csv", mime="text/csv")
    try:
        with rasterio.open(mosaic_path) as src:
            a, b, c, d = st.columns(4)
            a.metric("Width", f"{src.width:,} px")
            b.metric("Height", f"{src.height:,} px")
            c.metric("Bands", src.count)
            d.metric("File size", f"{mosaic_path.stat().st_size / (1024 * 1024):.1f} MiB")
            st.caption("CRS: " + str(src.crs) + " · Sources used: " + str(st.session_state.mosaic_summary.get("source_count", "see build result")))
    except Exception as exc:
        st.error("Could not read mosaic metadata: " + str(exc))

with st.expander("Troubleshooting and privacy"):
    st.markdown("**401/403:** verify access requirements; this version supports an optional bearer token.\n\n"
                "**404:** confirm the base URL and route templates.\n\n"
                "**Completed task but download fails:** the orthophoto may not be ready or available. The app continues with other tasks.\n\n"
                "**Large mosaic:** check disk space and begin with fewer tasks if memory is limited.\n\n"
                "**Privacy:** imagery and reports stay in the local data folder. This version does not publish to OpenAerialMap.")
