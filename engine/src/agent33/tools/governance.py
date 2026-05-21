"""Tool governance: permission checks, autonomy enforcement, rate limiting, and audit logging."""

from __future__ import annotations

import fnmatch
import json
import logging
import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from agent33.config import settings
from agent33.security.approval_tokens import ApprovalTokenError, ApprovalTokenManager
from agent33.security.permissions import check_permission
from agent33.tools.approvals import (
    ApprovalReason,
    ApprovalRiskTier,
    ToolApprovalService,
)

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.agents.definition import AutonomyLevel
    from agent33.tools.base import ToolContext, ToolResult

logger = logging.getLogger(__name__)

# Structured audit log
_audit_logger = logging.getLogger("agent33.tools.audit")

# Patterns that indicate command chaining / subshell injection
_CHAIN_OPERATORS = re.compile(r"[|;&]|&&|\|\|")
_SUBSHELL_PATTERNS = re.compile(r"\$\(|`")

# Tools that always perform write/execute operations (blocked in read-only mode)
_WRITE_TOOLS: frozenset[str] = frozenset({"shell", "browser"})
_DESTRUCTIVE_PARAMS: dict[str, set[str]] = {
    "file_ops": {"write"},  # operation=write is destructive
    "apply_patch": {"apply"},
}


class _RateLimiter:
    """Sliding-window rate limiter keyed by subject."""

    def __init__(self, per_minute: int, burst: int) -> None:
        self._per_minute = per_minute
        self._burst = burst
        # subject -> list of timestamps
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, subject: str) -> bool:
        """Return ``True`` if the request is within rate limits."""
        now = time.monotonic()
        window = self._windows[subject]
        # Purge entries older than 60s
        cutoff = now - 60.0
        self._windows[subject] = window = [t for t in window if t > cutoff]

        if len(window) >= self._per_minute:
            return False

        # Burst check: no more than `burst` requests in the last 1 second
        one_sec_ago = now - 1.0
        recent = sum(1 for t in window if t > one_sec_ago)
        if recent >= self._burst:
            return False

        window.append(now)
        return True


