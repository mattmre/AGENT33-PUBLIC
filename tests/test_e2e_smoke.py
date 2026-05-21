"""Production-surface smoke test for the AGENT-33 engine."""

from __future__ import annotations

import sys
from pathlib import Path


def test_agent33_fastapi_app_surface_boots() -> None:
    """Import the production FastAPI app without starting external services."""
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root / "engine" / "src"))

    from agent33.main import app

    assert app.title == "AGENT-33"
    routes = {getattr(route, "path", "") for route in app.routes}
    assert "/health" in routes
