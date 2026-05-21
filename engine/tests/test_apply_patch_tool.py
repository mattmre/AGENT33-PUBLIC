"""Tests for the governed apply_patch tool."""

from __future__ import annotations

import json

from agent33.tools.base import ToolContext
from agent33.tools.builtin.apply_patch import ApplyPatchTool
from agent33.tools.mutation_audit import MutationAuditStore


def _context(tmp_path, *, tenant_id: str = "tenant-a") -> ToolContext:
    return ToolContext(
        user_scopes=["tools:execute"],
        path_allowlist=[str(tmp_path)],
        working_dir=tmp_path,
        requested_by="tester",
        tenant_id=tenant_id,
    )


async def test_apply_patch_dry_run_previews_without_writing(tmp_path) -> None:
    store = MutationAuditStore()
    tool = ApplyPatchTool(audit_store=store)
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: notes.txt",
            "+hello",
            "+world",
            "*** End Patch",
        ]
    )

    result = await tool.execute({"patch": patch, "dry_run": True}, _context(tmp_path))

    assert result.success is True
    assert not (tmp_path / "notes.txt").exists()
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["operations"][0]["action"] == "add"
    records = store.list_records(tenant_id="tenant-a")
    assert len(records) == 1
    assert records[0].status == "preview"


async def test_apply_patch_updates_and_moves_file(tmp_path) -> None:
    source = tmp_path / "src.txt"
    source.write_text("alpha\nbeta\n", encoding="utf-8")
    store = MutationAuditStore()
    tool = ApplyPatchTool(audit_store=store)
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Update File: src.txt",
            "*** Move to: nested/dst.txt",
            "@@",
            " alpha",
            "-beta",
            "+gamma",
            "*** End Patch",
        ]
    )

    result = await tool.execute({"patch": patch}, _context(tmp_path))

    assert result.success is True
    assert not source.exists()
    assert (tmp_path / "nested" / "dst.txt").read_text(encoding="utf-8") == "alpha\ngamma\n"
    record = store.list_records(tenant_id="tenant-a")[0]
    assert record.status == "applied"
    assert record.files[0].new_path.replace("\\", "/").endswith("nested/dst.txt")


async def test_apply_patch_handles_delete_operation(tmp_path) -> None:
    doomed = tmp_path / "obsolete.txt"
    doomed.write_text("old\n", encoding="utf-8")
    tool = ApplyPatchTool()
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Delete File: obsolete.txt",
            "*** End Patch",
        ]
    )

    result = await tool.execute({"patch": patch}, _context(tmp_path))

    assert result.success is True
    assert not doomed.exists()


async def test_apply_patch_rejects_workspace_escape_and_records_failure(tmp_path) -> None:
    store = MutationAuditStore()
    tool = ApplyPatchTool(audit_store=store)
    patch = "\n".join(
        [
            "*** Begin Patch",
            "*** Add File: ../escape.txt",
            "+nope",
            "*** End Patch",
        ]
    )

    result = await tool.execute({"patch": patch}, _context(tmp_path))

    assert result.success is False
    assert "escapes the allowed workspace" in result.error
    records = store.list_records(tenant_id="tenant-a")
    assert len(records) == 1
    assert records[0].status == "failed"
