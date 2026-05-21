"""Phase 35 tests for LiveVoiceDaemon lifecycle and stub behaviour."""

from __future__ import annotations

import pytest

from agent33.multimodal.voice_daemon import LiveVoiceDaemon


@pytest.fixture
def daemon() -> LiveVoiceDaemon:
    return LiveVoiceDaemon(
        room_name="test-room",
        url="wss://livekit.example.com",
        api_key="test-key",
        api_secret="test-secret",
    )


# ------------------------------------------------------------------
# Lifecycle
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_sets_active(daemon: LiveVoiceDaemon) -> None:
    assert not daemon.health_check()
    await daemon.start()
    assert daemon.health_check()


@pytest.mark.asyncio
async def test_stop_clears_active(daemon: LiveVoiceDaemon) -> None:
    await daemon.start()
    assert daemon.health_check()
    await daemon.stop()
    assert not daemon.health_check()


@pytest.mark.asyncio
async def test_start_stop_idempotent(daemon: LiveVoiceDaemon) -> None:
    """Calling start/stop multiple times must not raise."""
    await daemon.start()
    await daemon.start()
    assert daemon.health_check()
    await daemon.stop()
    await daemon.stop()
    assert not daemon.health_check()


# ------------------------------------------------------------------
# Health check
# ------------------------------------------------------------------


def test_health_check_false_before_start(daemon: LiveVoiceDaemon) -> None:
    assert daemon.health_check() is False


@pytest.mark.asyncio
async def test_health_check_true_when_started(daemon: LiveVoiceDaemon) -> None:
    await daemon.start()
    assert daemon.health_check() is True


@pytest.mark.asyncio
async def test_health_check_false_after_stop(daemon: LiveVoiceDaemon) -> None:
    await daemon.start()
    await daemon.stop()
    assert daemon.health_check() is False


# ------------------------------------------------------------------
# Audio processing stubs
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_audio_chunk_returns_none(daemon: LiveVoiceDaemon) -> None:
    """Stub must return None until LiveKit wiring is added."""
    await daemon.start()
    result = await daemon.process_audio_chunk(b"\x00\x01\x02\x03")
    assert result is None


@pytest.mark.asyncio
async def test_process_audio_chunk_empty_bytes(daemon: LiveVoiceDaemon) -> None:
    await daemon.start()
    result = await daemon.process_audio_chunk(b"")
    assert result is None


@pytest.mark.asyncio
async def test_synthesize_speech_returns_none(daemon: LiveVoiceDaemon) -> None:
    """Stub must return None until LiveKit wiring is added."""
    await daemon.start()
    result = await daemon.synthesize_speech("Hello, world!")
    assert result is None


@pytest.mark.asyncio
async def test_synthesize_speech_empty_text(daemon: LiveVoiceDaemon) -> None:
    await daemon.start()
    result = await daemon.synthesize_speech("")
    assert result is None


@pytest.mark.asyncio
async def test_process_audio_chunk_requires_active_daemon(daemon: LiveVoiceDaemon) -> None:
    with pytest.raises(RuntimeError, match="not active"):
        await daemon.process_audio_chunk(b"\x00")


@pytest.mark.asyncio
async def test_synthesize_speech_requires_active_daemon(daemon: LiveVoiceDaemon) -> None:
    with pytest.raises(RuntimeError, match="not active"):
        await daemon.synthesize_speech("hello")


@pytest.mark.asyncio
async def test_livekit_transport_raises_dependency_gap() -> None:
    daemon = LiveVoiceDaemon(
        room_name="livekit-room",
        url="wss://livekit.example.com",
        api_key="livekit-key",
        api_secret="livekit-secret",
        transport="livekit",
    )
    with pytest.raises(RuntimeError, match="voice sidecar"):
        await daemon.start()


@pytest.mark.asyncio
async def test_snapshot_tracks_stub_runtime_state(daemon: LiveVoiceDaemon) -> None:
    await daemon.start()
    await daemon.process_audio_chunk(b"\x00\x01")
    await daemon.synthesize_speech("hello")

    snapshot = daemon.snapshot()

    assert snapshot["active"] is True
    assert snapshot["transport"] == "stub"
    assert snapshot["processed_chunks"] == 1
    assert snapshot["synthesized_utterances"] == 1
