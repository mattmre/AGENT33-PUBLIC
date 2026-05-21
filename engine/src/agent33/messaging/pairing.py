"""Pairing code manager for linking platform users to AGENT-33 accounts."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from agent33.messaging.models import PairingRequest

logger = logging.getLogger(__name__)

_TTL_MINUTES = 15
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_MINUTES = 15


class PairingManager:
    """Generate and verify six-digit pairing codes with automatic expiry
    and brute-force lockout."""

    def __init__(self) -> None:
        self._codes: dict[str, PairingRequest] = {}
        self._cleanup_task: asyncio.Task[None] | None = None
        # Track failed verification attempts per user_id
        self._failed_attempts: dict[str, list[datetime]] = defaultdict(list)

    async def start(self) -> None:
        """Begin periodic cleanup of expired codes."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

    def generate_code(self, platform: str, user_id: str) -> str:
        """Create a six-digit pairing code with a 15-minute TTL.

        If the user already has an active code it is replaced.
        """
        code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.now(UTC) + timedelta(minutes=_TTL_MINUTES)
        self._codes[code] = PairingRequest(
            platform=platform,
            user_id=user_id,
            code=code,
            expires_at=expires_at,
        )
        logger.info(
            "Pairing code generated for %s/%s (expires %s)",
            platform,
            user_id,
            expires_at.isoformat(),
        )
        return code

    def is_locked_out(self, user_id: str) -> bool:
        """Return ``True`` if the user is currently locked out due to too many
        failed verification attempts."""
        attempts = self._failed_attempts.get(user_id, [])
        if not attempts:
            return False
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=_LOCKOUT_MINUTES)
        recent = [a for a in attempts if a > cutoff]
        self._failed_attempts[user_id] = recent
        return len(recent) >= _MAX_FAILED_ATTEMPTS

    def verify_code(self, code: str, user_id: str) -> bool:
        """Verify and consume a pairing code.

        Returns ``True`` if the code is valid, not expired, and matches the
        user.  A consumed code is removed immediately.

        Returns ``False`` and records a failed attempt if verification fails.
        After ``_MAX_FAILED_ATTEMPTS`` failures within ``_LOCKOUT_MINUTES``,
        further attempts are rejected until the lockout window expires.
        """
        # Check lockout first
        if self.is_locked_out(user_id):
            logger.warning("Pairing verification locked out for user %s", user_id)
            return False

        request = self._codes.get(code)
        if request is None:
            self._record_failure(user_id)
            return False
        if datetime.now(UTC) > request.expires_at:
            del self._codes[code]
            self._record_failure(user_id)
            return False
        if request.user_id != user_id:
            self._record_failure(user_id)
            return False
        del self._codes[code]
        # Reset failed attempts on success
        self._failed_attempts.pop(user_id, None)
        return True

    def _record_failure(self, user_id: str) -> None:
        """Record a failed verification attempt."""
        self._failed_attempts[user_id].append(datetime.now(UTC))
        count = len(self._failed_attempts[user_id])
        if count >= _MAX_FAILED_ATTEMPTS:
            logger.warning(
                "Pairing brute-force lockout triggered for user %s (%d attempts)",
                user_id,
                count,
            )

    def _purge_expired(self) -> int:
        now = datetime.now(UTC)
        expired = [k for k, v in self._codes.items() if now > v.expires_at]
        for k in expired:
            del self._codes[k]
        return len(expired)

    async def _cleanup_loop(self) -> None:
        """Periodically remove expired codes."""
        while True:
            await asyncio.sleep(60)
            n = self._purge_expired()
            if n:
                logger.debug("Purged %d expired pairing codes", n)
