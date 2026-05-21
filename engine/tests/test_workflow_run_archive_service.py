from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agent33.workflows.events import WorkflowEvent, WorkflowEventType
from agent33.workflows.executor import StepResult, WorkflowResult, WorkflowStatus
from agent33.workflows.history import WorkflowExecutionRecord
from agent33.workflows.run_archive import WorkflowRunArchiveService

if TYPE_CHECKING:
    from pathlib import Path


def _sample_result(*, output_file: Path | None = None) -> WorkflowResult:
    outputs = {
        "summary": "done",
        "artifacts": [
            {
                "mime_type": "text/html",
                "data": "<div>ok</div>",
                "metadata": {"filename": "report.html", "label": "report"},
            }
        ],
    }
    if output_file is not None:
        outputs["output_files"] = [str(output_file)]

    return WorkflowResult(
        outputs={"summary": "done"},
        steps_executed=["step-a"],
        step_results=[
            StepResult(
                step_id="step-a",
                status="success",
                outputs=outputs,
                duration_ms=12.5,
            )
        ],
        duration_ms=12.5,
        status=WorkflowStatus.SUCCESS,
    )


def test_run_archive_persists_run_result_history_and_events_across_restart(tmp_path) -> None:
    archive_root = tmp_path / "workflow-archives"
    service = WorkflowRunArchiveService(archive_root)

    summary = service.start_run(
        "run-123",
        "durable-workflow",
        trigger_type="manual",
        started_at=1_720_000_000.0,
        metadata={"operator": "matt"},
        tenant_id="tenant-a",
    )
    assert summary["status"] == "running"

    service.append_event(
        "run-123",
        WorkflowEvent(
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            run_id="run-123",
            workflow_name="durable-workflow",
            timestamp=1_720_000_001.0,
            data={"step_count": 1},
        ),
    )
    service.append_event(
        "run-123",
        {
            "type": "workflow_completed",
            "run_id": "run-123",
            "workflow_name": "durable-workflow",
            "timestamp": 1_720_000_002.0,
            "data": {"status": "success"},
        },
    )

    history = WorkflowExecutionRecord(
        run_id="run-123",
        workflow_name="durable-workflow",
        trigger_type="manual",
        status="success",
        duration_ms=12.5,
        timestamp=1_720_000_002.0,
        step_statuses={"step-a": "success"},
        tenant_id="tenant-a",
    )
    service.record_result("run-123", _sample_result(), history_record=history)

    restarted = WorkflowRunArchiveService(archive_root)
    assert restarted.has_run("run-123")

    restored_summary = restarted.load_summary("run-123")
    assert restored_summary is not None
    assert restored_summary["workflow_name"] == "durable-workflow"
    assert restored_summary["status"] == "success"
    assert restored_summary["event_count"] == 2
    assert restored_summary["artifact_count"] == 1
    assert restored_summary["metadata"] == {"operator": "matt"}

    detail = restarted.load_detail("run-123")
    assert detail is not None
    assert detail["history"]["step_statuses"] == {"step-a": "success"}
    assert detail["result"]["status"] == "success"
    assert [event["type"] for event in detail["events"]] == [
        "workflow_started",
        "workflow_completed",
    ]
    assert detail["artifacts"][0]["name"] == "report.html"
    assert (
        restarted.read_artifact("run-123", detail["artifacts"][0]["relative_path"])
        == "<div>ok</div>"
    )


def test_run_archive_extracts_inline_and_file_artifacts(tmp_path) -> None:
    archive_root = tmp_path / "workflow-archives"
    output_file = tmp_path / "transcript.txt"
    output_file.write_text("captured stdout", encoding="utf-8")

    service = WorkflowRunArchiveService(archive_root)
    service.start_run("run-artifacts", "artifact-workflow")
    service.record_result("run-artifacts", _sample_result(output_file=output_file))

    artifacts = service.list_artifacts("run-artifacts")
    assert [artifact["name"] for artifact in artifacts] == ["report.html", "transcript.txt"]
    assert service.read_artifact("run-artifacts", artifacts[0]["relative_path"]) == "<div>ok</div>"
    assert (
        service.read_artifact("run-artifacts", artifacts[1]["relative_path"]) == "captured stdout"
    )

    restarted = WorkflowRunArchiveService(archive_root)
    restored_artifacts = restarted.list_artifacts("run-artifacts")
    assert [artifact["name"] for artifact in restored_artifacts] == [
        "report.html",
        "transcript.txt",
    ]
    assert (
        restarted.read_artifact(
            "run-artifacts",
            restored_artifacts[1]["relative_path"],
        )
        == "captured stdout"
    )


@pytest.mark.parametrize("run_id", ["", " ", "../escape", "bad/run", "name with spaces"])
def test_run_archive_rejects_unsafe_run_ids(tmp_path, run_id: str) -> None:
    service = WorkflowRunArchiveService(tmp_path / "workflow-archives")

    with pytest.raises(ValueError):
        service.start_run(run_id, "unsafe-workflow")

    with pytest.raises(ValueError):
        service.has_run(run_id)
