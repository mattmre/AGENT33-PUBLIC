"""Provider abstraction for TTS and STT backends.

Phase 35 delivers a provider-agnostic interface so the voice sidecar can swap
between local (Piper, Whisper) and cloud (ElevenLabs, OpenAI) backends without
touching orchestration code.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import shutil
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Audio format / metadata
# ------------------------------------------------------------------


class AudioEncoding(StrEnum):
    """Supported audio encodings for voice pipeline I/O."""

    PCM_S16LE = "pcm_s16le"
    MP3 = "mp3"
    OGG_OPUS = "ogg_opus"
    WAV = "wav"
    FLAC = "flac"


@dataclass(frozen=True)
class AudioFormat:
    """Describes the audio wire format for a voice session."""

    encoding: AudioEncoding = AudioEncoding.PCM_S16LE
    sample_rate: int = 16000
    channels: int = 1
    bit_depth: int = 16

    def __post_init__(self) -> None:
        if self.sample_rate < 8000 or self.sample_rate > 48000:
            raise ValueError(f"sample_rate must be 8000..48000, got {self.sample_rate}")
        if self.channels < 1 or self.channels > 2:
            raise ValueError(f"channels must be 1 or 2, got {self.channels}")
        if self.bit_depth not in {8, 16, 24, 32}:
            raise ValueError(f"bit_depth must be 8/16/24/32, got {self.bit_depth}")


@dataclass
class TTSResult:
    """Output from a TTS synthesis call."""

    audio_data: bytes
    audio_format: AudioFormat
    duration_ms: float = 0.0
    provider: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class STTResult:
    """Output from an STT transcription call."""

    text: str
    confidence: float = 0.0
    language: str = ""
    duration_ms: float = 0.0
    provider: str = ""
    is_partial: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------
# Provider protocols
# ------------------------------------------------------------------


@runtime_checkable
class TTSProvider(Protocol):
    """Protocol for text-to-speech providers.

    Implementations must provide ``synthesize`` and ``provider_name``.
    The voice sidecar dispatches to whichever TTSProvider is configured
    at startup, allowing hot-swap between local and cloud backends.
    """

    @property
    def provider_name(self) -> str: ...

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        audio_format: AudioFormat | None = None,
    ) -> TTSResult:
        """Convert *text* to audio bytes."""
        ...

    async def list_voices(self) -> list[dict[str, Any]]:
        """Return available voice identifiers for this provider."""
        ...

    async def health_check(self) -> bool:
        """Return True if the provider is reachable and ready."""
        ...


@runtime_checkable
class STTProvider(Protocol):
    """Protocol for speech-to-text providers.

    Implementations must provide ``transcribe`` and ``provider_name``.
    """

    @property
    def provider_name(self) -> str: ...

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: AudioFormat | None = None,
        language: str = "",
    ) -> STTResult:
        """Transcribe *audio_data* to text."""
        ...

    async def health_check(self) -> bool:
        """Return True if the provider is reachable and ready."""
        ...


# ------------------------------------------------------------------
# Base implementations (ABC for subclass convenience)
# ------------------------------------------------------------------


class BaseTTSProvider(ABC):
    """Abstract base class for TTS providers with shared helpers."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        audio_format: AudioFormat | None = None,
    ) -> TTSResult: ...

    async def list_voices(self) -> list[dict[str, Any]]:
        """Default: no discoverable voices."""
        return []

    async def health_check(self) -> bool:
        """Default: always healthy if constructed."""
        return True


