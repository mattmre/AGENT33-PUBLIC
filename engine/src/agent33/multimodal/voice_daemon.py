"""Voice daemon compatibility adapter.

LiveKit room management is served by the voice sidecar. This adapter preserves
the older in-process daemon lifecycle API for session accounting and redirects
operators to the sidecar when they select the LiveKit transport.
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

logger = structlog.get_logger()

VOICE_LIVEKIT_DEFERRED_MESSAGE = (
    "livekit transport is available via the voice sidecar (S32); "
    "set voice_livekit_enabled=True and configure voice_livekit_api_key, "
    "voice_livekit_api_secret, voice_livekit_ws_url to enable it"
)

VOICE_LIVEKIT_SIDECAR_AVAILABLE_MESSAGE = (
    "livekit transport is configured and available in the voice sidecar; "
    "connect to the sidecar's /v1/voice/livekit/ endpoints for room management"
)


class LiveVoiceDaemon:
    """Track voice daemon lifecycle state for legacy callers.

    Lifecycle
    ---------
    1. Construct with room/connection parameters.
    2. ``await start()`` marks the compatibility session active.
    3. ``process_audio_chunk`` and ``synthesize_speech`` count legacy calls but
       do not produce fake transcripts or audio.
    4. ``await stop()`` tears down the compatibility session.

    Use ``health_check()`` at any point to query liveness.
    """

    def __init__(
        self,
        room_name: str,
        url: str,
        api_key: str,
        api_secret: str,
        *,
        transport: str = "stub",
    ) -> None:
        self._room_name = room_name
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._transport = transport
        self._active = False
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._processed_chunks = 0
        self._synthesized_utterances = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the compatibility session or redirect LiveKit to the sidecar."""
        logger.info(
            "voice_daemon.starting",
            room=self._room_name,
            url=self._url,
            transport=self._transport,
        )
        if self._active:
            logger.debug("voice_daemon.start_skipped", room=self._room_name)
            return
        if self._transport == "livekit":
            logger.info(
                "voice_daemon.livekit_redirect",
                msg=VOICE_LIVEKIT_DEFERRED_MESSAGE,
            )
            raise RuntimeError(VOICE_LIVEKIT_DEFERRED_MESSAGE)
        if self._transport != "stub":
            raise ValueError(f"Unsupported voice daemon transport: {self._transport}")
        self._active = True
        self._started_at = datetime.now(UTC)
        self._stopped_at = None
        logger.info("voice_daemon.started", room=self._room_name, transport=self._transport)

    async def stop(self) -> None:
        """Stop the compatibility session."""
        logger.info("voice_daemon.stopping", room=self._room_name)
        if not self._active:
            logger.debug("voice_daemon.stop_skipped", room=self._room_name)
            return
        self._active = False
        self._stopped_at = datetime.now(UTC)
        logger.info("voice_daemon.stopped", room=self._room_name)

    def health_check(self) -> bool:
        """Return ``True`` when the compatibility session is active."""
        healthy = self._active
        logger.debug("voice_daemon.health_check", healthy=healthy, room=self._room_name)
        return healthy

    # ------------------------------------------------------------------
    # Legacy audio counters
    # ------------------------------------------------------------------

    async def process_audio_chunk(self, chunk: bytes) -> str | None:
        """Receive a raw audio chunk and return transcribed text, if any.

        The compatibility daemon does not synthesize fake transcript text.
        Realtime transcription is available from the voice sidecar.
        """
        if not self._active:
            raise RuntimeError("Voice daemon is not active")
        self._processed_chunks += 1
        logger.debug(
            "voice_daemon.process_audio_chunk",
            chunk_bytes=len(chunk),
            room=self._room_name,
        )
        return None

    async def synthesize_speech(self, text: str) -> bytes | None:
        """Convert *text* to speech audio bytes.

        The compatibility daemon does not synthesize fake audio bytes.
        Realtime speech output is available from the voice sidecar.
        """
        if not self._active:
            raise RuntimeError("Voice daemon is not active")
        self._synthesized_utterances += 1
        logger.debug(
            "voice_daemon.synthesize_speech",
            text_length=len(text),
            room=self._room_name,
        )
        return None

    def snapshot(self) -> dict[str, object]:
        """Return deterministic daemon status for API/session management."""
        return {
            "room_name": self._room_name,
            "transport": self._transport,
            "active": self._active,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "stopped_at": self._stopped_at.isoformat() if self._stopped_at else None,
            "processed_chunks": self._processed_chunks,
            "synthesized_utterances": self._synthesized_utterances,
        }
