"""Tests for the ElevenLabs audio transport and voice sidecar integration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent33.voice.elevenlabs import (
    ElevenLabsArtifactStore,
    ElevenLabsConfig,
    ElevenLabsTransport,
    ElevenLabsTransportError,
)

if TYPE_CHECKING:
    from pathlib import Path


# -----------------------------------------------------------------------
# ElevenLabsConfig tests
# -----------------------------------------------------------------------


class TestElevenLabsConfig:
    """Validate configuration defaults and boundary conditions."""

    def test_defaults(self) -> None:
        config = ElevenLabsConfig()
        assert config.api_key == ""
        assert config.model_id == "eleven_multilingual_v2"
        assert config.voice_id == ""
        assert config.stability == 0.5
        assert config.similarity_boost == 0.75
        assert config.output_format == "mp3_44100_128"
        assert config.optimize_streaming_latency == 3

    def test_custom_values(self) -> None:
        config = ElevenLabsConfig(
            api_key="test-key",
            model_id="eleven_turbo_v2",
            voice_id="abc123",
            stability=0.8,
            similarity_boost=0.6,
            output_format="pcm_24000",
            optimize_streaming_latency=1,
        )
        assert config.api_key == "test-key"
        assert config.model_id == "eleven_turbo_v2"
        assert config.voice_id == "abc123"
        assert config.stability == 0.8
        assert config.similarity_boost == 0.6
        assert config.output_format == "pcm_24000"
        assert config.optimize_streaming_latency == 1

    def test_stability_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="stability must be between"):
            ElevenLabsConfig(stability=1.5)

    def test_stability_negative(self) -> None:
        with pytest.raises(ValueError, match="stability must be between"):
            ElevenLabsConfig(stability=-0.1)

    def test_similarity_boost_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="similarity_boost must be between"):
            ElevenLabsConfig(similarity_boost=2.0)

    def test_optimize_streaming_latency_too_high(self) -> None:
        with pytest.raises(ValueError, match="optimize_streaming_latency must be between"):
            ElevenLabsConfig(optimize_streaming_latency=5)

    def test_optimize_streaming_latency_negative(self) -> None:
        with pytest.raises(ValueError, match="optimize_streaming_latency must be between"):
            ElevenLabsConfig(optimize_streaming_latency=-1)

    def test_resolved_websocket_url(self) -> None:
        config = ElevenLabsConfig(voice_id="my-voice-id")
        url = config.resolved_websocket_url()
        assert "my-voice-id" in url
        assert url.startswith("wss://")

    def test_boundary_stability_zero(self) -> None:
        config = ElevenLabsConfig(stability=0.0)
        assert config.stability == 0.0

    def test_boundary_stability_one(self) -> None:
        config = ElevenLabsConfig(stability=1.0)
        assert config.stability == 1.0

    def test_boundary_latency_zero(self) -> None:
        config = ElevenLabsConfig(optimize_streaming_latency=0)
        assert config.optimize_streaming_latency == 0

    def test_boundary_latency_four(self) -> None:
        config = ElevenLabsConfig(optimize_streaming_latency=4)
        assert config.optimize_streaming_latency == 4


# -----------------------------------------------------------------------
# ElevenLabsTransport tests — synthesize
# -----------------------------------------------------------------------


def _make_transport(api_key: str = "test-key", voice_id: str = "v1") -> ElevenLabsTransport:
    return ElevenLabsTransport(ElevenLabsConfig(api_key=api_key, voice_id=voice_id))


class TestSynthesize:
    """Test the HTTP-based synthesize method with mocked httpx."""

    async def test_synthesize_success(self) -> None:
        transport = _make_transport()
        fake_audio = b"\xff\xfb\x90\x04" * 100  # fake MP3 bytes

        mock_response = httpx.Response(
            status_code=200,
            content=fake_audio,
            request=httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/v1"),
        )

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await transport.synthesize("Hello world")

        assert result == fake_audio
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert "text-to-speech/v1" in call_args.args[0]
        body = call_args.kwargs["json"]
        assert body["text"] == "Hello world"
        assert body["model_id"] == "eleven_multilingual_v2"
        assert body["voice_settings"]["stability"] == 0.5

    async def test_synthesize_api_error(self) -> None:
        transport = _make_transport()

        error_body = {"detail": {"message": "Unauthorized"}}
        mock_response = httpx.Response(
            status_code=401,
            content=json.dumps(error_body).encode(),
            request=httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/v1"),
        )

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ElevenLabsTransportError) as exc_info:
                await transport.synthesize("test")

        assert exc_info.value.status_code == 401
        assert "401" in str(exc_info.value)

    async def test_synthesize_network_error(self) -> None:
        transport = _make_transport()

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(ElevenLabsTransportError, match="Network error"):
                await transport.synthesize("test")

    async def test_synthesize_empty_text_raises(self) -> None:
        transport = _make_transport()
        with pytest.raises(ValueError, match="text must not be empty"):
            await transport.synthesize("")

    async def test_synthesize_no_voice_id_raises(self) -> None:
        transport = ElevenLabsTransport(ElevenLabsConfig(api_key="key", voice_id=""))
        with pytest.raises(ValueError, match="voice_id must be set"):
            await transport.synthesize("test")

    async def test_synthesize_explicit_voice_id_override(self) -> None:
        transport = _make_transport(voice_id="default-voice")
        fake_audio = b"audio-bytes"

        mock_response = httpx.Response(
            status_code=200,
            content=fake_audio,
            request=httpx.Request(
                "POST", "https://api.elevenlabs.io/v1/text-to-speech/override-voice"
            ),
        )

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await transport.synthesize("test", voice_id="override-voice")

        assert result == fake_audio
        call_url = mock_client.post.call_args.args[0]
        assert "override-voice" in call_url


# -----------------------------------------------------------------------
# ElevenLabsTransport tests — synthesize_stream
# -----------------------------------------------------------------------


class TestSynthesizeStream:
    """Test the streaming TTS method."""

    async def test_synthesize_stream_success(self) -> None:
        transport = _make_transport()
        chunks = [b"chunk1", b"chunk2", b"chunk3"]

        mock_response = AsyncMock()
        mock_response.status_code = 200

        async def fake_aiter_bytes(chunk_size: int = 4096) -> Any:  # noqa: ARG001
            for c in chunks:
                yield c

        mock_response.aiter_bytes = fake_aiter_bytes

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            # Make stream() return an async context manager yielding mock_response
            stream_cm = AsyncMock()
            stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
            stream_cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = lambda *args, **kwargs: stream_cm  # noqa: ARG005

            mock_client_cls.return_value = mock_client

            collected: list[bytes] = []
            async for chunk in transport.synthesize_stream("Hello"):
                collected.append(chunk)

        assert collected == chunks

    async def test_synthesize_stream_empty_text_raises(self) -> None:
        transport = _make_transport()
        with pytest.raises(ValueError, match="text must not be empty"):
            async for _ in transport.synthesize_stream(""):
                pass  # pragma: no cover

    async def test_synthesize_stream_no_voice_id_raises(self) -> None:
        transport = ElevenLabsTransport(ElevenLabsConfig(api_key="key", voice_id=""))
        with pytest.raises(ValueError, match="voice_id must be set"):
            async for _ in transport.synthesize_stream("test"):
                pass  # pragma: no cover

    async def test_synthesize_stream_api_error(self) -> None:
        transport = _make_transport()

        mock_response = AsyncMock()
        mock_response.status_code = 500
        mock_response.aread = AsyncMock(return_value=b"Internal Server Error")

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)

            stream_cm = AsyncMock()
            stream_cm.__aenter__ = AsyncMock(return_value=mock_response)
            stream_cm.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = lambda *args, **kwargs: stream_cm  # noqa: ARG005

            mock_client_cls.return_value = mock_client

            with pytest.raises(ElevenLabsTransportError, match="500"):
                async for _ in transport.synthesize_stream("test"):
                    pass  # pragma: no cover


# -----------------------------------------------------------------------
# ElevenLabsTransport tests — list_voices and get_voice
# -----------------------------------------------------------------------


class TestListVoices:
    """Test voice listing and retrieval."""

    async def test_list_voices_success(self) -> None:
        transport = _make_transport()
        voices_data = {
            "voices": [
                {"voice_id": "v1", "name": "Rachel"},
                {"voice_id": "v2", "name": "Domi"},
            ]
        }

        mock_response = httpx.Response(
            status_code=200,
            content=json.dumps(voices_data).encode(),
            request=httpx.Request("GET", "https://api.elevenlabs.io/v1/voices"),
        )

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await transport.list_voices()

        assert len(result) == 2
        assert result[0]["voice_id"] == "v1"
        assert result[1]["name"] == "Domi"

    async def test_list_voices_api_error(self) -> None:
        transport = _make_transport()

        mock_response = httpx.Response(
            status_code=403,
            content=b"Forbidden",
            request=httpx.Request("GET", "https://api.elevenlabs.io/v1/voices"),
        )

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ElevenLabsTransportError) as exc_info:
                await transport.list_voices()

        assert exc_info.value.status_code == 403

    async def test_list_voices_network_error(self) -> None:
        transport = _make_transport()

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client_cls.return_value = mock_client

            with pytest.raises(ElevenLabsTransportError, match="Network error"):
                await transport.list_voices()


class TestGetVoice:
    """Test single voice retrieval."""

    async def test_get_voice_success(self) -> None:
        transport = _make_transport()
        voice_data = {"voice_id": "abc", "name": "Rachel", "category": "premade"}

        mock_response = httpx.Response(
            status_code=200,
            content=json.dumps(voice_data).encode(),
            request=httpx.Request("GET", "https://api.elevenlabs.io/v1/voices/abc"),
        )

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            result = await transport.get_voice("abc")

        assert result["voice_id"] == "abc"
        assert result["name"] == "Rachel"

    async def test_get_voice_not_found(self) -> None:
        transport = _make_transport()

        mock_response = httpx.Response(
            status_code=404,
            content=b"Not Found",
            request=httpx.Request("GET", "https://api.elevenlabs.io/v1/voices/missing"),
        )

        with patch("agent33.voice.elevenlabs.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            with pytest.raises(ElevenLabsTransportError) as exc_info:
                await transport.get_voice("missing")

        assert exc_info.value.status_code == 404


# -----------------------------------------------------------------------
# ElevenLabsTransport tests — health_check
# -----------------------------------------------------------------------


class TestHealthCheck:
    """Test API connectivity verification."""

    async def test_health_check_ok(self) -> None:
        transport = _make_transport()

        with patch.object(transport, "list_voices", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = [{"voice_id": "v1"}]
            result = await transport.health_check()

        assert result is True

    async def test_health_check_failed_api(self) -> None:
        transport = _make_transport()

        with patch.object(transport, "list_voices", new_callable=AsyncMock) as mock_list:
            mock_list.side_effect = ElevenLabsTransportError("API error", status_code=401)
            result = await transport.health_check()

        assert result is False

    async def test_health_check_no_api_key(self) -> None:
        transport = ElevenLabsTransport(ElevenLabsConfig(api_key=""))
        result = await transport.health_check()
        assert result is False

    async def test_health_check_network_failure(self) -> None:
        transport = _make_transport()

        with patch.object(transport, "list_voices", new_callable=AsyncMock) as mock_list:
            mock_list.side_effect = Exception("Unexpected error")
            result = await transport.health_check()

        assert result is False


# -----------------------------------------------------------------------
# ElevenLabsArtifactStore tests
# -----------------------------------------------------------------------


class TestArtifactStore:
    """Test audio artifact persistence and retrieval."""

    def test_save_and_list(self, tmp_path: Path) -> None:
        store = ElevenLabsArtifactStore(storage_dir=tmp_path / "artifacts")
        audio = b"\xff\xfb\x90\x04" * 50

        file_path = store.save_audio("session-1", "Hello world", audio, "mp3")

        assert file_path.endswith(".mp3")
        assert (tmp_path / "artifacts" / "session-1").exists()

        artifacts = store.list_artifacts("session-1")
        assert len(artifacts) == 1
        assert artifacts[0]["session_id"] == "session-1"
        assert artifacts[0]["text"] == "Hello world"
        assert artifacts[0]["audio_format"] == "mp3"
        assert artifacts[0]["size_bytes"] == len(audio)

    def test_save_multiple_artifacts(self, tmp_path: Path) -> None:
        store = ElevenLabsArtifactStore(storage_dir=tmp_path / "artifacts")
        store.save_audio("session-1", "First", b"audio1", "mp3")
        store.save_audio("session-1", "Second", b"audio2", "mp3")
        store.save_audio("session-2", "Other", b"audio3", "wav")

        s1_artifacts = store.list_artifacts("session-1")
        assert len(s1_artifacts) == 2
        assert {a["text"] for a in s1_artifacts} == {"First", "Second"}

        s2_artifacts = store.list_artifacts("session-2")
        assert len(s2_artifacts) == 1
        assert s2_artifacts[0]["audio_format"] == "wav"

    def test_get_artifact_found(self, tmp_path: Path) -> None:
        store = ElevenLabsArtifactStore(storage_dir=tmp_path / "artifacts")
        file_path = store.save_audio("session-1", "test", b"data", "mp3")

        # Extract artifact_id from the listing
        artifacts = store.list_artifacts("session-1")
        artifact_id = artifacts[0]["artifact_id"]

        result = store.get_artifact(artifact_id)
        assert result is not None
        assert str(result) == file_path

    def test_get_artifact_not_found(self, tmp_path: Path) -> None:
        store = ElevenLabsArtifactStore(storage_dir=tmp_path / "artifacts")
        result = store.get_artifact("nonexistent-id")
        assert result is None

    def test_list_artifacts_empty_session(self, tmp_path: Path) -> None:
        store = ElevenLabsArtifactStore(storage_dir=tmp_path / "artifacts")
        artifacts = store.list_artifacts("no-such-session")
        assert artifacts == []

    def test_manifest_persisted_to_disk(self, tmp_path: Path) -> None:
        store = ElevenLabsArtifactStore(storage_dir=tmp_path / "artifacts")
        store.save_audio("session-1", "Hello", b"audio", "mp3")

        manifest_path = tmp_path / "artifacts" / "session-1" / "manifest.json"
        assert manifest_path.exists()

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["text"] == "Hello"

    def test_manifest_loaded_from_disk(self, tmp_path: Path) -> None:
        """Verify a fresh store instance loads manifests from disk."""
        store1 = ElevenLabsArtifactStore(storage_dir=tmp_path / "artifacts")
        store1.save_audio("session-x", "Persisted", b"bytes", "mp3")

        # Create a new store instance pointing to the same directory
        store2 = ElevenLabsArtifactStore(storage_dir=tmp_path / "artifacts")
        artifacts = store2.list_artifacts("session-x")
        assert len(artifacts) == 1
        assert artifacts[0]["text"] == "Persisted"

    def test_storage_dir_created_on_init(self, tmp_path: Path) -> None:
        storage = tmp_path / "deep" / "nested" / "path"
        assert not storage.exists()
        ElevenLabsArtifactStore(storage_dir=storage)
        assert storage.exists()


# -----------------------------------------------------------------------
# Voice sidecar app integration tests
# -----------------------------------------------------------------------


class TestSidecarElevenLabsEndpoints:
    """Test the ElevenLabs endpoints wired into the voice sidecar app."""

    def _make_app(
        self,
        tmp_path: Path,
        *,
        api_key: str = "test-key",
        voice_id: str = "test-voice",
    ) -> Any:
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
        config = ElevenLabsConfig(api_key=api_key, voice_id=voice_id)
        store = ElevenLabsArtifactStore(storage_dir=tmp_path / "el-artifacts")
        return create_voice_sidecar_app(
            service,
            elevenlabs_config=config,
            elevenlabs_artifact_store=store,
        )

    async def test_synthesize_endpoint_success(self, tmp_path: Path) -> None:
        app = self._make_app(tmp_path)
        fake_audio = b"fake-audio-data"

        with patch.object(
            app.state.elevenlabs_transport,
            "synthesize",
            new_callable=AsyncMock,
            return_value=fake_audio,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/v1/voice/synthesize",
                    json={"text": "Hello from ElevenLabs"},
                )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["size_bytes"] == len(fake_audio)
        assert body["format"] == "mp3_44100_128"

    async def test_synthesize_endpoint_with_session_persists_artifact(
        self, tmp_path: Path
    ) -> None:
        app = self._make_app(tmp_path)
        fake_audio = b"persisted-audio"

        with patch.object(
            app.state.elevenlabs_transport,
            "synthesize",
            new_callable=AsyncMock,
            return_value=fake_audio,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/v1/voice/synthesize",
                    json={
                        "text": "Saved audio",
                        "session_id": "test-session",
                    },
                )

        assert response.status_code == 200
        body = response.json()
        assert body["artifact_path"] != ""

        # Verify the artifact was actually saved
        store: ElevenLabsArtifactStore = app.state.elevenlabs_artifact_store
        artifacts = store.list_artifacts("test-session")
        assert len(artifacts) == 1
        assert artifacts[0]["text"] == "Saved audio"

    async def test_synthesize_endpoint_no_api_key(self, tmp_path: Path) -> None:
        """When ElevenLabs is not configured, the stub TTS provider handles the request."""
        app = self._make_app(tmp_path, api_key="")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/synthesize",
                json={"text": "test"},
            )
        assert response.status_code == 200
        body = response.json()
        assert body["provider"] == "stub"
        assert body["size_bytes"] > 0

    async def test_synthesize_endpoint_api_error(self, tmp_path: Path) -> None:
        app = self._make_app(tmp_path)

        with patch.object(
            app.state.elevenlabs_transport,
            "synthesize",
            new_callable=AsyncMock,
            side_effect=ElevenLabsTransportError(
                "API error", status_code=429, detail="Rate limited"
            ),
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    "/v1/voice/synthesize",
                    json={"text": "test"},
                )

        assert response.status_code == 429
        assert "Rate limited" in response.json()["detail"]

    async def test_voices_endpoint_success(self, tmp_path: Path) -> None:
        """Voices endpoint returns both stub provider voices and ElevenLabs voices."""
        app = self._make_app(tmp_path)
        mock_voices = [{"voice_id": "v1", "name": "Rachel"}]

        with patch.object(
            app.state.elevenlabs_transport,
            "list_voices",
            new_callable=AsyncMock,
            return_value=mock_voices,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/v1/voice/voices")

        assert response.status_code == 200
        body = response.json()
        # Stub provider contributes 2 voices + ElevenLabs contributes 1
        assert len(body["voices"]) == 3
        voice_names = [v["name"] for v in body["voices"]]
        assert "Rachel" in voice_names

    async def test_voices_endpoint_no_api_key(self, tmp_path: Path) -> None:
        """Without ElevenLabs, the stub provider voices are still returned."""
        app = self._make_app(tmp_path, api_key="")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/voice/voices")
        assert response.status_code == 200
        body = response.json()
        assert len(body["voices"]) == 2  # stub voices only
        assert all(v.get("provider") == "stub" for v in body["voices"])

    async def test_health_elevenlabs_configured(self, tmp_path: Path) -> None:
        app = self._make_app(tmp_path)

        with patch.object(
            app.state.elevenlabs_transport,
            "health_check",
            new_callable=AsyncMock,
            return_value=True,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/v1/voice/health/elevenlabs")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["model_id"] == "eleven_multilingual_v2"

    async def test_health_elevenlabs_unhealthy(self, tmp_path: Path) -> None:
        app = self._make_app(tmp_path)

        with patch.object(
            app.state.elevenlabs_transport,
            "health_check",
            new_callable=AsyncMock,
            return_value=False,
        ):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.get("/v1/voice/health/elevenlabs")

        assert response.status_code == 200
        assert response.json()["status"] == "unavailable"

    async def test_health_elevenlabs_unconfigured(self, tmp_path: Path) -> None:
        app = self._make_app(tmp_path, api_key="")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/voice/health/elevenlabs")

        assert response.status_code == 200
        assert response.json()["status"] == "unconfigured"


# -----------------------------------------------------------------------
# Config integration test
# -----------------------------------------------------------------------


class TestConfigIntegration:
    """Verify the ElevenLabs settings exist on the Settings model."""

    def test_elevenlabs_settings_defaults(self) -> None:
        from agent33.config import Settings

        s = Settings(
            environment="test",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.voice_elevenlabs_enabled is False
        assert s.voice_elevenlabs_api_key.get_secret_value() == ""
        assert s.voice_elevenlabs_default_voice_id == ""
        assert s.voice_elevenlabs_model_id == "eleven_multilingual_v2"

    def test_elevenlabs_settings_custom(self) -> None:
        from pydantic import SecretStr

        from agent33.config import Settings

        s = Settings(
            environment="test",
            voice_elevenlabs_enabled=True,
            voice_elevenlabs_api_key=SecretStr("sk-test-key"),
            voice_elevenlabs_default_voice_id="voice-abc",
            voice_elevenlabs_model_id="eleven_turbo_v2",
            _env_file=None,  # type: ignore[call-arg]
        )
        assert s.voice_elevenlabs_enabled is True
        assert s.voice_elevenlabs_api_key.get_secret_value() == "sk-test-key"
        assert s.voice_elevenlabs_default_voice_id == "voice-abc"
        assert s.voice_elevenlabs_model_id == "eleven_turbo_v2"
