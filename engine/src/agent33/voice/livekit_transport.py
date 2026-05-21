"""LiveKit media transport for the voice sidecar.

Provides room management, participant tracking, JWT access token generation,
and health checking for LiveKit-based real-time media transport.

S32: Real LiveKit media transport lives in the sidecar process, not the main
runtime. This module uses PyJWT (already a project dependency) for access
token generation compatible with the LiveKit access token format.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import jwt

logger = logging.getLogger(__name__)


@dataclass
class LiveKitConfig:
    """Configuration for the LiveKit media transport."""

    api_key: str = ""
    api_secret: str = ""
    ws_url: str = ""  # e.g., "wss://my-livekit.example.com"
    room_prefix: str = "agent33-"
    default_codec: str = "opus"
    max_participants: int = 10
    token_ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.max_participants < 1:
            raise ValueError("max_participants must be at least 1")
        if self.token_ttl_seconds < 1:
            raise ValueError("token_ttl_seconds must be at least 1")
        if self.default_codec not in {"opus", "vp8", "vp9", "h264", "av1"}:
            raise ValueError(
                f"default_codec must be one of: opus, vp8, vp9, h264, av1; "
                f"got {self.default_codec!r}"
            )

    @property
    def is_configured(self) -> bool:
        """Return True if the essential connection parameters are set."""
        return bool(self.api_key and self.api_secret and self.ws_url)


@dataclass
class LiveKitRoom:
    """Represents a LiveKit room managed by the sidecar."""

    room_name: str
    room_id: str
    participant_count: int
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "room_name": self.room_name,
            "room_id": self.room_id,
            "participant_count": self.participant_count,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class LiveKitParticipant:
    """Represents a participant in a LiveKit room."""

    identity: str
    name: str
    joined_at: datetime
    tracks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "identity": self.identity,
            "name": self.name,
            "joined_at": self.joined_at.isoformat(),
            "tracks": self.tracks,
        }


class LiveKitTransportError(Exception):
    """Raised when a LiveKit transport operation fails."""

    def __init__(self, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.detail = detail


class LiveKitTransport:
    """In-process LiveKit media transport for the voice sidecar.

    Manages rooms and participants in memory, generates JWT access tokens
    compatible with the LiveKit token format, and provides health checking.

    In a production deployment with a real LiveKit server, the create/delete/list
    operations would call the LiveKit Server API over HTTP. This sidecar
    implementation tracks state locally so the transport is self-contained
    and testable without a running LiveKit instance.
    """

    def __init__(self, config: LiveKitConfig) -> None:
        self._config = config
        self._rooms: dict[str, LiveKitRoom] = {}
        self._participants: dict[str, list[LiveKitParticipant]] = {}

    @property
    def config(self) -> LiveKitConfig:
        return self._config

    def generate_token(
        self,
        room_name: str,
        identity: str,
        *,
        ttl: int | None = None,
    ) -> str:
        """Generate a JWT access token for joining a LiveKit room.

        The token follows the LiveKit access token specification:
        - ``iss``: API key
        - ``sub``: participant identity
        - ``iat``: issued-at timestamp
        - ``exp``: expiration timestamp
        - ``nbf``: not-before timestamp
        - ``jti``: unique token ID
        - ``video``: grant payload containing room name and permissions

        Raises ``LiveKitTransportError`` if the transport is not configured.
        """
        if not self._config.api_key or not self._config.api_secret:
            raise LiveKitTransportError(
                "Cannot generate token: api_key and api_secret are required",
                detail="LiveKit transport is not configured",
            )

        if not room_name:
            raise ValueError("room_name must not be empty")
        if not identity:
            raise ValueError("identity must not be empty")

        now = int(time.time())
        effective_ttl = ttl if ttl is not None else self._config.token_ttl_seconds

        claims: dict[str, Any] = {
            "iss": self._config.api_key,
            "sub": identity,
            "iat": now,
            "nbf": now,
            "exp": now + effective_ttl,
            "jti": uuid4().hex,
            "video": {
                "room": room_name,
                "roomJoin": True,
                "canPublish": True,
                "canSubscribe": True,
                "canPublishData": True,
            },
        }

        token: str = jwt.encode(
            claims,
            self._config.api_secret,
            algorithm="HS256",
            headers={"typ": "JWT"},
        )

        logger.debug(
            "livekit.token_generated",
            extra={
                "room_name": room_name,
                "identity": identity,
                "ttl": effective_ttl,
            },
        )
        return token

    def create_room(
        self,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> LiveKitRoom:
        """Create a new room in the sidecar's in-memory registry.

        The room name is prefixed with the configured ``room_prefix`` if it
        does not already start with it. Raises ``LiveKitTransportError`` if a
        room with the same name already exists.
        """
        if not name:
            raise ValueError("room name must not be empty")

        prefixed_name = name
        if self._config.room_prefix and not name.startswith(self._config.room_prefix):
            prefixed_name = f"{self._config.room_prefix}{name}"

        if prefixed_name in self._rooms:
            raise LiveKitTransportError(
                f"Room '{prefixed_name}' already exists",
                detail=f"room_name={prefixed_name}",
            )

        room = LiveKitRoom(
            room_name=prefixed_name,
            room_id=uuid4().hex,
            participant_count=0,
            created_at=datetime.now(UTC),
            metadata=metadata or {},
        )
        self._rooms[prefixed_name] = room
        self._participants[prefixed_name] = []

        logger.info(
            "livekit.room_created",
            extra={
                "room_name": prefixed_name,
                "room_id": room.room_id,
            },
        )
        return room

    def list_rooms(self) -> list[LiveKitRoom]:
        """Return all active rooms, sorted by creation time (newest first)."""
        return sorted(
            self._rooms.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )

    def get_room(self, room_name: str) -> LiveKitRoom | None:
        """Return a room by name, or None if not found."""
        return self._rooms.get(room_name)

    def delete_room(self, room_name: str) -> bool:
        """Delete a room and its participants.

        Returns True if the room was found and deleted, False otherwise.
        """
        if room_name not in self._rooms:
            return False

        del self._rooms[room_name]
        self._participants.pop(room_name, None)

        logger.info(
            "livekit.room_deleted",
            extra={"room_name": room_name},
        )
        return True

    def add_participant(
        self,
        room_name: str,
        identity: str,
        name: str = "",
        tracks: list[str] | None = None,
    ) -> LiveKitParticipant:
        """Add a participant to a room.

        Raises ``LiveKitTransportError`` if the room does not exist or the
        room is at capacity.
        """
        room = self._rooms.get(room_name)
        if room is None:
            raise LiveKitTransportError(
                f"Room '{room_name}' does not exist",
                detail=f"room_name={room_name}",
            )

        if room.participant_count >= self._config.max_participants:
            raise LiveKitTransportError(
                f"Room '{room_name}' is at capacity ({self._config.max_participants})",
                detail=f"max_participants={self._config.max_participants}",
            )

        participant = LiveKitParticipant(
            identity=identity,
            name=name or identity,
            joined_at=datetime.now(UTC),
            tracks=tracks or [],
        )
        self._participants.setdefault(room_name, []).append(participant)
        room.participant_count = len(self._participants[room_name])

        logger.debug(
            "livekit.participant_added",
            extra={
                "room_name": room_name,
                "identity": identity,
            },
        )
        return participant

    def get_participants(self, room_name: str) -> list[LiveKitParticipant]:
        """Return all participants in a room.

        Raises ``LiveKitTransportError`` if the room does not exist.
        """
        if room_name not in self._rooms:
            raise LiveKitTransportError(
                f"Room '{room_name}' does not exist",
                detail=f"room_name={room_name}",
            )
        return list(self._participants.get(room_name, []))

    def remove_participant(self, room_name: str, identity: str) -> bool:
        """Remove a participant from a room by identity.

        Returns True if the participant was found and removed, False otherwise.
        """
        if room_name not in self._rooms:
            return False

        participants = self._participants.get(room_name, [])
        original_count = len(participants)
        self._participants[room_name] = [p for p in participants if p.identity != identity]
        removed = len(self._participants[room_name]) < original_count

        if removed:
            room = self._rooms[room_name]
            room.participant_count = len(self._participants[room_name])

        return removed

    def health_check(self) -> bool:
        """Verify that the transport is properly configured.

        Returns True if api_key, api_secret, and ws_url are all set.
        """
        healthy = self._config.is_configured
        logger.debug(
            "livekit.health_check",
            extra={"healthy": healthy, "ws_url": self._config.ws_url},
        )
        return healthy

    def snapshot(self) -> dict[str, Any]:
        """Return a deterministic transport status snapshot."""
        return {
            "configured": self._config.is_configured,
            "ws_url": self._config.ws_url,
            "room_prefix": self._config.room_prefix,
            "default_codec": self._config.default_codec,
            "max_participants": self._config.max_participants,
            "active_rooms": len(self._rooms),
            "total_participants": sum(room.participant_count for room in self._rooms.values()),
        }
