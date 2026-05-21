"""Progressive disclosure (L0-L3) for adapter definitions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.execution.models import AdapterDefinition


def disclose(definition: AdapterDefinition, level: int = 0) -> dict[str, Any]:
    """Return adapter information at the requested disclosure level.

    Levels:

    - **L0**: adapter_id, name, tool_id, type
    - **L1**: + interface summary (executable or base_url), version, status
    - **L2**: + full interface details, error handling, sandbox overrides
    - **L3**: + metadata (examples, fixtures)

    Args:
        definition: The adapter definition to disclose.
        level: Disclosure level (0-3). Values outside range are clamped.

    Returns:
        A dict with the disclosed information.
    """
    level = max(0, min(3, level))

    # L0 — minimal identification
    data: dict[str, Any] = {
        "adapter_id": definition.adapter_id,
        "name": definition.name,
        "tool_id": definition.tool_id,
        "type": definition.type.value,
    }

    if level >= 1:
        data["version"] = definition.version
        data["status"] = definition.status.value

        # Interface summary: show the key identifying field only.
        if definition.cli is not None:
            data["interface_summary"] = {
                "executable": definition.cli.executable,
            }
        elif definition.api is not None:
            data["interface_summary"] = {
                "base_url": definition.api.base_url,
            }
        else:
            data["interface_summary"] = {}

    if level >= 2:
        # Full interface details
        if definition.cli is not None:
            data["cli"] = definition.cli.model_dump()
        if definition.api is not None:
            data["api"] = definition.api.model_dump()
        data["error_handling"] = definition.error_handling.model_dump()
        if definition.sandbox_override:
            data["sandbox_override"] = definition.sandbox_override

    if level >= 3:
        data["metadata"] = definition.metadata

    return data
