"""Tests for the LiveKit media transport and voice sidecar integration (S32)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import httpx
import jwt
import pytest

from agent33.voice.livekit_transport import (
    LiveKitConfig,
    LiveKitParticipant,
    LiveKitRoom,
    LiveKitTransport,
    LiveKitTransportError,
)

if TYPE_CHECKING:
    from pathlib import Path


# -----------------------------------------------------------------------
# LiveKitConfig tests
# -----------------------------------------------------------------------


class TestLiveKitConfig:
    """Validate configuration defaults and boundary conditions."""

    def test_defaults(self) -> None:
        config = LiveKitConfig()
        assert config.api_key == ""
        assert config.api_secret == ""
        assert config.ws_url == ""
        assert config.room_prefix == "agent33-"
        assert config.default_codec == "opus"
        assert config.max_participants == 10
        assert config.token_ttl_seconds == 3600

    def test_custom_values(self) -> None:
        config = LiveKitConfig(
            api_key="APIfoo",
            api_secret="secret123",
            ws_url="wss://lk.example.com",
            room_prefix="myapp-",
            default_codec="vp8",
            max_participants=50,
            token_ttl_seconds=7200,
        )
        assert config.api_key == "APIfoo"
        assert config.api_secret == "secret123"
        assert config.ws_url == "wss://lk.example.com"
        assert config.room_prefix == "myapp-"
        assert config.default_codec == "vp8"
        assert config.max_participants == 50
        assert config.token_ttl_seconds == 7200

    def test_max_participants_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_participants must be at least 1"):
            LiveKitConfig(max_participants=0)

    def test_max_participants_negative(self) -> None:
        with pytest.raises(ValueError, match="max_participants must be at least 1"):
            LiveKitConfig(max_participants=-5)

    def test_token_ttl_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="token_ttl_seconds must be at least 1"):
            LiveKitConfig(token_ttl_seconds=0)

    def test_invalid_codec(self) -> None:
        with pytest.raises(ValueError, match="default_codec must be one of"):
            LiveKitConfig(default_codec="mp3")

    def test_valid_codecs(self) -> None:
        for codec in ("opus", "vp8", "vp9", "h264", "av1"):
            config = LiveKitConfig(default_codec=codec)
            assert config.default_codec == codec

    def test_is_configured_true(self) -> None:
        config = LiveKitConfig(api_key="key", api_secret="secret", ws_url="wss://x.example.com")
        assert config.is_configured is True

    def test_is_configured_false_missing_key(self) -> None:
        config = LiveKitConfig(api_secret="secret", ws_url="wss://x.example.com")
        assert config.is_configured is False

    def test_is_configured_false_missing_secret(self) -> None:
        config = LiveKitConfig(api_key="key", ws_url="wss://x.example.com")
        assert config.is_configured is False

    def test_is_configured_false_missing_url(self) -> None:
        config = LiveKitConfig(api_key="key", api_secret="secret")
        assert config.is_configured is False

    def test_is_configured_false_all_empty(self) -> None:
        config = LiveKitConfig()
        assert config.is_configured is False


# -----------------------------------------------------------------------
# LiveKitRoom and LiveKitParticipant model tests
# -----------------------------------------------------------------------


class TestLiveKitModels:
    """Test data model serialization."""

    def test_room_to_dict(self) -> None:
        from datetime import UTC, datetime

        room = LiveKitRoom(
            room_name="agent33-test",
            room_id="abc123",
            participant_count=2,
            created_at=datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC),
            metadata={"purpose": "testing"},
        )
        d = room.to_dict()
        assert d["room_name"] == "agent33-test"
        assert d["room_id"] == "abc123"
        assert d["participant_count"] == 2
        assert d["created_at"] == "2026-03-15T12:00:00+00:00"
        assert d["metadata"] == {"purpose": "testing"}

    def test_participant_to_dict(self) -> None:
        from datetime import UTC, datetime

        p = LiveKitParticipant(
            identity="user-1",
            name="Alice",
            joined_at=datetime(2026, 3, 15, 12, 30, 0, tzinfo=UTC),
            tracks=["audio-track-1", "video-track-1"],
        )
        d = p.to_dict()
        assert d["identity"] == "user-1"
        assert d["name"] == "Alice"
        assert d["joined_at"] == "2026-03-15T12:30:00+00:00"
        assert d["tracks"] == ["audio-track-1", "video-track-1"]

    def test_participant_default_tracks(self) -> None:
        from datetime import UTC, datetime

        p = LiveKitParticipant(
            identity="user-2",
            name="Bob",
            joined_at=datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC),
        )
        assert p.tracks == []

    def test_room_default_metadata(self) -> None:
        from datetime import UTC, datetime

        room = LiveKitRoom(
            room_name="r1",
            room_id="id1",
            participant_count=0,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        assert room.metadata == {}


# -----------------------------------------------------------------------
# Token generation tests
# -----------------------------------------------------------------------


def _make_transport(
    api_key: str = "APItestkey",
    api_secret: str = "testsecret",
    ws_url: str = "wss://lk.test.example.com",
    **kwargs: Any,
) -> LiveKitTransport:
    return LiveKitTransport(
        LiveKitConfig(
            api_key=api_key,
            api_secret=api_secret,
            ws_url=ws_url,
            **kwargs,
        )
    )


class TestTokenGeneration:
    """Test JWT access token generation."""

    def test_generate_token_structure(self) -> None:
        transport = _make_transport()
        token = transport.generate_token("my-room", "user-1")

        # Decode and verify JWT structure
        decoded = jwt.decode(
            token,
            "testsecret",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )

        assert decoded["iss"] == "APItestkey"
        assert decoded["sub"] == "user-1"
        assert "iat" in decoded
        assert "nbf" in decoded
        assert "exp" in decoded
        assert "jti" in decoded
        assert decoded["video"]["room"] == "my-room"
        assert decoded["video"]["roomJoin"] is True
        assert decoded["video"]["canPublish"] is True
        assert decoded["video"]["canSubscribe"] is True
        assert decoded["video"]["canPublishData"] is True

    def test_generate_token_default_ttl(self) -> None:
        transport = _make_transport(token_ttl_seconds=3600)
        token = transport.generate_token("room", "user")

        decoded = jwt.decode(
            token, "testsecret", algorithms=["HS256"], options={"verify_exp": False}
        )
        assert decoded["exp"] - decoded["iat"] == 3600

    def test_generate_token_custom_ttl(self) -> None:
        transport = _make_transport()
        token = transport.generate_token("room", "user", ttl=600)

        decoded = jwt.decode(
            token, "testsecret", algorithms=["HS256"], options={"verify_exp": False}
        )
        assert decoded["exp"] - decoded["iat"] == 600

    def test_generate_token_unique_jti(self) -> None:
        transport = _make_transport()
        token1 = transport.generate_token("room", "user")
        token2 = transport.generate_token("room", "user")

        d1 = jwt.decode(token1, "testsecret", algorithms=["HS256"], options={"verify_exp": False})
        d2 = jwt.decode(token2, "testsecret", algorithms=["HS256"], options={"verify_exp": False})
        assert d1["jti"] != d2["jti"]

    def test_generate_token_verifiable_signature(self) -> None:
        transport = _make_transport()
        token = transport.generate_token("room", "user")

        # Should succeed with correct secret
        decoded = jwt.decode(token, "testsecret", algorithms=["HS256"])
        assert decoded["sub"] == "user"

        # Should fail with wrong secret
        with pytest.raises(jwt.InvalidSignatureError):
            jwt.decode(token, "wrong-secret", algorithms=["HS256"])

    def test_generate_token_no_api_key_raises(self) -> None:
        transport = _make_transport(api_key="")
        with pytest.raises(LiveKitTransportError, match="api_key and api_secret are required"):
            transport.generate_token("room", "user")

    def test_generate_token_no_api_secret_raises(self) -> None:
        transport = _make_transport(api_secret="")
        with pytest.raises(LiveKitTransportError, match="api_key and api_secret are required"):
            transport.generate_token("room", "user")

    def test_generate_token_empty_room_raises(self) -> None:
        transport = _make_transport()
        with pytest.raises(ValueError, match="room_name must not be empty"):
            transport.generate_token("", "user")

    def test_generate_token_empty_identity_raises(self) -> None:
        transport = _make_transport()
        with pytest.raises(ValueError, match="identity must not be empty"):
            transport.generate_token("room", "")


# -----------------------------------------------------------------------
# Room CRUD tests
# -----------------------------------------------------------------------


class TestRoomCRUD:
    """Test room creation, listing, and deletion."""

    def test_create_room_with_prefix(self) -> None:
        transport = _make_transport(room_prefix="agent33-")
        room = transport.create_room("test-room")

        assert room.room_name == "agent33-test-room"
        assert room.participant_count == 0
        assert room.room_id  # non-empty UUID hex
        assert room.created_at is not None

    def test_create_room_already_prefixed(self) -> None:
        transport = _make_transport(room_prefix="agent33-")
        room = transport.create_room("agent33-already-prefixed")

        assert room.room_name == "agent33-already-prefixed"

    def test_create_room_no_prefix(self) -> None:
        transport = _make_transport(room_prefix="")
        room = transport.create_room("plain-room")

        assert room.room_name == "plain-room"

    def test_create_room_with_metadata(self) -> None:
        transport = _make_transport()
        meta = {"agent_id": "code-worker", "session": "abc"}
        room = transport.create_room("test", metadata=meta)

        assert room.metadata == meta

    def test_create_room_default_metadata(self) -> None:
        transport = _make_transport()
        room = transport.create_room("test")

        assert room.metadata == {}

    def test_create_room_duplicate_raises(self) -> None:
        transport = _make_transport()
        transport.create_room("dupe")

        with pytest.raises(LiveKitTransportError, match="already exists"):
            transport.create_room("dupe")

    def test_create_room_empty_name_raises(self) -> None:
        transport = _make_transport()
        with pytest.raises(ValueError, match="room name must not be empty"):
            transport.create_room("")

    def test_list_rooms_empty(self) -> None:
        transport = _make_transport()
        assert transport.list_rooms() == []

    def test_list_rooms_ordered_by_creation(self) -> None:
        from datetime import UTC, datetime
        from unittest.mock import patch

        transport = _make_transport()

        # Use deterministic timestamps to guarantee ordering
        t1 = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
        t2 = datetime(2026, 3, 15, 10, 0, 1, tzinfo=UTC)
        t3 = datetime(2026, 3, 15, 10, 0, 2, tzinfo=UTC)

        with patch("agent33.voice.livekit_transport.datetime") as mock_dt:
            mock_dt.now.return_value = t1
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            transport.create_room("first")

            mock_dt.now.return_value = t2
            transport.create_room("second")

            mock_dt.now.return_value = t3
            transport.create_room("third")

        rooms = transport.list_rooms()
        assert len(rooms) == 3
        # Newest first
        assert rooms[0].room_name.endswith("third")
        assert rooms[1].room_name.endswith("second")
        assert rooms[2].room_name.endswith("first")

    def test_get_room_found(self) -> None:
        transport = _make_transport()
        created = transport.create_room("findme")

        found = transport.get_room(created.room_name)
        assert found is not None
        assert found.room_id == created.room_id

    def test_get_room_not_found(self) -> None:
        transport = _make_transport()
        assert transport.get_room("nonexistent") is None

    def test_delete_room_success(self) -> None:
        transport = _make_transport()
        room = transport.create_room("deleteme")

        result = transport.delete_room(room.room_name)
        assert result is True
        assert transport.list_rooms() == []

    def test_delete_room_not_found(self) -> None:
        transport = _make_transport()
        result = transport.delete_room("nonexistent")
        assert result is False

    def test_delete_room_clears_participants(self) -> None:
        transport = _make_transport()
        room = transport.create_room("with-people")
        transport.add_participant(room.room_name, "user-1")

        transport.delete_room(room.room_name)

        # Room and participants are gone
        assert transport.get_room(room.room_name) is None


# -----------------------------------------------------------------------
# Participant management tests
# -----------------------------------------------------------------------


class TestParticipants:
    """Test participant add, list, remove, and capacity enforcement."""

    def test_add_participant(self) -> None:
        transport = _make_transport()
        room = transport.create_room("room1")
        participant = transport.add_participant(
            room.room_name, "user-1", name="Alice", tracks=["audio"]
        )

        assert participant.identity == "user-1"
        assert participant.name == "Alice"
        assert participant.tracks == ["audio"]
        assert participant.joined_at is not None

        # Room count updated
        updated_room = transport.get_room(room.room_name)
        assert updated_room is not None
        assert updated_room.participant_count == 1

    def test_add_participant_default_name(self) -> None:
        transport = _make_transport()
        room = transport.create_room("room1")
        participant = transport.add_participant(room.room_name, "user-2")

        assert participant.name == "user-2"  # defaults to identity

    def test_add_participant_nonexistent_room_raises(self) -> None:
        transport = _make_transport()
        with pytest.raises(LiveKitTransportError, match="does not exist"):
            transport.add_participant("no-such-room", "user")

    def test_add_participant_at_capacity_raises(self) -> None:
        transport = _make_transport(max_participants=2)
        room = transport.create_room("small-room")
        transport.add_participant(room.room_name, "user-1")
        transport.add_participant(room.room_name, "user-2")

        with pytest.raises(LiveKitTransportError, match="at capacity"):
            transport.add_participant(room.room_name, "user-3")

    def test_get_participants(self) -> None:
        transport = _make_transport()
        room = transport.create_room("room1")
        transport.add_participant(room.room_name, "user-1", name="Alice")
        transport.add_participant(room.room_name, "user-2", name="Bob")

        participants = transport.get_participants(room.room_name)
        assert len(participants) == 2
        identities = {p.identity for p in participants}
        assert identities == {"user-1", "user-2"}

    def test_get_participants_empty_room(self) -> None:
        transport = _make_transport()
        room = transport.create_room("empty-room")
        participants = transport.get_participants(room.room_name)
        assert participants == []

    def test_get_participants_nonexistent_room_raises(self) -> None:
        transport = _make_transport()
        with pytest.raises(LiveKitTransportError, match="does not exist"):
            transport.get_participants("no-such-room")

    def test_remove_participant_success(self) -> None:
        transport = _make_transport()
        room = transport.create_room("room1")
        transport.add_participant(room.room_name, "user-1")
        transport.add_participant(room.room_name, "user-2")

        result = transport.remove_participant(room.room_name, "user-1")
        assert result is True

        participants = transport.get_participants(room.room_name)
        assert len(participants) == 1
        assert participants[0].identity == "user-2"

        updated_room = transport.get_room(room.room_name)
        assert updated_room is not None
        assert updated_room.participant_count == 1

    def test_remove_participant_not_found(self) -> None:
        transport = _make_transport()
        room = transport.create_room("room1")
        result = transport.remove_participant(room.room_name, "no-such-user")
        assert result is False

    def test_remove_participant_nonexistent_room(self) -> None:
        transport = _make_transport()
        result = transport.remove_participant("no-room", "user-1")
        assert result is False


# -----------------------------------------------------------------------
# Health check and snapshot tests
# -----------------------------------------------------------------------


class TestHealthAndSnapshot:
    """Test health check and snapshot methods."""

    def test_health_check_configured(self) -> None:
        transport = _make_transport()
        assert transport.health_check() is True

    def test_health_check_unconfigured(self) -> None:
        transport = LiveKitTransport(LiveKitConfig())
        assert transport.health_check() is False

    def test_health_check_partial_config(self) -> None:
        transport = LiveKitTransport(LiveKitConfig(api_key="key"))
        assert transport.health_check() is False

    def test_snapshot_empty(self) -> None:
        transport = _make_transport()
        snap = transport.snapshot()

        assert snap["configured"] is True
        assert snap["ws_url"] == "wss://lk.test.example.com"
        assert snap["room_prefix"] == "agent33-"
        assert snap["default_codec"] == "opus"
        assert snap["max_participants"] == 10
        assert snap["active_rooms"] == 0
        assert snap["total_participants"] == 0

    def test_snapshot_with_rooms_and_participants(self) -> None:
        transport = _make_transport()
        room = transport.create_room("r1")
        transport.add_participant(room.room_name, "u1")
        transport.add_participant(room.room_name, "u2")
        transport.create_room("r2")

        snap = transport.snapshot()
        assert snap["active_rooms"] == 2
        assert snap["total_participants"] == 2

    def test_snapshot_unconfigured(self) -> None:
        transport = LiveKitTransport(LiveKitConfig())
        snap = transport.snapshot()
        assert snap["configured"] is False


# -----------------------------------------------------------------------
# Sidecar API endpoint tests
# -----------------------------------------------------------------------


def _make_sidecar_app(
    tmp_path: Path,
    *,
    api_key: str = "APItestkey",
    api_secret: str = "testsecret",
    ws_url: str = "wss://lk.test.example.com",
) -> Any:
    """Create a voice sidecar app with LiveKit transport configured."""
    from agent33.voice.app import create_voice_sidecar_app
    from agent33.voice.service import VoiceSidecarService

    voices_path = tmp_path / "voices.json"
    voices_path.write_text(
        json.dumps({"voices": [{"id": "default", "name": "Default"}]}),
        encoding="utf-8",
    )
    service = VoiceSidecarService(
        voices_path=voices_path,
        artifacts_dir=tmp_path / "artifacts",
        playback_backend="noop",
    )
    lk_config = LiveKitConfig(
        api_key=api_key,
        api_secret=api_secret,
        ws_url=ws_url,
    )
    return create_voice_sidecar_app(service, livekit_config=lk_config)


class TestSidecarLiveKitEndpoints:
    """Test LiveKit endpoints wired into the voice sidecar app."""

    async def test_create_room_endpoint(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/livekit/rooms",
                json={"name": "test-room", "metadata": {"agent": "code-worker"}},
            )

        assert response.status_code == 201
        body = response.json()
        assert body["room_name"] == "agent33-test-room"
        assert body["participant_count"] == 0
        assert body["metadata"] == {"agent": "code-worker"}
        assert body["room_id"]  # non-empty
        assert body["created_at"]  # non-empty ISO string

    async def test_create_room_duplicate_returns_409(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await client.post("/v1/voice/livekit/rooms", json={"name": "dup"})
            response = await client.post("/v1/voice/livekit/rooms", json={"name": "dup"})

        assert response.status_code == 409

    async def test_create_room_empty_name_returns_400(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/v1/voice/livekit/rooms", json={"name": ""})

        assert response.status_code == 400

    async def test_list_rooms_endpoint(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await client.post("/v1/voice/livekit/rooms", json={"name": "room-a"})
            await client.post("/v1/voice/livekit/rooms", json={"name": "room-b"})
            response = await client.get("/v1/voice/livekit/rooms")

        assert response.status_code == 200
        rooms = response.json()
        assert len(rooms) == 2
        names = {r["room_name"] for r in rooms}
        assert "agent33-room-a" in names
        assert "agent33-room-b" in names

    async def test_list_rooms_empty(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/voice/livekit/rooms")

        assert response.status_code == 200
        assert response.json() == []

    async def test_delete_room_endpoint(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            create = await client.post("/v1/voice/livekit/rooms", json={"name": "deleteme"})
            room_name = create.json()["room_name"]

            response = await client.delete(f"/v1/voice/livekit/rooms/{room_name}")

        assert response.status_code == 200
        assert response.json()["status"] == "deleted"
        assert response.json()["room_name"] == room_name

    async def test_delete_room_not_found_returns_404(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.delete("/v1/voice/livekit/rooms/nonexistent")

        assert response.status_code == 404

    async def test_generate_token_endpoint(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/livekit/token",
                json={"room_name": "my-room", "identity": "agent-1", "ttl": 600},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["room_name"] == "my-room"
        assert body["identity"] == "agent-1"
        assert body["token"]  # non-empty

        # Verify the token is a valid JWT with correct claims
        decoded = jwt.decode(
            body["token"],
            "testsecret",
            algorithms=["HS256"],
            options={"verify_exp": False},
        )
        assert decoded["sub"] == "agent-1"
        assert decoded["video"]["room"] == "my-room"
        assert decoded["exp"] - decoded["iat"] == 600

    async def test_generate_token_empty_room_returns_400(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/livekit/token",
                json={"room_name": "", "identity": "user"},
            )

        assert response.status_code == 400

    async def test_generate_token_empty_identity_returns_400(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/livekit/token",
                json={"room_name": "room", "identity": ""},
            )

        assert response.status_code == 400

    async def test_list_participants_endpoint(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        # Pre-populate a room with participants via the transport directly
        lk_transport: LiveKitTransport = app.state.livekit_transport
        room = lk_transport.create_room("people-room")
        lk_transport.add_participant(room.room_name, "user-1", name="Alice")
        lk_transport.add_participant(room.room_name, "user-2", name="Bob")

        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/v1/voice/livekit/rooms/{room.room_name}/participants")

        assert response.status_code == 200
        participants = response.json()
        assert len(participants) == 2
        names = {p["name"] for p in participants}
        assert names == {"Alice", "Bob"}
        # Verify serialization structure
        for p in participants:
            assert "identity" in p
            assert "joined_at" in p
            assert "tracks" in p

    async def test_list_participants_nonexistent_room_returns_404(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/voice/livekit/rooms/no-such-room/participants")

        assert response.status_code == 404

    async def test_livekit_health_endpoint_configured(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/voice/health/livekit")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["ws_url"] == "wss://lk.test.example.com"
        assert body["default_codec"] == "opus"
        assert body["active_rooms"] == 0
        assert body["total_participants"] == 0

    async def test_livekit_health_endpoint_unconfigured(self, tmp_path: Path) -> None:
        app = _make_sidecar_app(tmp_path, api_key="", api_secret="", ws_url="")
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/voice/health/livekit")

        assert response.status_code == 200
        assert response.json()["status"] == "unconfigured"

    async def test_livekit_endpoints_return_503_when_unconfigured(self, tmp_path: Path) -> None:
        """All CRUD endpoints should return 503 when LiveKit is not configured."""
        app = _make_sidecar_app(tmp_path, api_key="", api_secret="", ws_url="")
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Create room
            r = await client.post("/v1/voice/livekit/rooms", json={"name": "room"})
            assert r.status_code == 503

            # List rooms
            r = await client.get("/v1/voice/livekit/rooms")
            assert r.status_code == 503

            # Delete room
            r = await client.delete("/v1/voice/livekit/rooms/room")
            assert r.status_code == 503

            # Generate token
            r = await client.post(
                "/v1/voice/livekit/token",
                json={"room_name": "room", "identity": "user"},
            )
            assert r.status_code == 503

            # List participants
            r = await client.get("/v1/voice/livekit/rooms/room/participants")
            assert r.status_code == 503

    async def test_existing_sidecar_endpoints_still_work(self, tmp_path: Path) -> None:
        """Verify that adding LiveKit endpoints does not break existing ones."""
        app = _make_sidecar_app(tmp_path)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Health endpoint
            r = await client.get("/health")
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"

            # Session lifecycle
            created = await client.post(
                "/v1/voice/sessions",
                json={"room_name": "test", "requested_by": "pytest"},
            )
            assert created.status_code == 201
            session_id = created.json()["session_id"]

            sessions = await client.get("/v1/voice/sessions")
            assert sessions.status_code == 200
            assert len(sessions.json()) == 1

            stopped = await client.post(f"/v1/voice/sessions/{session_id}/stop")
            assert stopped.status_code == 200
            assert stopped.json()["state"] == "stopped"


# -----------------------------------------------------------------------
# Config integration tests
# -----------------------------------------------------------------------


class TestConfigIntegration:
    """Verify the LiveKit settings exist on the Settings model."""

    def test_livekit_settings_defaults(self) -> None:
        from agent33.config import Settings

        s = Settings(
            environment="test",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.voice_livekit_enabled is False
        assert s.voice_livekit_api_key.get_secret_value() == ""
        assert s.voice_livekit_api_secret.get_secret_value() == ""
        assert s.voice_livekit_ws_url == ""

    def test_livekit_settings_custom(self) -> None:
        from pydantic import SecretStr

        from agent33.config import Settings

        s = Settings(
            environment="test",
            voice_livekit_enabled=True,
            voice_livekit_api_key=SecretStr("APIkey123"),
            voice_livekit_api_secret=SecretStr("secret456"),
            voice_livekit_ws_url="wss://my-livekit.example.com",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.voice_livekit_enabled is True
        assert s.voice_livekit_api_key.get_secret_value() == "APIkey123"
        assert s.voice_livekit_api_secret.get_secret_value() == "secret456"
        assert s.voice_livekit_ws_url == "wss://my-livekit.example.com"


# -----------------------------------------------------------------------
# Voice daemon integration test
# -----------------------------------------------------------------------


class TestVoiceDaemonLiveKitMessage:
    """Verify the voice daemon's deferred-livekit message is updated."""

    def test_deferred_message_mentions_sidecar(self) -> None:
        from agent33.multimodal.voice_daemon import VOICE_LIVEKIT_DEFERRED_MESSAGE

        assert "voice sidecar" in VOICE_LIVEKIT_DEFERRED_MESSAGE.lower()
        assert "voice_livekit_enabled" in VOICE_LIVEKIT_DEFERRED_MESSAGE

    def test_sidecar_available_message_exists(self) -> None:
        from agent33.multimodal.voice_daemon import VOICE_LIVEKIT_SIDECAR_AVAILABLE_MESSAGE

        assert "sidecar" in VOICE_LIVEKIT_SIDECAR_AVAILABLE_MESSAGE.lower()
        assert "livekit" in VOICE_LIVEKIT_SIDECAR_AVAILABLE_MESSAGE.lower()

    async def test_livekit_transport_raises_with_updated_message(self) -> None:
        from agent33.multimodal.voice_daemon import LiveVoiceDaemon

        daemon = LiveVoiceDaemon(
            room_name="test",
            url="wss://example.com",
            api_key="key",
            api_secret="secret",
            transport="livekit",
        )
        with pytest.raises(RuntimeError, match="voice sidecar"):
            await daemon.start()
