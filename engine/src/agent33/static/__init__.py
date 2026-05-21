"""Static asset helpers for the agent33 package."""

from __future__ import annotations

from pathlib import Path


def ui_path() -> Path:
    """Return the path to the bundled React frontend assets.

    Returns the directory containing ``index.html`` and other built assets.
    Raises :class:`FileNotFoundError` if the wheel was built without the
    frontend (e.g. ``AGENT33_SKIP_FRONTEND_BUILD=1``).
    """
    path = Path(__file__).parent / "ui"
    if not path.exists():
        msg = (
            f"Frontend assets not found at {path}. "
            "Rebuild the wheel with frontend bundling enabled "
            "(unset AGENT33_SKIP_FRONTEND_BUILD)."
        )
        raise FileNotFoundError(msg)
    return path
