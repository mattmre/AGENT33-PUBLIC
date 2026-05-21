"""Governance policy abstractions for connector boundary calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import structlog

if TYPE_CHECKING:
    from agent33.connectors.models import ConnectorRequest

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    """Result of a governance policy evaluation."""

    allowed: bool
    reason: str = ""


class ConnectorGovernancePolicy(Protocol):
    """Policy contract used by connector governance middleware."""

    def evaluate(self, request: ConnectorRequest) -> GovernanceDecision:
        """Return whether *request* is allowed to proceed."""
        ...


@dataclass(frozen=True, slots=True)
class AllowAllConnectorPolicy:
    """Default permissive policy."""

    def evaluate(self, request: ConnectorRequest) -> GovernanceDecision:  # noqa: ARG002
        return GovernanceDecision(allowed=True)


@dataclass(frozen=True, slots=True)
class BlocklistConnectorPolicy:
    """Simple blocklist policy for connectors and operations."""

    blocked_connectors: frozenset[str] = field(default_factory=frozenset)
    blocked_operations: frozenset[str] = field(default_factory=frozenset)

    def evaluate(self, request: ConnectorRequest) -> GovernanceDecision:
        if request.connector in self.blocked_connectors:
            return GovernanceDecision(
                allowed=False,
                reason=f"connector blocked by policy: {request.connector}",
            )
        if request.operation in self.blocked_operations:
            return GovernanceDecision(
                allowed=False,
                reason=f"operation blocked by policy: {request.operation}",
            )
        return GovernanceDecision(allowed=True)
