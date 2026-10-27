from pathlib import Path

from cli import project_paths, select_completed_tasks


def test_project_paths_stay_inside_project_data_folder(tmp_path: Path):
    project_dir, photo_dir, report_path = project_paths(tmp_path, "sample-project")
    assert project_dir == tmp_path / "data" / "project_sample-project"
    assert photo_dir == project_dir / "orthophotos"
    assert report_path == project_dir / "task_report.csv"


def test_completed_task_selection_uses_default_states():
    records = [
        {"task_id": "1", "status": "IMAGE_PROCESSING_FINISHED"},
        {"task_id": "2", "status": "PROCESSING"},
        {"task_id": "3", "status": "COMPLETE"},
    ]
    assert [row["task_id"] for row in select_completed_tasks(records)] == ["1", "3"]


def test_completed_task_selection_accepts_explicit_states_case_insensitively():
    records = [
        {"task_id": "1", "status": "PROCESSING"},
        {"task_id": "2", "status": "READY_FOR_REVIEW"},
    ]
    assert [row["task_id"] for row in select_completed_tasks(records, ["ready_for_review"])] == ["2"]


def test_completed_task_selection_has_keyword_fallback():
    records = [{"task_id": "1", "status": "TASK_DONE"}, {"task_id": "2", "status": "PROCESSING"}]
    assert [row["task_id"] for row in select_completed_tasks(records, ["UNKNOWN"])] == ["1"]