class ToolGovernance:
    """Pre-execution permission checks, autonomy enforcement, rate limiting,
    and post-execution audit logging."""

    # Map of tool names to the scope required to invoke them.
    # Tools not listed here default to ``tools:execute``.
    TOOL_SCOPE_MAP: dict[str, str] = {}

    def __init__(
        self,
        approval_service: ToolApprovalService | None = None,
        approval_token_manager: ApprovalTokenManager | None = None,
    ) -> None:
        self._rate_limiter = _RateLimiter(
            per_minute=settings.rate_limit_per_minute,
            burst=settings.rate_limit_burst,
        )
        self._approval_service = approval_service
        self._approval_token_manager = approval_token_manager
        self._approved_tools: set[str] = set()

    @property
    def approved_tools(self) -> frozenset[str]:
        """Return the set of globally approved tool names (read-only)."""
        return frozenset(self._approved_tools)

    def load_approved_tools_file(self, path: Path) -> None:
        """Load CLI-approved tools from a JSON file.

        The file is expected to be a JSON object whose keys are tool names
        (values are metadata dicts with ``approved_at`` and ``reason``).
        Tool names are added to the internal approved set, which is
        additive to existing approvals (never replaces).

        Silently skips if the file does not exist or cannot be parsed.
        """
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to load approved tools from %s", path)
            return
        if not isinstance(data, dict):
            logger.warning("Approved tools file has invalid format: %s", path)
            return
        added = 0
        for tool_name in data:
            if isinstance(tool_name, str) and tool_name.strip():
                self._approved_tools.add(tool_name.strip())
                added += 1
        if added:
            logger.info("Loaded %d approved tools from %s", added, path)

    def set_approval_service(self, approval_service: ToolApprovalService | None) -> None:
        """Set or clear the approval service used for ask/supervised policies."""
        self._approval_service = approval_service

    def set_approval_token_manager(
        self, approval_token_manager: ApprovalTokenManager | None
    ) -> None:
        """Set or clear the approval-token manager used for governed execution."""
        self._approval_token_manager = approval_token_manager

    def pre_execute_check(
        self,
        tool_name: str,
        params: dict[str, Any],
        context: ToolContext,
        autonomy_level: AutonomyLevel | None = None,
    ) -> bool:
        """Return ``True`` if the current context is allowed to run the tool.

        Checks (in order):
        0. Tool-specific governance policies (from context.tool_policies).
        1. Rate limiting (per-subject sliding window).
        2. Autonomy level enforcement.
        3. The user has the required scope (``tools:execute`` by default).
        4. For the shell tool, the command passes multi-segment validation.
        5. For file operations, the path is within the path allowlist.
        6. For web fetch, the domain is in the domain allowlist.
        """
        # --- Tool-specific governance policies ---
        operation = self._resolve_operation(tool_name, params)
        approval_validated = False
        if context.tool_policies:
            policy_result = self._check_tool_policy(tool_name, params, context)
            if policy_result is not None:
                # Policy explicitly allowed, denied, or asked
                if policy_result == "deny":
                    logger.warning("Tool policy denied: tool=%s", tool_name)
                    return False
                if policy_result == "ask":
                    # CLI-approved tools bypass the ask policy
                    if tool_name in self._approved_tools:
                        logger.info("Tool approved via CLI: tool=%s (skipping ask)", tool_name)
                        # Fall through to normal checks (same as "allow")
                    else:
                        if self._try_consume_approval(
                            params=params,
                            tool_name=tool_name,
                            operation=operation,
                            tenant_id=context.tenant_id,
                            consume=False,
                        ):
                            approval_validated = True
                        else:
                            if self._approval_service is not None:
                                approval = self._approval_service.request(
                                    reason=ApprovalReason.TOOL_POLICY_ASK,
                                    tool_name=tool_name,
                                    operation=operation,
                                    command=str(params.get("command", "")),
                                    requested_by=context.requested_by,
                                    tenant_id=context.tenant_id,
                                    details="Tool policy requires operator approval.",
                                    arguments=self._sanitize_approval_arguments(params),
                                    risk_tier=ApprovalRiskTier.MEDIUM,
                                )
                                logger.info(
                                    "Tool policy requires approval: tool=%s approval_id=%s",
                                    tool_name,
                                    approval.approval_id,
                                )
                            else:
                                logger.info("Tool policy requires approval: tool=%s", tool_name)
                            logger.info(
                                "Tool policy approval pending: tool=%s (blocking)",
                                tool_name,
                            )
                            return False
                # "allow" continues to normal checks

        # --- Rate limiting ---
        subject = context.user_scopes[0] if context.user_scopes else "__anon__"
        if not self._rate_limiter.check(subject):
            logger.warning("Rate limit exceeded for subject=%s", subject)
            return False

        # --- Autonomy level enforcement ---
        if autonomy_level is not None:
            from agent33.agents.definition import AutonomyLevel

            if autonomy_level == AutonomyLevel.READ_ONLY and self._is_write_operation(
                tool_name, operation
            ):
                logger.warning("Autonomy denied: tool=%s blocked in read-only mode", tool_name)
                return False
            if (
                autonomy_level == AutonomyLevel.SUPERVISED
                and tool_name in _DESTRUCTIVE_PARAMS
                and operation in _DESTRUCTIVE_PARAMS[tool_name]
                and not approval_validated
            ):
                if self._try_consume_approval(
                    params=params,
                    tool_name=tool_name,
                    operation=operation,
                    tenant_id=context.tenant_id,
                    consume=False,
                ):
                    approval_validated = True
                else:
                    if self._approval_service is not None:
                        approval = self._approval_service.request(
                            reason=ApprovalReason.SUPERVISED_DESTRUCTIVE,
                            tool_name=tool_name,
                            operation=operation,
                            command=str(params.get("command", "")),
                            requested_by=context.requested_by,
                            tenant_id=context.tenant_id,
                            details="Supervised autonomy requires operator approval.",
                            arguments=self._sanitize_approval_arguments(params),
                            risk_tier=ApprovalRiskTier.HIGH,
                        )
                        logger.info(
                            ("Supervised approval required: tool=%s operation=%s approval_id=%s"),
                            tool_name,
                            operation,
                            approval.approval_id,
                        )
                    else:
                        logger.info(
                            "Supervised approval required: tool=%s operation=%s",
                            tool_name,
                            operation,
                        )
                    return False

        # --- Scope check ---
        required_scope = self.TOOL_SCOPE_MAP.get(tool_name, "tools:execute")
        if not check_permission(required_scope, context.user_scopes):
            logger.warning(
                "Permission denied: tool=%s scope=%s user_scopes=%s",
                tool_name,
                required_scope,
                context.user_scopes,
            )
            return False

        # --- Shell: multi-segment command validation ---
        if tool_name == "shell":
            command = params.get("command", "")
            if not self._validate_command(command, context):
                return False

        # --- File ops: path allowlist ---
        if tool_name == "file_ops" and context.path_allowlist:
            path = params.get("path", "")
            if not any(path.startswith(allowed) for allowed in context.path_allowlist):
                logger.warning(
                    "Path not in allowlist: %s (allowed: %s)",
                    path,
                    context.path_allowlist,
                )
                return False

        # --- Web fetch: domain allowlist ---
        if tool_name == "web_fetch" and context.domain_allowlist:
            url = params.get("url", "")
            from urllib.parse import urlparse

            domain = urlparse(url).hostname or ""
            if not any(
                domain == allowed or domain.endswith(f".{allowed}")
                for allowed in context.domain_allowlist
            ):
                logger.warning(
                    "Domain not in allowlist: %s (allowed: %s)",
                    domain,
                    context.domain_allowlist,
                )
                return False

        if approval_validated and not self._try_consume_approval(
            params=params,
            tool_name=tool_name,
            operation=operation,
            tenant_id=context.tenant_id,
            consume=True,
        ):
            logger.warning("Approval consumption failed after validation: tool=%s", tool_name)
            return False

        return True

    def _try_consume_approval(
        self,
        params: dict[str, Any],
        tool_name: str,
        operation: str,
        tenant_id: str,
        *,
        consume: bool,
    ) -> bool:
        """Consume a matching approved request via approval token or approval ID."""
        sanitized_params = self._sanitize_approval_arguments(params)
        approval_token = params.get("__approval_token")
        if (
            isinstance(approval_token, str)
            and approval_token
            and self._approval_token_manager is not None
        ):
            try:
                payload = self._approval_token_manager.validate(
                    approval_token,
                    tool_name,
                    sanitized_params,
                    tenant_id=tenant_id,
                    consume=False,
                )
            except ApprovalTokenError as exc:
                logger.info("Approval token rejected: tool=%s error=%s", tool_name, exc)
                return False
            if self._approval_service is None:
                return (
                    not consume
                    or (not payload.one_time)
                    or self._approval_token_manager.consume(payload.jti)
                )
            if not consume:
                return self._approval_service.is_approved(
                    payload.jti,
                    tool_name=tool_name,
                    operation=operation,
                    tenant_id=tenant_id,
                )
            consumed = self._approval_service.consume_if_approved(
                payload.jti,
                tool_name=tool_name,
                operation=operation,
                tenant_id=tenant_id,
            )
            if not consumed:
                return False
            return (not payload.one_time) or self._approval_token_manager.consume(payload.jti)

        if self._approval_service is None:
            return False
        approval_id = params.get("__approval_id")
        if not isinstance(approval_id, str) or not approval_id:
            return False
        if not consume:
            return self._approval_service.is_approved(
                approval_id,
                tool_name=tool_name,
                operation=operation,
                tenant_id=tenant_id,
            )
        return self._approval_service.consume_if_approved(
            approval_id,
            tool_name=tool_name,
            operation=operation,
            tenant_id=tenant_id,
        )

    @staticmethod
    def _sanitize_approval_arguments(params: dict[str, Any]) -> dict[str, object]:
        """Remove transport-only approval keys before hashing or persisting arguments."""
        return {
            key: value
            for key, value in params.items()
            if key not in {"__approval_id", "__approval_token"}
        }

    def _check_tool_policy(
        self,
        tool_name: str,
        params: dict[str, Any],
        context: ToolContext,
    ) -> str | None:
        """Evaluate tool_policies for this tool invocation.

        Returns:
            "allow" if explicitly allowed
            "deny" if explicitly denied
            "ask" if requires approval
            None if no matching policy (continue to normal checks)

        Policy keys support:
        - Exact tool name: "shell"
        - Wildcard tool pattern: "file_*", "*"
        - Tool with operation suffix: "file_ops:write", "file_ops:*"

        Precedence (most specific to least):
        1. Exact operation match: "file_ops:write"
        2. Exact tool match: "file_ops"
        3. Wildcard operation match: "file_*:write"
        4. Wildcard tool match: "file_*"
        5. Global wildcard: "*"
        """
        policies = context.tool_policies
        if not policies:
            return None

        operation = self._resolve_operation(tool_name, params)

        # 1. Check exact operation match first (most specific)
        if operation:
            exact_op_key = f"{tool_name}:{operation}"
            if exact_op_key in policies:
                return policies[exact_op_key].lower()

            exact_wildcard_op_key = f"{tool_name}:*"
            if exact_wildcard_op_key in policies:
                return policies[exact_wildcard_op_key].lower()

        # 2. Check exact tool name match
        if tool_name in policies:
            return policies[tool_name].lower()

        # 3. Check wildcard operation patterns (sorted by length for specificity)
        if operation:
            wildcard_op_keys = [
                k for k in policies if ":" in k and ("*" in k or "?" in k or "[" in k)
            ]
            wildcard_op_keys.sort(key=len, reverse=True)

            for pattern_key in wildcard_op_keys:
                parts = pattern_key.split(":", 1)
                if len(parts) == 2:
                    tool_pattern, op_pattern = parts
                    if fnmatch.fnmatch(tool_name, tool_pattern) and (
                        op_pattern == "*" or fnmatch.fnmatch(operation, op_pattern)
                    ):
                        return policies[pattern_key].lower()

        # 4. Check wildcard tool patterns (sorted by length for specificity)
        wildcard_tool_keys = [
            k for k in policies if ":" not in k and ("*" in k or "?" in k or "[" in k) and k != "*"
        ]
        wildcard_tool_keys.sort(key=len, reverse=True)

        for pattern in wildcard_tool_keys:
            if fnmatch.fnmatch(tool_name, pattern):
                return policies[pattern].lower()

        # 5. Check global wildcard (least specific)
        if "*" in policies:
            return policies["*"].lower()

        return None

    @staticmethod
    def _resolve_operation(tool_name: str, params: dict[str, Any]) -> str:
        """Return the effective operation name for a tool invocation."""
        if tool_name == "apply_patch":
            return "preview" if bool(params.get("dry_run", False)) else "apply"
        return str(params.get("operation", ""))

    @staticmethod
    def _is_write_operation(tool_name: str, operation: str) -> bool:
        """Return True when the invocation mutates state."""
        return tool_name in _WRITE_TOOLS or (
            tool_name in _DESTRUCTIVE_PARAMS and operation in _DESTRUCTIVE_PARAMS[tool_name]
        )

    def _validate_command(self, command: str, context: ToolContext) -> bool:
        """Validate a shell command, checking all segments against the allowlist.

        Multi-segment validation (inspired by ZeroClaw ``security/policy.rs``):
        1. Reject subshell patterns: ``$(...)`` and backticks.
        2. Split on chain operators: ``|``, ``&&``, ``||``, ``;``.
        3. Validate every segment's executable against the allowlist.
        """
        if not command:
            return True

        # Block subshell injection
        if _SUBSHELL_PATTERNS.search(command):
            logger.warning("Subshell injection blocked: %s", command[:100])
            return False

        if not context.command_allowlist:
            # No allowlist configured — allow (governance is opt-in per-agent)
            return True

        # Split on chain operators and validate each segment
        segments = _CHAIN_OPERATORS.split(command)
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue
            executable = segment.split()[0] if segment.split() else ""
            if executable and executable not in context.command_allowlist:
                logger.warning(
                    "Command not in allowlist: %s (segment of: %s, allowed: %s)",
                    executable,
                    command[:100],
                    context.command_allowlist,
                )
                return False

        return True

    def log_execution(
        self,
        tool_name: str,
        params: dict[str, Any],
        result: ToolResult,
    ) -> None:
        """Write a structured audit log entry for a tool execution."""
        _audit_logger.info(
            "tool_execution",
            extra={
                "tool": tool_name,
                "params": params,
                "success": result.success,
                "error": result.error or None,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
