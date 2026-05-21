"""BrowserBase cloud browser backend (Phase 55).

Provides a ``CloudBrowserBackend`` that manages remote headless browser
sessions via the BrowserBase REST API. When configured, the BrowserTool can
offload browser execution to the cloud instead of running local Playwright.

Design:
  - Sessions are created via ``POST /sessions`` and connected to via a
    Playwright CDP endpoint returned in the session response.
  - Fallback: when no API key is configured, callers should use the local
    Playwright backend (this module returns ``None`` from ``connect``).
  - Session lifecycle is managed through ``connect``, ``disconnect``, and
    ``list_sessions`` methods.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_BROWSERBASE_AVAILABLE = True
try:
    import httpx
except ImportError:
    _BROWSERBASE_AVAILABLE = False

# Playwright import is optional (only needed when connecting via CDP)
_PLAYWRIGHT_AVAILABLE = True
try:
    from playwright.async_api import async_playwright
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


@dataclass(frozen=True, slots=True)
class CloudSession:
    """Metadata for an active cloud browser session."""

    session_id: str
    connect_url: str
    status: str = "created"
    project_id: str = ""


@dataclass
class CloudBrowserBackend:
    """BrowserBase cloud browser backend.

    Manages remote browser sessions via the BrowserBase REST API.

    Parameters
    ----------
    api_key:
        BrowserBase API key. If empty, the backend is disabled.
    api_url:
        Base URL for the BrowserBase API.
    project_id:
        Optional BrowserBase project ID for session scoping.
    """

    api_key: str = ""
    api_url: str = "https://www.browserbase.com/v1"
    project_id: str = ""
    _active_sessions: dict[str, CloudSession] = field(default_factory=dict, init=False, repr=False)

    @property
    def is_configured(self) -> bool:
        """Return True if the backend has a valid API key."""
        return bool(self.api_key)

    async def connect(self, *, session_label: str = "") -> CloudSession | None:
        """Create a new cloud browser session.

        Returns a ``CloudSession`` with connection details, or ``None`` if
        the backend is not configured or dependencies are missing.
        """
        if not self.is_configured:
            logger.debug("Cloud browser backend not configured (no API key)")
            return None

        if not _BROWSERBASE_AVAILABLE:
            logger.warning("httpx not available; cannot create cloud browser session")
            return None

        headers = {
            "x-bb-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        body: dict[str, Any] = {}
        if self.project_id:
            body["projectId"] = self.project_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{self.api_url}/sessions",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            session_id: str = data.get("id", "")
            connect_url: str = data.get("connectUrl", "")
            if not session_id:
                logger.error("BrowserBase returned no session ID: %s", data)
                return None

            session = CloudSession(
                session_id=session_id,
                connect_url=connect_url,
                status=data.get("status", "created"),
                project_id=data.get("projectId", self.project_id),
            )
            self._active_sessions[session_id] = session
            logger.info(
                "Created cloud browser session %s (label=%s)",
                session_id,
                session_label,
            )
            return session

        except Exception:
            logger.exception("Failed to create cloud browser session")
            return None

    async def disconnect(self, session_id: str) -> bool:
        """Close a cloud browser session.

        Returns True if the session was successfully closed.
        """
        if not self.is_configured or not _BROWSERBASE_AVAILABLE:
            return False

        self._active_sessions.pop(session_id, None)

        headers = {
            "x-bb-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{self.api_url}/sessions/{session_id}/stop",
                    headers=headers,
                )
                resp.raise_for_status()
            logger.info("Closed cloud browser session %s", session_id)
            return True
        except Exception:
            logger.exception("Failed to close cloud session %s", session_id)
            return False

    async def list_sessions(self) -> list[CloudSession]:
        """List active cloud browser sessions from the API.

        Falls back to locally tracked sessions if the API call fails.
        """
        if not self.is_configured or not _BROWSERBASE_AVAILABLE:
            return list(self._active_sessions.values())

        headers = {"x-bb-api-key": self.api_key}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{self.api_url}/sessions",
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

            sessions: list[CloudSession] = []
            items = data if isinstance(data, list) else data.get("sessions", [])
            for item in items:
                sessions.append(
                    CloudSession(
                        session_id=item.get("id", ""),
                        connect_url=item.get("connectUrl", ""),
                        status=item.get("status", "unknown"),
                        project_id=item.get("projectId", ""),
                    )
                )
            return sessions
        except Exception:
            logger.debug("Failed to list cloud sessions, returning local cache")
            return list(self._active_sessions.values())

    async def get_playwright_page(self, session: CloudSession) -> Any:
        """Connect to a cloud session via CDP and return a Playwright Page.

        The caller is responsible for closing the browser/playwright when done.
        Returns ``None`` if Playwright is not available or connection fails.
        """
        if not _PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available for cloud CDP connection")
            return None

        if not session.connect_url:
            logger.error("Cloud session %s has no connect URL", session.session_id)
            return None

        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.connect_over_cdp(session.connect_url)
            contexts = browser.contexts
            if contexts:
                pages = contexts[0].pages
                if pages:
                    return pages[0]
                return await contexts[0].new_page()
            context = await browser.new_context()
            return await context.new_page()
        except Exception:
            logger.exception("Failed to connect to cloud session %s", session.session_id)
            return None
