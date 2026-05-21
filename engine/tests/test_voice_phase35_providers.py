"""Phase 35 tests: provider abstraction, TTS/STT dispatch, transcribe route,
session audio format, DELETE session, and provider health.

Tests exercise real behavior through the provider protocol layer and HTTP routes,
not just route existence.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from agent33.voice.app import create_voice_sidecar_app
from agent33.voice.models import AudioFormatConfig
from agent33.voice.providers import (
    AudioEncoding,
    AudioFormat,
    ElevenLabsTTSProviderAdapter,
    OpenAIWhisperSTTProvider,
    PiperTTSProvider,
    STTProvider,
    STTResult,
    StubSTTProvider,
    StubTTSProvider,
    TTSProvider,
    TTSResult,
    WhisperSTTProvider,
)
from agent33.voice.service import VoiceSidecarService

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_service(
    tmp_path: Path,
    *,
    tts_provider: TTSProvider | None = None,
    stt_provider: STTProvider | None = None,
) -> VoiceSidecarService:
    voices_path = tmp_path / "voices.json"
    voices_path.write_text(
        json.dumps({"voices": [{"id": "default", "name": "Default"}]}),
        encoding="utf-8",
    )
    return VoiceSidecarService(
        voices_path=voices_path,
        artifacts_dir=tmp_path / "artifacts",
        playback_backend="noop",
        tts_provider=tts_provider,
        stt_provider=stt_provider,
    )


# ------------------------------------------------------------------
# AudioFormat dataclass
# ------------------------------------------------------------------


class TestAudioFormat:
    def test_default_values(self) -> None:
        fmt = AudioFormat()
        assert fmt.encoding == AudioEncoding.PCM_S16LE
        assert fmt.sample_rate == 16000
        assert fmt.channels == 1
        assert fmt.bit_depth == 16

    def test_custom_values(self) -> None:
        fmt = AudioFormat(encoding=AudioEncoding.MP3, sample_rate=44100, channels=2, bit_depth=16)
        assert fmt.encoding == AudioEncoding.MP3
        assert fmt.sample_rate == 44100
        assert fmt.channels == 2

    def test_invalid_sample_rate_low(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            AudioFormat(sample_rate=4000)

    def test_invalid_sample_rate_high(self) -> None:
        with pytest.raises(ValueError, match="sample_rate"):
            AudioFormat(sample_rate=96000)

    def test_invalid_channels(self) -> None:
        with pytest.raises(ValueError, match="channels"):
            AudioFormat(channels=0)

    def test_invalid_bit_depth(self) -> None:
        with pytest.raises(ValueError, match="bit_depth"):
            AudioFormat(bit_depth=12)

    def test_frozen(self) -> None:
        fmt = AudioFormat()
        with pytest.raises(AttributeError):
            fmt.sample_rate = 44100  # type: ignore[misc]


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------


class TestProtocolConformance:
    def test_stub_tts_is_tts_provider(self) -> None:
        provider = StubTTSProvider()
        assert isinstance(provider, TTSProvider)

    def test_stub_stt_is_stt_provider(self) -> None:
        provider = StubSTTProvider()
        assert isinstance(provider, STTProvider)

    def test_piper_tts_is_tts_provider(self) -> None:
        provider = PiperTTSProvider()
        assert isinstance(provider, TTSProvider)

    def test_whisper_stt_is_stt_provider(self) -> None:
        provider = WhisperSTTProvider()
        assert isinstance(provider, STTProvider)

    def test_openai_whisper_is_stt_provider(self) -> None:
        provider = OpenAIWhisperSTTProvider()
        assert isinstance(provider, STTProvider)


# ------------------------------------------------------------------
# StubTTSProvider
# ------------------------------------------------------------------


class TestStubTTSProvider:
    @pytest.mark.asyncio
    async def test_synthesize_returns_audio_bytes(self) -> None:
        provider = StubTTSProvider()
        result = await provider.synthesize("Hello world")
        assert isinstance(result, TTSResult)
        assert len(result.audio_data) > 0
        assert result.provider == "stub"
        assert result.duration_ms == 100.0

    @pytest.mark.asyncio
    async def test_synthesize_empty_text_raises(self) -> None:
        provider = StubTTSProvider()
        with pytest.raises(ValueError, match="text must not be empty"):
            await provider.synthesize("")

    @pytest.mark.asyncio
    async def test_synthesize_custom_format(self) -> None:
        provider = StubTTSProvider()
        fmt = AudioFormat(encoding=AudioEncoding.WAV, sample_rate=22050)
        result = await provider.synthesize("Test", audio_format=fmt)
        assert result.audio_format.sample_rate == 22050
        assert result.audio_format.encoding == AudioEncoding.WAV

    @pytest.mark.asyncio
    async def test_synthesize_voice_id_in_metadata(self) -> None:
        provider = StubTTSProvider()
        result = await provider.synthesize("Test", voice_id="custom-voice")
        assert result.metadata["voice_id"] == "custom-voice"

    @pytest.mark.asyncio
    async def test_list_voices(self) -> None:
        provider = StubTTSProvider()
        voices = await provider.list_voices()
        assert len(voices) == 2
        assert voices[0]["voice_id"] == "stub-default"

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        provider = StubTTSProvider()
        assert await provider.health_check() is True

    def test_provider_name(self) -> None:
        provider = StubTTSProvider()
        assert provider.provider_name == "stub"


# ------------------------------------------------------------------
# StubSTTProvider
# ------------------------------------------------------------------


class TestStubSTTProvider:
    @pytest.mark.asyncio
    async def test_transcribe_returns_text(self) -> None:
        provider = StubSTTProvider()
        result = await provider.transcribe(b"\x00\x01\x02\x03")
        assert isinstance(result, STTResult)
        assert result.text == "[stub transcription]"
        assert result.confidence == 1.0
        assert result.provider == "stub"

    @pytest.mark.asyncio
    async def test_transcribe_empty_audio_raises(self) -> None:
        provider = StubSTTProvider()
        with pytest.raises(ValueError, match="audio_data must not be empty"):
            await provider.transcribe(b"")

    @pytest.mark.asyncio
    async def test_transcribe_language_passthrough(self) -> None:
        provider = StubSTTProvider()
        result = await provider.transcribe(b"\x00", language="fr")
        assert result.language == "fr"

    @pytest.mark.asyncio
    async def test_transcribe_audio_bytes_in_metadata(self) -> None:
        provider = StubSTTProvider()
        data = b"\x00" * 100
        result = await provider.transcribe(data)
        assert result.metadata["audio_bytes"] == 100

    @pytest.mark.asyncio
    async def test_health_check(self) -> None:
        provider = StubSTTProvider()
        assert await provider.health_check() is True

    def test_provider_name(self) -> None:
        provider = StubSTTProvider()
        assert provider.provider_name == "stub"


# ------------------------------------------------------------------
# PiperTTSProvider
# ------------------------------------------------------------------


class TestPiperTTSProvider:
    @pytest.mark.asyncio
    async def test_synthesize_invokes_piper_cli(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model_path = tmp_path / "voice.onnx"
        model_path.write_bytes(b"model")
        captured: dict[str, Any] = {}

        class FakeProcess:
            returncode = 0

            async def communicate(self, input_data: bytes) -> tuple[bytes, bytes]:
                captured["input"] = input_data
                output_path = Path(captured["args"][captured["args"].index("--output_file") + 1])
                output_path.write_bytes(b"RIFFaudio")
                return b"", b""

        async def fake_exec(*args: str, **_kwargs: Any) -> FakeProcess:
            captured["args"] = list(args)
            return FakeProcess()

        monkeypatch.setattr("agent33.voice.providers.shutil.which", lambda _exe: "piper")
        monkeypatch.setattr("agent33.voice.providers.asyncio.create_subprocess_exec", fake_exec)

        provider = PiperTTSProvider(model_path=str(model_path))
        result = await provider.synthesize("Hello")
        assert result.audio_data == b"RIFFaudio"
        assert result.provider == "piper"
        assert result.metadata["model_path"] == str(model_path)
        assert captured["input"] == b"Hello"

    @pytest.mark.asyncio
    async def test_custom_model_path(self) -> None:
        provider = PiperTTSProvider(model_path="/models/piper.onnx")
        voices = await provider.list_voices()
        assert voices[0]["provider"] == "piper"

    @pytest.mark.asyncio
    async def test_custom_voice_id(self) -> None:
        provider = PiperTTSProvider(voice_id="en_GB-alba-medium")
        voices = await provider.list_voices()
        assert voices[0]["voice_id"] == "en_GB-alba-medium"

    @pytest.mark.asyncio
    async def test_list_voices(self) -> None:
        provider = PiperTTSProvider()
        voices = await provider.list_voices()
        assert len(voices) == 1
        assert voices[0]["provider"] == "piper"

    @pytest.mark.asyncio
    async def test_empty_text_raises(self) -> None:
        provider = PiperTTSProvider()
        with pytest.raises(ValueError, match="text must not be empty"):
            await provider.synthesize("")

    @pytest.mark.asyncio
    async def test_missing_binary_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("agent33.voice.providers.shutil.which", lambda _exe: None)
        provider = PiperTTSProvider(model_path="/models/piper.onnx")
        with pytest.raises(RuntimeError, match="Piper executable"):
            await provider.synthesize("Hello")

    @pytest.mark.asyncio
    async def test_health_check_requires_binary_and_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model_path = tmp_path / "voice.onnx"
        model_path.write_bytes(b"model")
        monkeypatch.setattr("agent33.voice.providers.shutil.which", lambda _exe: "piper")
        assert await PiperTTSProvider(model_path=str(model_path)).health_check() is True
        missing_provider = PiperTTSProvider(model_path=str(tmp_path / "missing.onnx"))
        assert await missing_provider.health_check() is False

    def test_provider_name(self) -> None:
        assert PiperTTSProvider().provider_name == "piper"


# ------------------------------------------------------------------
# WhisperSTTProvider
# ------------------------------------------------------------------


class TestWhisperSTTProvider:
    @pytest.mark.asyncio
    async def test_transcribe_uses_local_whisper_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeModel:
            def transcribe(self, audio_path: str, **kwargs: Any) -> dict[str, str]:
                assert Path(audio_path).exists()
                assert kwargs["language"] == "de"
                return {"text": "Guten Tag", "language": "de"}

        fake_whisper = SimpleNamespace(load_model=lambda model_size, device: FakeModel())
        monkeypatch.setattr(
            "agent33.voice.providers.importlib.import_module",
            lambda name: fake_whisper,
        )

        provider = WhisperSTTProvider()
        result = await provider.transcribe(b"\x00\x01", language="de")
        assert result.text == "Guten Tag"
        assert result.provider == "whisper"
        assert result.metadata["model_size"] == "base"

    @pytest.mark.asyncio
    async def test_custom_model_and_device(self) -> None:
        provider = WhisperSTTProvider(model_size="large", device="cuda")
        assert provider.provider_name == "whisper"

    @pytest.mark.asyncio
    async def test_empty_audio_raises(self) -> None:
        provider = WhisperSTTProvider()
        with pytest.raises(ValueError, match="audio_data must not be empty"):
            await provider.transcribe(b"")

    @pytest.mark.asyncio
    async def test_language_passthrough(self) -> None:
        provider = StubSTTProvider()
        result = await provider.transcribe(b"\x00", language="de")
        assert result.language == "de"

    @pytest.mark.asyncio
    async def test_missing_whisper_package_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing_module(_name: str) -> Any:
            raise ImportError("missing")

        monkeypatch.setattr("agent33.voice.providers.importlib.import_module", missing_module)
        provider = WhisperSTTProvider()
        with pytest.raises(RuntimeError, match="openai-whisper"):
            await provider.transcribe(b"\x00")

    @pytest.mark.asyncio
    async def test_health_check_reports_missing_package(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def missing_module(_name: str) -> Any:
            raise ImportError("missing")

        monkeypatch.setattr("agent33.voice.providers.importlib.import_module", missing_module)
        assert await WhisperSTTProvider().health_check() is False

    def test_provider_name(self) -> None:
        assert WhisperSTTProvider().provider_name == "whisper"


# ------------------------------------------------------------------
# OpenAIWhisperSTTProvider
# ------------------------------------------------------------------


class TestOpenAIWhisperSTTProvider:
    @pytest.mark.asyncio
    async def test_transcribe_without_api_key_raises(self) -> None:
        provider = OpenAIWhisperSTTProvider()
        with pytest.raises(RuntimeError, match="API key"):
            await provider.transcribe(b"\x00")

    @pytest.mark.asyncio
    async def test_transcribe_with_api_key_calls_openai(self) -> None:
        provider = OpenAIWhisperSTTProvider(api_key="test-key", base_url="https://api.test")
        transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"text": "hello from api"},
                request=request,
            )
        )

        original_client = httpx.AsyncClient

        def client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
            kwargs["transport"] = transport
            return original_client(*args, **kwargs)

        from unittest.mock import patch

        with patch("agent33.voice.providers.httpx.AsyncClient", client_factory):
            result = await provider.transcribe(
                b"\x00",
                audio_format=AudioFormat(encoding=AudioEncoding.WAV),
            )
        assert result.provider == "openai_whisper"
        assert result.text == "hello from api"
        assert result.metadata["model"] == "whisper-1"

    @pytest.mark.asyncio
    async def test_health_check_without_key(self) -> None:
        provider = OpenAIWhisperSTTProvider()
        assert await provider.health_check() is False

    @pytest.mark.asyncio
    async def test_health_check_with_key(self) -> None:
        provider = OpenAIWhisperSTTProvider(api_key="test-key")
        assert await provider.health_check() is True

    def test_provider_name(self) -> None:
        assert OpenAIWhisperSTTProvider().provider_name == "openai_whisper"


# ------------------------------------------------------------------
# ElevenLabsTTSProviderAdapter
# ------------------------------------------------------------------


class TestElevenLabsTTSProviderAdapter:
    @pytest.mark.asyncio
    async def test_adapter_wraps_transport(self) -> None:
        class FakeTransport:
            async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes:
                return b"\xff" * 100

            async def list_voices(self) -> list[dict[str, Any]]:
                return [{"voice_id": "v1", "name": "Voice One"}]

            async def health_check(self) -> bool:
                return True

        adapter = ElevenLabsTTSProviderAdapter(FakeTransport())
        assert adapter.provider_name == "elevenlabs"

        result = await adapter.synthesize("Hello")
        assert len(result.audio_data) == 100
        assert result.provider == "elevenlabs"

    @pytest.mark.asyncio
    async def test_adapter_list_voices(self) -> None:
        class FakeTransport:
            async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes:
                return b""

            async def list_voices(self) -> list[dict[str, Any]]:
                return [{"voice_id": "v1"}, {"voice_id": "v2"}]

            async def health_check(self) -> bool:
                return True

        adapter = ElevenLabsTTSProviderAdapter(FakeTransport())
        voices = await adapter.list_voices()
        assert len(voices) == 2

    @pytest.mark.asyncio
    async def test_adapter_health_check(self) -> None:
        class FakeTransport:
            async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes:
                return b""

            async def list_voices(self) -> list[dict[str, Any]]:
                return []

            async def health_check(self) -> bool:
                return False

        adapter = ElevenLabsTTSProviderAdapter(FakeTransport())
        assert await adapter.health_check() is False

    @pytest.mark.asyncio
    async def test_adapter_empty_text_raises(self) -> None:
        class FakeTransport:
            async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes:
                return b""

            async def list_voices(self) -> list[dict[str, Any]]:
                return []

            async def health_check(self) -> bool:
                return True

        adapter = ElevenLabsTTSProviderAdapter(FakeTransport())
        with pytest.raises(ValueError, match="text must not be empty"):
            await adapter.synthesize("")


# ------------------------------------------------------------------
# Service TTS/STT dispatch
# ------------------------------------------------------------------


class TestServiceProviderDispatch:
    @pytest.mark.asyncio
    async def test_service_synthesize_via_stub(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        result = await service.synthesize("Hello from service")
        assert result.provider == "stub"
        assert len(result.audio_data) > 0

    @pytest.mark.asyncio
    async def test_service_transcribe_via_stub(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        result = await service.transcribe(b"\x00\x01\x02")
        assert result.provider == "stub"
        assert result.text == "[stub transcription]"

    @pytest.mark.asyncio
    async def test_service_synthesize_logs_session_event(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        session = service.start_session(room_name="tts-room")
        await service.synthesize("Test TTS", session_id=session.session_id)

        events_file = tmp_path / "artifacts" / session.session_id / "events.jsonl"
        contents = events_file.read_text(encoding="utf-8")
        assert "tts.synthesized" in contents

    @pytest.mark.asyncio
    async def test_service_transcribe_logs_session_event(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        session = service.start_session(room_name="stt-room")
        await service.transcribe(b"\x00\x01", session_id=session.session_id)

        events_file = tmp_path / "artifacts" / session.session_id / "events.jsonl"
        contents = events_file.read_text(encoding="utf-8")
        assert "stt.transcribed" in contents

    @pytest.mark.asyncio
    async def test_service_synthesize_with_custom_provider(self, tmp_path: Path) -> None:
        class CustomTTSProvider(StubTTSProvider):
            @property
            def provider_name(self) -> str:
                return "custom"

        service = _make_service(tmp_path, tts_provider=CustomTTSProvider())
        result = await service.synthesize("Test with Piper")
        assert result.provider == "custom"

    @pytest.mark.asyncio
    async def test_service_transcribe_with_custom_provider(self, tmp_path: Path) -> None:
        class CustomSTTProvider(StubSTTProvider):
            @property
            def provider_name(self) -> str:
                return "custom"

        service = _make_service(tmp_path, stt_provider=CustomSTTProvider())
        result = await service.transcribe(b"\x00")
        assert result.provider == "custom"

    @pytest.mark.asyncio
    async def test_service_synthesize_invalid_session_id_ignored(self, tmp_path: Path) -> None:
        """Synthesis still succeeds when session_id points to a nonexistent session."""
        service = _make_service(tmp_path)
        result = await service.synthesize("Hello", session_id="nonexistent")
        assert result.provider == "stub"


# ------------------------------------------------------------------
# Session audio format and agent linking
# ------------------------------------------------------------------


class TestSessionAudioFormat:
    def test_session_has_default_audio_format(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        session = service.start_session(room_name="room")
        assert session.audio_format.encoding == "pcm_s16le"
        assert session.audio_format.sample_rate == 16000
        assert session.audio_format.channels == 1

    def test_session_custom_audio_format(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        fmt = AudioFormatConfig(encoding="mp3", sample_rate=44100, channels=2, bit_depth=16)
        session = service.start_session(room_name="room", audio_format=fmt)
        assert session.audio_format.encoding == "mp3"
        assert session.audio_format.sample_rate == 44100
        assert session.audio_format.channels == 2

    def test_session_agent_session_linking(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        session = service.start_session(room_name="room", agent_session_id="agent-sess-abc")
        assert session.agent_session_id == "agent-sess-abc"

    def test_session_provider_names_tracked(self, tmp_path: Path) -> None:
        class CustomTTSProvider(StubTTSProvider):
            @property
            def provider_name(self) -> str:
                return "custom"

        service = _make_service(tmp_path, tts_provider=CustomTTSProvider())
        session = service.start_session(room_name="room")
        assert session.tts_provider == "custom"
        assert session.stt_provider == "stub"


# ------------------------------------------------------------------
# Session delete
# ------------------------------------------------------------------


class TestSessionDelete:
    def test_delete_active_session(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        session = service.start_session(room_name="room")
        assert service.delete_session(session.session_id) is True
        assert service.get_session(session.session_id) is None

    def test_delete_stopped_session(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        session = service.start_session(room_name="room")
        service.stop_session(session.session_id)
        assert service.delete_session(session.session_id) is True
        assert service.get_session(session.session_id) is None

    def test_delete_nonexistent_returns_false(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        assert service.delete_session("nonexistent") is False


# ------------------------------------------------------------------
# Health snapshot with providers
# ------------------------------------------------------------------


class TestHealthSnapshotProviders:
    def test_health_includes_provider_names(self, tmp_path: Path) -> None:
        service = _make_service(
            tmp_path,
            tts_provider=PiperTTSProvider(),
            stt_provider=WhisperSTTProvider(),
        )
        health = service.health_snapshot()
        assert health.tts_provider == "piper"
        assert health.stt_provider == "whisper"

    def test_health_default_providers(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        health = service.health_snapshot()
        assert health.tts_provider == "stub"
        assert health.stt_provider == "stub"


# ------------------------------------------------------------------
# HTTP route tests: transcribe
# ------------------------------------------------------------------


class TestTranscribeRoute:
    @pytest.mark.asyncio
    async def test_transcribe_with_file(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/transcribe",
                files={"file": ("audio.wav", BytesIO(b"\x00\x01\x02\x03"), "audio/wav")},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ok"
            assert body["text"] == "[stub transcription]"
            assert body["confidence"] == 1.0
            assert body["provider"] == "stub"

    @pytest.mark.asyncio
    async def test_transcribe_no_file_returns_400(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/v1/voice/transcribe")
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_transcribe_empty_file_returns_400(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/transcribe",
                files={"file": ("audio.wav", BytesIO(b""), "audio/wav")},
            )
            assert response.status_code == 400
            assert "empty" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_transcribe_with_language_param(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/transcribe",
                files={"file": ("audio.wav", BytesIO(b"\x00"), "audio/wav")},
                data={"language": "fr"},
            )
            assert response.status_code == 200
            assert response.json()["language"] == "fr"

    @pytest.mark.asyncio
    async def test_transcribe_with_session_id(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        session = service.start_session(room_name="stt-room")
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/transcribe",
                files={"file": ("audio.wav", BytesIO(b"\x00"), "audio/wav")},
                data={"session_id": session.session_id},
            )
            assert response.status_code == 200

        events_file = tmp_path / "artifacts" / session.session_id / "events.jsonl"
        contents = events_file.read_text(encoding="utf-8")
        assert "stt.transcribed" in contents


# ------------------------------------------------------------------
# HTTP route tests: synthesize (provider-agnostic)
# ------------------------------------------------------------------


class TestSynthesizeRoute:
    @pytest.mark.asyncio
    async def test_synthesize_via_stub_provider(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/synthesize",
                json={"text": "Hello world"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ok"
            assert body["provider"] == "stub"
            assert body["size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_synthesize_empty_text_returns_400(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/synthesize",
                json={"text": ""},
            )
            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_synthesize_with_custom_provider(self, tmp_path: Path) -> None:
        class CustomTTSProvider(StubTTSProvider):
            @property
            def provider_name(self) -> str:
                return "custom"

        service = _make_service(tmp_path, tts_provider=CustomTTSProvider())
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/synthesize",
                json={"text": "Hello from Piper"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["provider"] == "custom"


# ------------------------------------------------------------------
# HTTP route tests: DELETE session
# ------------------------------------------------------------------


class TestDeleteSessionRoute:
    @pytest.mark.asyncio
    async def test_delete_session_route(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/v1/voice/sessions",
                json={"room_name": "delete-room"},
            )
            session_id = created.json()["session_id"]

            response = await client.delete(f"/v1/voice/sessions/{session_id}")
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "deleted"
            assert body["session_id"] == session_id

            # Verify session is gone
            get_response = await client.get(f"/v1/voice/sessions/{session_id}")
            assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_session_returns_404(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.delete("/v1/voice/sessions/nonexistent")
            assert response.status_code == 404


# ------------------------------------------------------------------
# HTTP route tests: session creation with audio format
# ------------------------------------------------------------------


class TestSessionCreationRoute:
    @pytest.mark.asyncio
    async def test_create_session_with_audio_format(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/sessions",
                json={
                    "room_name": "fmt-room",
                    "audio_format": {
                        "encoding": "mp3",
                        "sample_rate": 44100,
                        "channels": 2,
                        "bit_depth": 16,
                    },
                },
            )
            assert response.status_code == 201
            body = response.json()
            assert body["audio_format"]["encoding"] == "mp3"
            assert body["audio_format"]["sample_rate"] == 44100
            assert body["audio_format"]["channels"] == 2

    @pytest.mark.asyncio
    async def test_create_session_with_agent_session_id(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/sessions",
                json={
                    "room_name": "linked-room",
                    "agent_session_id": "agent-sess-xyz",
                },
            )
            assert response.status_code == 201
            body = response.json()
            assert body["agent_session_id"] == "agent-sess-xyz"

    @pytest.mark.asyncio
    async def test_create_session_default_audio_format(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/v1/voice/sessions",
                json={"room_name": "default-fmt-room"},
            )
            assert response.status_code == 201
            body = response.json()
            assert body["audio_format"]["encoding"] == "pcm_s16le"
            assert body["audio_format"]["sample_rate"] == 16000


# ------------------------------------------------------------------
# HTTP route tests: provider health
# ------------------------------------------------------------------


class TestProviderHealthRoute:
    @pytest.mark.asyncio
    async def test_providers_health_endpoint(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/voice/health/providers")
            assert response.status_code == 200
            body = response.json()
            assert body["tts"]["provider"] == "stub"
            assert body["tts"]["healthy"] is True
            assert body["stt"]["provider"] == "stub"
            assert body["stt"]["healthy"] is True


# ------------------------------------------------------------------
# HTTP route tests: voices listing (provider-agnostic)
# ------------------------------------------------------------------


class TestVoicesRoute:
    @pytest.mark.asyncio
    async def test_list_voices_from_stub_provider(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/v1/voice/voices")
            assert response.status_code == 200
            body = response.json()
            assert len(body["voices"]) >= 2  # stub-default + stub-alt


# ------------------------------------------------------------------
# Health endpoint includes providers
# ------------------------------------------------------------------


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_includes_provider_info(self, tmp_path: Path) -> None:
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            body = response.json()
            assert body["tts_provider"] == "stub"
            assert body["stt_provider"] == "stub"


# ------------------------------------------------------------------
# Backward compatibility: existing tests still work
# ------------------------------------------------------------------


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_existing_session_lifecycle(self, tmp_path: Path) -> None:
        """Verify the existing session lifecycle still works with the new fields."""
        service = _make_service(tmp_path)
        app = create_voice_sidecar_app(service)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/v1/voice/sessions",
                json={"room_name": "compat-room", "requested_by": "pytest"},
            )
            assert created.status_code == 201
            payload = created.json()
            assert payload["room_name"] == "compat-room"
            assert payload["state"] == "active"
            assert "audio_format" in payload  # new field present
            assert "agent_session_id" in payload  # new field present

            stopped = await client.post(f"/v1/voice/sessions/{payload['session_id']}/stop")
            assert stopped.status_code == 200
            assert stopped.json()["state"] == "stopped"
