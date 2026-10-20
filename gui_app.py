from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
import webbrowser

from mosaic_core import (
    COMPLETED_DEFAULT, DroneTMError, build_mosaic, create_preview,
    download_orthophoto, fetch_tasks, is_valid_raster, parse_project_slug,
    resolve_project_uuid, safe_id, write_task_report,
)

DEFAULT_PROJECT_URL = "https://drone.hotosm.org/projects/duut-tasi-50m-metinaro"
DEFAULT_API_URL = "https://api.drone.hotosm.org"
TASKS_TEMPLATE = "/tasks/states/{project_id}"
PHOTO_TEMPLATE = "/projects/odm/export/{project_id}/{task_id}/orthophoto/"


class DesktopApp:
    """Native Tkinter front end; it does not start a local web server."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("DroneTM Progress Mosaic")
        root.geometry("1050x720")
        root.minsize(800, 560)
        self.events: queue.Queue = queue.Queue()
        self.busy = False
        self.records: list[dict] = []
        self.project_id = ""
        self.project_key = ""
        self.project_uuid = ""
        self.project_dir: Path | None = None
        self.photo_dir: Path | None = None

        settings = ttk.LabelFrame(root, text="DroneTM connection", padding=10)
        settings.pack(fill="x", padx=12, pady=(12, 6))
        self.project_var = tk.StringVar(value=DEFAULT_PROJECT_URL)
        self.api_var = tk.StringVar(value=DEFAULT_API_URL)
        self.token_var = tk.StringVar()
        self.timeout_var = tk.StringVar(value="90")
        self._field(settings, "Project page URL", self.project_var, 0, 0, 3)
        self._field(settings, "API base URL", self.api_var, 1, 0, 2)
        self._field(settings, "Bearer token (optional)", self.token_var, 0, 3, 2, show="*")
        self._field(settings, "Timeout (seconds)", self.timeout_var, 1, 3, 1)

        controls = ttk.Frame(root, padding=(12, 6))
        controls.pack(fill="x")
        self.load_button = ttk.Button(controls, text="Load tasks", command=self.load_tasks)
        self.load_button.pack(side="left", padx=(0, 6))
        self.download_button = ttk.Button(controls, text="Download selected", command=self.download_selected, state="disabled")
        self.download_button.pack(side="left", padx=6)
        self.mosaic_button = ttk.Button(controls, text="Build mosaic", command=self.build_local_mosaic)
        self.mosaic_button.pack(side="left", padx=6)
        self.folder_button = ttk.Button(controls, text="Open project folder", command=self.open_project_folder)
        self.folder_button.pack(side="left", padx=6)

        body = ttk.Panedwindow(root, orient="vertical")
        body.pack(fill="both", expand=True, padx=12, pady=6)
        task_frame = ttk.LabelFrame(body, text="Tasks (select one or more; completed tasks are selected by default)", padding=8)
        self.task_list = tk.Listbox(task_frame, selectmode=tk.EXTENDED, height=12, exportselection=False)
        scroll = ttk.Scrollbar(task_frame, orient="vertical", command=self.task_list.yview)
        self.task_list.configure(yscrollcommand=scroll.set)
        self.task_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        body.add(task_frame, weight=3)

        log_frame = ttk.LabelFrame(body, text="Activity log", padding=8)
        self.log = tk.Text(log_frame, height=9, wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        body.add(log_frame, weight=2)
        self.status_var = tk.StringVar(value="Ready. Local processing; no browser server is started.")
        ttk.Label(root, textvariable=self.status_var, anchor="w", padding=(12, 6)).pack(fill="x")
        self._log("Native GUI mode: no localhost browser tab is used.")
        self._log("Source orthophotos stay in data/project_<slug>/orthophotos. No automatic OAM upload.")

    def _field(self, parent, label, variable, row, column, span, show=None):
        ttk.Label(parent, text=label).grid(row=row * 2, column=column, columnspan=span, sticky="w", padx=4, pady=(2, 0))
        entry = ttk.Entry(parent, textvariable=variable, show=show or "")
        entry.grid(row=row * 2 + 1, column=column, columnspan=span, sticky="ew", padx=4, pady=(0, 4))
        for col in range(column, column + span):
            parent.columnconfigure(col, weight=1)

    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start_job(self, label: str, function) -> None:
        if self.busy:
            return
        self.busy = True
        self.status_var.set(label)
        for button in (self.load_button, self.download_button, self.mosaic_button):
            button.configure(state="disabled")
        def run():
            try:
                function()
                self.events.put(("done", label))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=run, daemon=True).start()
        self.root.after(100, self._poll_events)

    def _poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self._log(value)
                elif kind == "tasks":
                    self.records, self.project_id, self.project_key, self.project_uuid = value
                    self.project_dir = Path("data") / ("project_" + self.project_key)
                    self.photo_dir = self.project_dir / "orthophotos"
                    self.task_list.delete(0, "end")
                    for index, record in enumerate(self.records):
                        status = record.get("status") or "(status unknown)"
                        cached = self.photo_dir / ("task_" + safe_id(record["task_id"]) + ".tif")
                        suffix = " [cached]" if is_valid_raster(cached) else ""
                        self.task_list.insert("end", f"{record['task_id']} | {status}{suffix}")
                        if status.upper() in COMPLETED_DEFAULT or any(w in status.upper() for w in ("FINISH", "COMPLETE", "DONE")):
                            self.task_list.selection_set(index)
                    self.download_button.configure(state="normal")
                elif kind == "done":
                    self._log(value + " completed.")
                    self.status_var.set("Ready")
                    self.busy = False
                    self.load_button.configure(state="normal")
                    self.mosaic_button.configure(state="normal")
                    if self.records:
                        self.download_button.configure(state="normal")
                    return
                elif kind == "error":
                    self._log("ERROR: " + value)
                    self.status_var.set("Operation failed")
                    self.busy = False
                    self.load_button.configure(state="normal")
                    self.mosaic_button.configure(state="normal")
                    if self.records:
                        self.download_button.configure(state="normal")
                    messagebox.showerror("DroneTM Progress Mosaic", value)
                    return
        except queue.Empty:
            pass
        if self.busy:
            self.root.after(100, self._poll_events)

    def load_tasks(self) -> None:
        project_url = self.project_var.get().strip()
        base_url = self.api_var.get().strip().rstrip("/")
        token = self.token_var.get().strip()
        try:
            project_id = parse_project_slug(project_url)
            timeout = int(self.timeout_var.get())
            if timeout < 1:
                raise ValueError("Timeout must be a positive number.")
            if not base_url.startswith(("https://", "http://")):
                raise ValueError("API base URL must start with https:// or http://.")
        except Exception as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        def job():
            self.events.put(("log", "Resolving project and loading task states…"))
            project_uuid = resolve_project_uuid(base_url, project_id, token, timeout)
            records, _ = fetch_tasks(base_url, project_uuid, TASKS_TEMPLATE, token, timeout)
            project_key = safe_id(project_id)
            self.events.put(("tasks", (records, project_id, project_key, project_uuid)))
            self.events.put(("log", f"Loaded {len(records)} task records for {project_id}."))
        self._start_job("Loading tasks…", job)

    def download_selected(self) -> None:
        if not self.records or self.photo_dir is None:
            messagebox.showinfo("Load tasks first", "Load the project task list before downloading.")
            return
        indexes = list(self.task_list.curselection())
        if not indexes:
            messagebox.showinfo("Select tasks", "Select at least one task.")
            return
        selected = [self.records[i] for i in indexes]
        photo_dir = self.photo_dir
        report_path = (self.project_dir or Path("data")) / "task_report.csv"
        base_url, token = self.api_var.get().strip().rstrip("/"), self.token_var.get().strip()
        timeout = int(self.timeout_var.get())

        def job():
            rows = []
            for index, record in enumerate(selected, 1):
                task_id = record["task_id"]
                dest = photo_dir / ("task_" + safe_id(task_id) + ".tif")
                self.events.put(("log", f"Downloading/reusing task {task_id} ({index}/{len(selected)})…"))
                ok, message = download_orthophoto(base_url, self.project_uuid, task_id, PHOTO_TEMPLATE, dest, token, timeout=max(timeout, 90))
                rows.append({"task_id": task_id, "status": record.get("status", ""), "selected": True,
                             "result": "REUSED" if message.startswith("Reused") else "DOWNLOADED" if ok else "FAILED",
                             "download_ok": ok, "message": message, "file_path": str(dest) if ok else ""})
                self.events.put(("log", f"{task_id}: {message}"))
            write_task_report(rows, report_path)
            self.events.put(("log", f"Task report saved: {report_path.resolve()}"))
        self._start_job("Downloading orthophotos…", job)

    def build_local_mosaic(self) -> None:
        project_key = self.project_key or safe_id(parse_project_slug(self.project_var.get().strip()))
        project_dir = self.project_dir or Path("data") / ("project_" + project_key)
        photo_dir = project_dir / "orthophotos"
        if not photo_dir.is_dir():
            messagebox.showinfo("No local orthophotos", f"Orthophotos folder not found:\n{photo_dir}")
            return
        sources = sorted(photo_dir.glob("task_*.tif"))
        sources = [p for p in sources if is_valid_raster(p)]
        if not sources:
            messagebox.showinfo("No valid orthophotos", f"No valid task_*.tif files were found in:\n{photo_dir}")
            return
        output = project_dir / "mosaic.tif"
        preview = project_dir / "preview.png"
        report = project_dir / "task_report.csv"
        def job():
            self.events.put(("log", f"Building mosaic from {len(sources)} local GeoTIFF(s). Source files will not be modified."))
            summary = build_mosaic(sources, output)
            create_preview(output, preview)
            if self.records:
                rows = [{"task_id": r["task_id"], "status": r.get("status", ""),
                         "selected": any(p.stem == "task_" + safe_id(r["task_id"]) for p in sources),
                         "result": "REUSED" if any(p.stem == "task_" + safe_id(r["task_id"]) for p in sources) else "NOT_CACHED",
                         "download_ok": any(p.stem == "task_" + safe_id(r["task_id"]) for p in sources),
                         "message": "Valid cached GeoTIFF" if any(p.stem == "task_" + safe_id(r["task_id"]) for p in sources) else "Not included",
                         "file_path": str(photo_dir / ("task_" + safe_id(r["task_id"]) + ".tif"))}
                        for r in self.records]
                write_task_report(rows, report)
            self.events.put(("log", f"Mosaic saved: {output.resolve()}"))
            self.events.put(("log", f"Preview saved: {preview.resolve()}"))
            self.events.put(("log", f"Dimensions: {summary['width']:,} × {summary['height']:,}; bands: {summary['bands']}; CRS: {summary['crs']}"))
            self.events.put(("log", "For a validated COG, run rebuild_cog.bat separately from OSGeo4W/GDAL."))
        self._start_job("Building mosaic…", job)

    def open_project_folder(self) -> None:
        folder = self.project_dir or Path("data") / ("project_" + safe_id(parse_project_slug(self.project_var.get().strip())))
        folder.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(str(folder))  # Windows native folder opener


def main() -> None:
    root = tk.Tk()
    DesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
