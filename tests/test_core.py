from mosaic_core import build_url, normalize_tasks, safe_id

def test_normalize_list_of_task_records():
    records = normalize_tasks({"results": [{"id": 12, "state": "IMAGE_PROCESSING_FINISHED"}, {"task_id": "13", "status": "PROCESSING"}]})
    assert records[0]["task_id"] == "12"
    assert records[0]["status"] == "IMAGE_PROCESSING_FINISHED"
    assert records[1]["task_id"] == "13"

def test_normalize_mapping_of_task_states():
    records = normalize_tasks({"101": "IMAGE_PROCESSING_FINISHED", "102": "PROCESSING"})
    assert [(r["task_id"], r["status"]) for r in records] == [("101", "IMAGE_PROCESSING_FINISHED"), ("102", "PROCESSING")]

def test_nested_task_id_and_status():
    records = normalize_tasks([{"task": {"id": 77}, "status": {"state": "DONE"}}])
    assert records[0]["task_id"] == "77"
    assert records[0]["status"] == "DONE"

def test_url_join():
    assert build_url("https://example.org/", "/api/tasks/states/{project_id}", project_id=123) == "https://example.org/api/tasks/states/123"

def test_safe_id():
    assert "/" not in safe_id("../../abc 12")
    assert safe_id("abc 12") == "abc_12"
