"""CLI entrypoint for the standalone voice sidecar."""

from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from agent33.voice.app import create_voice_sidecar_app
from agent33.voice.service import VoiceSidecarService

app = typer.Typer(help="Run the AGENT-33 standalone voice sidecar.")


@app.command()
def main(
    host: str = "127.0.0.1",
    port: int = 8790,
    voices_path: str = "config/voice/voices.json",
    artifacts_dir: str = "var/voice-sidecar",
    playback_backend: str = "noop",
) -> None:
    """Launch the sidecar FastAPI app via Uvicorn."""
    service = VoiceSidecarService(
        voices_path=Path(voices_path),
        artifacts_dir=Path(artifacts_dir),
        playback_backend=playback_backend,
    )
    uvicorn.run(create_voice_sidecar_app(service), host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()
