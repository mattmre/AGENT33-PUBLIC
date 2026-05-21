from __future__ import annotations

from types import SimpleNamespace

from agent33.operator.status_line import StatusLineService


async def test_status_line_health_is_ok_without_shell_hook(tmp_path) -> None:
    service = StatusLineService(
        app_state=SimpleNamespace(
            operator_session_service=object(),
            script_hook_discovery=SimpleNamespace(discovered_hooks={}),
        ),
        workspace_root=tmp_path,
    )

    snapshot = await service.health_snapshot()

    assert snapshot["status"] == "ok"
    assert snapshot["hook_present"] is False
