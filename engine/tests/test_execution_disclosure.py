"""Tests for progressive disclosure (L0-L3)."""

from __future__ import annotations

from agent33.execution.disclosure import disclose
from agent33.execution.models import (
    AdapterDefinition,
    AdapterType,
    CLIInterface,
    ErrorHandling,
    RetryConfig,
)


def _sample_definition() -> AdapterDefinition:
    return AdapterDefinition(
        adapter_id="ADP-001",
        name="rg-search",
        version="1.2.0",
        tool_id="TL-003",
        type=AdapterType.CLI,
        cli=CLIInterface(
            executable="rg",
            base_args=["--json"],
            arg_mapping={"pattern": "{pattern}"},
        ),
        error_handling=ErrorHandling(
            retry=RetryConfig(max_attempts=2, backoff_ms=500),
        ),
        sandbox_override={"timeout_ms": 60000},
        metadata={"author": "test-user", "examples": ["rg foo ."]},
    )


class TestDisclosure:
    """Progressive disclosure levels."""

    def test_l0_minimal(self) -> None:
        d = disclose(_sample_definition(), level=0)
        assert d == {
            "adapter_id": "ADP-001",
            "name": "rg-search",
            "tool_id": "TL-003",
            "type": "cli",
        }
        # L0 must NOT include version, status, or interface details
        assert "version" not in d
        assert "status" not in d
        assert "cli" not in d

    def test_l1_adds_summary(self) -> None:
        d = disclose(_sample_definition(), level=1)
        assert d["version"] == "1.2.0"
        assert d["status"] == "active"
        assert d["interface_summary"] == {"executable": "rg"}
        # L1 must NOT include full interface
        assert "cli" not in d
        assert "error_handling" not in d

    def test_l2_adds_full_interface(self) -> None:
        d = disclose(_sample_definition(), level=2)
        assert "cli" in d
        assert d["cli"]["executable"] == "rg"
        assert d["cli"]["base_args"] == ["--json"]
        assert "error_handling" in d
        assert d["error_handling"]["retry"]["max_attempts"] == 2
        assert d["sandbox_override"] == {"timeout_ms": 60000}
        # L2 must NOT include metadata
        assert "metadata" not in d

    def test_l3_includes_metadata(self) -> None:
        d = disclose(_sample_definition(), level=3)
        assert "metadata" in d
        assert d["metadata"]["author"] == "test-user"
        assert "examples" in d["metadata"]
        # L3 includes everything from lower levels
        assert "cli" in d
        assert "version" in d
        assert d["adapter_id"] == "ADP-001"