class BaseSTTProvider(ABC):
    """Abstract base class for STT providers with shared helpers."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: AudioFormat | None = None,
        language: str = "",
    ) -> STTResult: ...

    async def health_check(self) -> bool:
        """Default: always healthy if constructed."""
        return True


# ------------------------------------------------------------------
# Stub / local providers
# ------------------------------------------------------------------


class StubTTSProvider(BaseTTSProvider):
    """No-op TTS provider for testing and development.

    Returns a deterministic zero-filled audio buffer so callers can
    exercise the full pipeline without a real TTS backend.
    """

    @property
    def provider_name(self) -> str:
        return "stub"

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        audio_format: AudioFormat | None = None,
    ) -> TTSResult:
        if not text:
            raise ValueError("text must not be empty")
        fmt = audio_format or AudioFormat()
        # Generate a deterministic silence buffer: ~100ms of audio at the
        # requested sample rate.
        sample_bytes = fmt.bit_depth // 8
        num_samples = int(fmt.sample_rate * 0.1) * fmt.channels
        audio_data = b"\x00" * (num_samples * sample_bytes)
        return TTSResult(
            audio_data=audio_data,
            audio_format=fmt,
            duration_ms=100.0,
            provider=self.provider_name,
            metadata={"voice_id": voice_id or "stub-default", "text_length": len(text)},
        )

    async def list_voices(self) -> list[dict[str, Any]]:
        return [
            {"voice_id": "stub-default", "name": "Stub Default", "provider": "stub"},
            {"voice_id": "stub-alt", "name": "Stub Alternate", "provider": "stub"},
        ]


class StubSTTProvider(BaseSTTProvider):
    """No-op STT provider for testing and development.

    Returns a fixed transcription string so callers can exercise
    the full pipeline without a real STT backend.
    """

    @property
    def provider_name(self) -> str:
        return "stub"

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: AudioFormat | None = None,
        language: str = "",
    ) -> STTResult:
        if not audio_data:
            raise ValueError("audio_data must not be empty")
        return STTResult(
            text="[stub transcription]",
            confidence=1.0,
            language=language or "en",
            duration_ms=0.0,
            provider=self.provider_name,
            metadata={"audio_bytes": len(audio_data)},
        )


# ------------------------------------------------------------------
# Local providers (Piper TTS / Whisper STT)
# ------------------------------------------------------------------


class PiperTTSProvider(BaseTTSProvider):
    """Local Piper TTS provider backed by the ``piper`` CLI.

    The provider fails closed when the executable or model is not configured,
    so a selected real backend never returns synthetic audio.
    """

    def __init__(
        self,
        *,
        model_path: str = "",
        voice_id: str = "en_US-lessac-medium",
        executable: str = "piper",
    ) -> None:
        self._model_path = model_path
        self._default_voice_id = voice_id
        self._executable = executable

    @property
    def provider_name(self) -> str:
        return "piper"

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        audio_format: AudioFormat | None = None,
    ) -> TTSResult:
        if not text:
            raise ValueError("text must not be empty")
        fmt = audio_format or AudioFormat(encoding=AudioEncoding.WAV, sample_rate=22050)
        resolved_executable = shutil.which(self._executable)
        if not resolved_executable:
            raise RuntimeError(f"Piper executable is not available: {self._executable}")
        if not self._model_path:
            raise RuntimeError("Piper model_path is not configured")
        model_path = Path(self._model_path)
        if not model_path.exists():
            raise RuntimeError(f"Piper model_path does not exist: {model_path}")

        started = time.perf_counter()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output_file:
            output_path = Path(output_file.name)
        try:
            proc = await asyncio.create_subprocess_exec(
                resolved_executable,
                "--model",
                str(model_path),
                "--output_file",
                str(output_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _stdout, stderr = await proc.communicate(text.encode("utf-8"))
            if proc.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Piper synthesis failed: {detail or proc.returncode}")
            audio_data = output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)

        return TTSResult(
            audio_data=audio_data,
            audio_format=fmt,
            duration_ms=(time.perf_counter() - started) * 1000,
            provider=self.provider_name,
            metadata={
                "voice_id": voice_id or self._default_voice_id,
                "model_path": self._model_path,
            },
        )

    async def list_voices(self) -> list[dict[str, Any]]:
        return [
            {
                "voice_id": self._default_voice_id,
                "name": "Piper Lessac Medium",
                "provider": "piper",
            },
        ]

    async def health_check(self) -> bool:
        return bool(
            shutil.which(self._executable) and self._model_path and Path(self._model_path).exists()
        )


class WhisperSTTProvider(BaseSTTProvider):
    """Local Whisper STT provider backed by the optional ``whisper`` package.

    The model is loaded lazily and real transcription is performed in a worker
    thread because Whisper inference is blocking.
    """

    def __init__(self, *, model_size: str = "base", device: str = "cpu") -> None:
        self._model_size = model_size
        self._device = device
        self._model: Any | None = None

    @property
    def provider_name(self) -> str:
        return "whisper"

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: AudioFormat | None = None,
        language: str = "",
    ) -> STTResult:
        if not audio_data:
            raise ValueError("audio_data must not be empty")
        model = self._load_model()
        fmt = audio_format or AudioFormat(encoding=AudioEncoding.WAV)
        suffix = _suffix_for_audio_encoding(fmt.encoding)
        started = time.perf_counter()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as audio_file:
            audio_path = Path(audio_file.name)
            audio_file.write(audio_data)
        try:
            options: dict[str, Any] = {}
            if language:
                options["language"] = language
            transcription = await asyncio.to_thread(model.transcribe, str(audio_path), **options)
        finally:
            audio_path.unlink(missing_ok=True)
        text = str(transcription.get("text", "")).strip()
        detected_language = str(transcription.get("language") or language or "")
        return STTResult(
            text=text,
            confidence=0.0,
            language=detected_language,
            duration_ms=(time.perf_counter() - started) * 1000,
            provider=self.provider_name,
            metadata={
                "model_size": self._model_size,
                "device": self._device,
            },
        )

    async def health_check(self) -> bool:
        try:
            importlib.import_module("whisper")
        except ImportError:
            return False
        return True

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            whisper = importlib.import_module("whisper")
        except ImportError as exc:
            raise RuntimeError("openai-whisper package is not installed") from exc
        self._model = whisper.load_model(self._model_size, device=self._device)
        return self._model


# ------------------------------------------------------------------
# Cloud providers
# ------------------------------------------------------------------


class OpenAIWhisperSTTProvider(BaseSTTProvider):
    """Cloud OpenAI Whisper API provider."""

    def __init__(
        self,
        *,
        api_key: str = "",
        model: str = "whisper-1",
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 60.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "openai_whisper"

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        audio_format: AudioFormat | None = None,
        language: str = "",
    ) -> STTResult:
        if not audio_data:
            raise ValueError("audio_data must not be empty")
        if not self._api_key:
            raise RuntimeError("OpenAI API key is not configured")
        fmt = audio_format or AudioFormat(encoding=AudioEncoding.WAV)
        filename = f"audio{_suffix_for_audio_encoding(fmt.encoding)}"
        data: dict[str, str] = {"model": self._model, "response_format": "json"}
        if language:
            data["language"] = language
        headers = {"Authorization": f"Bearer {self._api_key}"}
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/audio/transcriptions",
                headers=headers,
                data=data,
                files={"file": (filename, audio_data, _mime_for_audio_encoding(fmt.encoding))},
            )
            response.raise_for_status()
        payload = response.json()
        return STTResult(
            text=str(payload.get("text", "")).strip(),
            confidence=0.0,
            language=language or "en",
            duration_ms=(time.perf_counter() - started) * 1000,
            provider=self.provider_name,
            metadata={"model": self._model},
        )

    async def health_check(self) -> bool:
        return bool(self._api_key)


def _suffix_for_audio_encoding(encoding: AudioEncoding) -> str:
    return {
        AudioEncoding.PCM_S16LE: ".raw",
        AudioEncoding.MP3: ".mp3",
        AudioEncoding.OGG_OPUS: ".ogg",
        AudioEncoding.WAV: ".wav",
        AudioEncoding.FLAC: ".flac",
    }[encoding]


def _mime_for_audio_encoding(encoding: AudioEncoding) -> str:
    return {
        AudioEncoding.PCM_S16LE: "application/octet-stream",
        AudioEncoding.MP3: "audio/mpeg",
        AudioEncoding.OGG_OPUS: "audio/ogg",
        AudioEncoding.WAV: "audio/wav",
        AudioEncoding.FLAC: "audio/flac",
    }[encoding]


class ElevenLabsTTSProviderAdapter(BaseTTSProvider):
    """Adapter wrapping the existing ElevenLabsTransport as a TTSProvider.

    This bridges the pre-existing ``ElevenLabsTransport`` class (which
    predates the provider abstraction) into the Phase 35 protocol so
    existing ElevenLabs configuration continues to work.
    """

    def __init__(self, transport: Any) -> None:
        self._transport = transport

    @property
    def provider_name(self) -> str:
        return "elevenlabs"

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        audio_format: AudioFormat | None = None,
    ) -> TTSResult:
        if not text:
            raise ValueError("text must not be empty")
        audio_data: bytes = await self._transport.synthesize(text, voice_id=voice_id or None)
        fmt = audio_format or AudioFormat(encoding=AudioEncoding.MP3, sample_rate=44100)
        return TTSResult(
            audio_data=audio_data,
            audio_format=fmt,
            provider=self.provider_name,
            metadata={"voice_id": voice_id, "size_bytes": len(audio_data)},
        )

    async def list_voices(self) -> list[dict[str, Any]]:
        voices: list[dict[str, Any]] = await self._transport.list_voices()
        return voices

    async def health_check(self) -> bool:
        result: bool = await self._transport.health_check()
        return result
