"""Stateless HITL approval tokens backed by short-lived JWTs."""

from __future__ import annotations

import hmac
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

import jwt
from pydantic import BaseModel

from agent33.security.arg_hash import canonical_arg_hash

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore
    from agent33.tools.approvals import ToolApprovalRequest

logger = logging.getLogger(__name__)


class ApprovalTokenError(Exception):
    """Raised when an approval token fails validation."""


class ApprovalTokenPayload(BaseModel):
    """Decoded approval-token claims."""

    typ: str = "a33_approval"
    sub: str = ""
    jti: str = ""
    tool: str = ""
    op: str = ""
    arg_hash: str = ""
    tenant_id: str = ""
    scope: str = "tools:execute"
    one_time: bool = True
    exp: int = 0
    iat: int = 0


class ApprovalTokenManager:
    """Issue and validate stateless HITL approval tokens.

    Tokens are JWTs signed with a shared secret.  A ``typ`` claim of
    ``a33_approval`` prevents cross-use with regular auth JWTs.
    """

    def __init__(
        self,
        secret: str,
        algorithm: str = "HS256",
        default_ttl_seconds: int = 300,
        default_one_time: bool = True,
        clock: Any | None = None,
        state_store: OrchestrationStateStore | None = None,
    ) -> None:
        self._secret = secret
        self._algorithm = algorithm
        self._default_ttl_seconds = default_ttl_seconds
        self._default_one_time = default_one_time
        self._clock = clock or time.time
        self._state_store = state_store
        self._lock = threading.RLock()
        # Track consumed one-time tokens (jti -> consumed_at)
        self._consumed: dict[str, float] = {}
        # Emergency revocation set (jti -> revoked_at)
        self._revoked: dict[str, float] = {}
        self._load_state()

    # ------------------------------------------------------------------
    # Issuance
    # ------------------------------------------------------------------

    def issue(
        self,
        approval: ToolApprovalRequest,
        arguments: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
        one_time: bool | None = None,
    ) -> str:
        """Issue a signed approval token for an already-approved request.

        Raises ``ApprovalTokenError`` if the approval is not in ``approved``
        status.
        """
        from agent33.tools.approvals import ApprovalStatus

        if approval.status != ApprovalStatus.APPROVED:
            raise ApprovalTokenError(
                f"Cannot issue token for approval in status={approval.status}"
            )

        now = int(self._clock())
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        one_time_value = self._default_one_time if one_time is None else one_time
        arg_hash = canonical_arg_hash(approval.tool_name, arguments or {})

        claims: dict[str, Any] = {
            "typ": "a33_approval",
            "sub": approval.reviewed_by or approval.requested_by,
            "iss": "agent33",
            "iat": now,
            "exp": now + ttl,
            "jti": approval.approval_id,
            "tool": approval.tool_name,
            "op": approval.operation,
            "arg_hash": arg_hash,
            "tenant_id": approval.tenant_id,
            "scope": "tools:execute",
            "one_time": one_time_value,
        }
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(
        self,
        token: str,
        tool_name: str,
        arguments: dict[str, Any],
        tenant_id: str = "",
        *,
        consume: bool = True,
    ) -> ApprovalTokenPayload:
        """Validate and optionally consume an approval token.

        Raises ``ApprovalTokenError`` on any validation failure.
        """
        with self._lock:
            self._prune_consumed()
            self._prune_revoked()

            try:
                data = jwt.decode(
                    token,
                    self._secret,
                    algorithms=[self._algorithm],
                    options={"require": ["exp", "iat", "typ", "tool", "jti"]},
                )
            except jwt.ExpiredSignatureError as exc:
                raise ApprovalTokenError("Approval token has expired") from exc
            except jwt.InvalidTokenError as exc:
                raise ApprovalTokenError(f"Invalid approval token: {exc}") from exc

            # Validate type claim
            if data.get("typ") != "a33_approval":
                raise ApprovalTokenError("Token is not an approval token (wrong typ)")

            # Validate tool scope
            if data.get("tool") != tool_name:
                raise ApprovalTokenError(
                    f"Token tool mismatch: expected={tool_name}, got={data.get('tool')}"
                )

            # Validate argument hash
            expected_hash = canonical_arg_hash(tool_name, arguments)
            if not hmac.compare_digest(data.get("arg_hash", ""), expected_hash):
                raise ApprovalTokenError("Token argument hash mismatch (arguments were tampered)")

            # Validate tenant scope
            token_tenant = data.get("tenant_id", "")
            if tenant_id and token_tenant and token_tenant != tenant_id:
                raise ApprovalTokenError(
                    f"Token tenant mismatch: expected={tenant_id}, got={token_tenant}"
                )

            payload = ApprovalTokenPayload(**data)

            # Check revocation
            if payload.jti in self._revoked:
                raise ApprovalTokenError("Token has been revoked")

            # Check one-time consumption
            if payload.one_time and payload.jti in self._consumed:
                raise ApprovalTokenError("One-time token has already been consumed")

            if consume and payload.one_time:
                self._consume_locked(payload.jti)

            return payload

    def consume(self, jti: str) -> bool:
        """Consume a one-time token JTI if it has not already been consumed."""
        with self._lock:
            self._prune_consumed()
            if jti in self._consumed:
                return False
            self._consume_locked(jti)
            return True

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def revoke(self, jti: str) -> bool:
        """Add a token JTI to the revocation set."""
        with self._lock:
            if jti in self._revoked:
                return False
            self._revoked[jti] = self._clock()
            self._persist_state()
            return True

    def is_revoked(self, jti: str) -> bool:
        """Check if a JTI has been revoked."""
        with self._lock:
            return jti in self._revoked

    # ------------------------------------------------------------------
    # Pruning
    # ------------------------------------------------------------------

    def _prune_consumed(self) -> None:
        """Remove consumed entries older than 2x default TTL."""
        cutoff = self._clock() - (2 * self._default_ttl_seconds)
        pruned = {jti: ts for jti, ts in self._consumed.items() if ts > cutoff}
        if pruned != self._consumed:
            self._consumed = pruned
            self._persist_state()

    def _prune_revoked(self) -> None:
        """Remove revoked entries older than 2x default TTL."""
        cutoff = self._clock() - (2 * self._default_ttl_seconds)
        pruned = {jti: ts for jti, ts in self._revoked.items() if ts > cutoff}
        if pruned != self._revoked:
            self._revoked = pruned
            self._persist_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            "approval_tokens",
            {
                "consumed": self._consumed,
                "revoked": self._revoked,
            },
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace("approval_tokens")
        consumed = payload.get("consumed", {})
        revoked = payload.get("revoked", {})
        if isinstance(consumed, dict):
            self._consumed = {
                str(jti): float(timestamp)
                for jti, timestamp in consumed.items()
                if isinstance(jti, str) and isinstance(timestamp, (int, float))
            }
        if isinstance(revoked, dict):
            self._revoked = {
                str(jti): float(timestamp)
                for jti, timestamp in revoked.items()
                if isinstance(jti, str) and isinstance(timestamp, (int, float))
            }

    def _consume_locked(self, jti: str) -> None:
        self._consumed[jti] = self._clock()
        self._persist_state()
