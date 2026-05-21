"""Hatchling build hook: bundle the React frontend before wheel packaging.

When ``hatch build`` runs, this hook:
1. Runs ``npm ci && npm run build`` in the ``../frontend/`` directory.
2. Copies ``frontend/dist/`` into ``src/agent33/static/ui/`` so the wheel
   includes the built assets.

The hook is a no-op when the ``AGENT33_SKIP_FRONTEND_BUILD`` env var is set
to ``1``, which allows CI jobs and developers to skip the Node.js build when
testing Python-only changes.

If ``npm`` is not found on PATH, the hook prints a warning and returns
without error -- this allows ``pip install -e .`` to succeed in Python-only
development environments.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


def _find_npm() -> str | None:
    """Locate the npm executable, returning its path or None."""
    return shutil.which("npm")


class CustomBuildHook(BuildHookInterface):  # type: ignore[misc]
    """Hatchling build hook that compiles the React frontend before packaging."""

    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Run the frontend build and copy assets into the package tree."""
        if os.environ.get("AGENT33_SKIP_FRONTEND_BUILD") == "1":
            return

        repo_root = Path(self.root).parent  # engine/ -> repo root
        frontend_dir = repo_root / "frontend"
        static_dest = Path(self.root) / "src" / "agent33" / "static" / "ui"

        if not frontend_dir.exists():
            # Frontend directory missing -- skip gracefully (headless / API-only installs)
            return

        npm = _find_npm()
        if npm is None:
            print(  # noqa: T201
                "WARNING: npm not found on PATH. "
                "Skipping frontend build. "
                "The wheel will not include the React UI. "
                "Install Node.js or set AGENT33_SKIP_FRONTEND_BUILD=1 "
                "to suppress this warning.",
                file=sys.stderr,
            )
            return

        # Merge env to preserve PATH (required on Windows)
        env = {**os.environ}

        # Install npm dependencies
        subprocess.run(
            [npm, "ci", "--prefer-offline"],
            cwd=str(frontend_dir),
            check=True,
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        # Build the frontend
        subprocess.run(
            [npm, "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            env=env,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

        # Copy dist -> static/ui
        dist_dir = frontend_dir / "dist"
        if not dist_dir.exists():
            msg = f"Frontend build did not produce {dist_dir}"
            raise RuntimeError(msg)

        if static_dest.exists():
            shutil.rmtree(static_dest)
        shutil.copytree(str(dist_dir), str(static_dest))
