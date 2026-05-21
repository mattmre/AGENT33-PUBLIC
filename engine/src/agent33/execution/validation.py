"""Input validation for execution contracts (IV-01 through IV-05)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.execution.models import ExecutionContract

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# IV-02: Shell metacharacters that could enable injection.
_SHELL_METACHAR_PATTERN = re.compile(r"[;|&$`(){}\[\]<>\\\"'!#*?]")

# IV-03: Path traversal / sensitive path patterns.
_PATH_TRAVERSAL_PATTERNS = (
    "..",
    "/etc/",
    "/var/",
    "C:\\Windows",
    "c:\\windows",
)

# IV-04: Environment variables that must be stripped.
_DANGEROUS_ENV_VARS = frozenset(
    {
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "PYTHONPATH",
        "NODE_OPTIONS",
    }
)

# IV-05: Maximum stdin size in bytes (1 MB).
_MAX_STDIN_BYTES = 1_048_576


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """Outcome of contract validation."""

    is_valid: bool = True
    violations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_command_allowlist(
    command: str,
    allowlist: set[str] | None = None,
) -> str | None:
    """IV-01: Verify *command* is in the allowlist.

    Returns a violation string if the check fails, ``None`` if it passes.
    When *allowlist* is ``None`` (no allowlist configured), the check passes.
    """
    if allowlist is None:
        return None
    if command not in allowlist:
        return f"IV-01: Command '{command}' is not in the allowlist"
    return None


def check_argument_sanitization(arguments: list[str]) -> str | None:
    """IV-02: Detect shell metacharacters in arguments.

    Returns a violation string if dangerous characters are found.
    """
    for arg in arguments:
        if _SHELL_METACHAR_PATTERN.search(arg):
            return f"IV-02: Argument contains shell metacharacters: '{arg[:80]}'"
    return None


def check_path_traversal(paths: list[str]) -> str | None:
    """IV-03: Detect path traversal in file paths.

    Checks working_directory, input_files, and output_files for suspicious
    patterns like ``../`` or references to sensitive system directories.
    """
    for path in paths:
        for pattern in _PATH_TRAVERSAL_PATTERNS:
            if pattern in path:
                return f"IV-03: Path traversal or sensitive path detected: '{path[:120]}'"
    return None


def check_environment_filtering(environment: dict[str, str]) -> str | None:
    """IV-04: Detect dangerous environment variables.

    Returns a violation if any banned variable is present.
    """
    found = _DANGEROUS_ENV_VARS & set(environment.keys())
    if found:
        return f"IV-04: Dangerous environment variables detected: {sorted(found)}"
    return None


def check_input_size(stdin: str | None) -> str | None:
    """IV-05: Validate that stdin does not exceed the size limit.

    Returns a violation if stdin exceeds 1 MB (encoded as UTF-8).
    """
    if stdin is not None and len(stdin.encode("utf-8")) > _MAX_STDIN_BYTES:
        return f"IV-05: Stdin exceeds maximum size of {_MAX_STDIN_BYTES} bytes"
    return None


# ---------------------------------------------------------------------------
# Aggregate validator
# ---------------------------------------------------------------------------


def validate_contract(
    contract: ExecutionContract,
    *,
    command_allowlist: set[str] | None = None,
) -> ValidationResult:
    """Run all validation checks against *contract*.

    Args:
        contract: The execution contract to validate.
        command_allowlist: Optional set of permitted command names.

    Returns:
        A :class:`ValidationResult` indicating validity and any violations.
    """
    violations: list[str] = []
    inputs = contract.inputs

    # IV-01
    v = check_command_allowlist(inputs.command, command_allowlist)
    if v:
        violations.append(v)

    # IV-02
    v = check_argument_sanitization(inputs.arguments)
    if v:
        violations.append(v)

    # IV-03 — collect all paths from the contract
    all_paths: list[str] = list(inputs.input_files)
    if inputs.working_directory:
        all_paths.append(inputs.working_directory)
    all_paths.extend(contract.outputs.output_files)
    v = check_path_traversal(all_paths)
    if v:
        violations.append(v)

    # IV-04
    v = check_environment_filtering(inputs.environment)
    if v:
        violations.append(v)

    # IV-05
    v = check_input_size(inputs.stdin)
    if v:
        violations.append(v)

    return ValidationResult(
        is_valid=len(violations) == 0,
        violations=violations,
    )
