"""Tests for execution contract input validation (IV-01 through IV-05)."""

from __future__ import annotations

from agent33.execution.models import ExecutionContract, ExecutionInputs, OutputSpec
from agent33.execution.validation import (
    check_argument_sanitization,
    check_command_allowlist,
    check_environment_filtering,
    check_input_size,
    check_path_traversal,
    validate_contract,
)


class TestIV01CommandAllowlist:
    """IV-01: Command allowlist check."""

    def test_no_allowlist_passes(self) -> None:
        assert check_command_allowlist("anything", None) is None

    def test_allowed_command(self) -> None:
        assert check_command_allowlist("rg", {"rg", "echo"}) is None

    def test_blocked_command(self) -> None:
        v = check_command_allowlist("rm", {"rg", "echo"})
        assert v is not None
        assert "IV-01" in v
        assert "rm" in v


class TestIV02ArgumentSanitization:
    """IV-02: Shell metacharacter detection in arguments."""

    def test_clean_args(self) -> None:
        assert check_argument_sanitization(["hello", "world", "123"]) is None

    def test_semicolon(self) -> None:
        v = check_argument_sanitization(["hello; rm -rf /"])
        assert v is not None
        assert "IV-02" in v

    def test_pipe(self) -> None:
        v = check_argument_sanitization(["cat file | grep secret"])
        assert v is not None
        assert "IV-02" in v

    def test_dollar(self) -> None:
        v = check_argument_sanitization(["$HOME"])
        assert v is not None
        assert "IV-02" in v

    def test_backtick(self) -> None:
        v = check_argument_sanitization(["`whoami`"])
        assert v is not None
        assert "IV-02" in v


class TestIV03PathTraversal:
    """IV-03: Path traversal detection."""

    def test_clean_paths(self) -> None:
        assert check_path_traversal(["/project/src", "/project/out"]) is None

    def test_dot_dot(self) -> None:
        v = check_path_traversal(["../../etc/passwd"])
        assert v is not None
        assert "IV-03" in v

    def test_etc_path(self) -> None:
        v = check_path_traversal(["/etc/shadow"])
        assert v is not None
        assert "IV-03" in v

    def test_windows_path(self) -> None:
        v = check_path_traversal(["C:\\Windows\\System32"])
        assert v is not None
        assert "IV-03" in v


class TestIV04EnvironmentFiltering:
    """IV-04: Dangerous environment variable detection."""

    def test_clean_env(self) -> None:
        assert check_environment_filtering({"LANG": "C", "HOME": "/home/user"}) is None

    def test_ld_preload(self) -> None:
        v = check_environment_filtering({"LD_PRELOAD": "/tmp/evil.so"})
        assert v is not None
        assert "IV-04" in v
        assert "LD_PRELOAD" in v

    def test_node_options(self) -> None:
        v = check_environment_filtering({"NODE_OPTIONS": "--require /tmp/evil.js"})
        assert v is not None
        assert "IV-04" in v


class TestIV05InputSize:
    """IV-05: stdin size validation."""

    def test_small_stdin(self) -> None:
        assert check_input_size("hello world") is None

    def test_none_stdin(self) -> None:
        assert check_input_size(None) is None

    def test_oversized_stdin(self) -> None:
        big = "x" * (1_048_576 + 1)
        v = check_input_size(big)
        assert v is not None
        assert "IV-05" in v


class TestValidateContract:
    """Aggregate validate_contract() function."""

    def _make_contract(self, **overrides: object) -> ExecutionContract:
        inputs_data = {
            "command": "echo",
            "arguments": ["hello"],
            "environment": {},
        }
        if "inputs" in overrides:
            inputs_data.update(overrides.pop("inputs"))  # type: ignore[arg-type]
        defaults = {
            "tool_id": "TL-001",
            "inputs": ExecutionInputs(**inputs_data),
        }
        defaults.update(overrides)  # type: ignore[arg-type]
        return ExecutionContract(**defaults)  # type: ignore[arg-type]

    def test_clean_contract_passes(self) -> None:
        c = self._make_contract()
        result = validate_contract(c)
        assert result.is_valid is True
        assert result.violations == []

    def test_multiple_violations_accumulate(self) -> None:
        c = self._make_contract(
            inputs={
                "command": "rm",
                "arguments": ["file; echo pwned"],
                "environment": {"LD_PRELOAD": "/tmp/evil.so"},
            },
            outputs=OutputSpec(output_files=["../../secret"]),
        )
        result = validate_contract(c, command_allowlist={"echo"})
        assert result.is_valid is False
        # At least command allowlist, argument sanitization, env, and path checks
        assert len(result.violations) >= 4
        codes = [v[:5] for v in result.violations]
        assert "IV-01" in codes
        assert "IV-02" in codes
        assert "IV-03" in codes
        assert "IV-04" in codes

    def test_allowlist_none_skips_check(self) -> None:
        c = self._make_contract()
        result = validate_contract(c, command_allowlist=None)
        assert result.is_valid is True
