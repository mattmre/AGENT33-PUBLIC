"""Session spawn service: template-based subagent session creation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from agent33.sessions.models import OperatorSession
    from agent33.sessions.service import OperatorSessionService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SessionSpawnTemplate(BaseModel):
    """Template for spawning a child session."""

    template_id: str
    name: str
    agent_name: str = ""
    purpose_template: str = ""
    model_override: str = ""
    effort_override: str = ""


class SpawnRequest(BaseModel):
    """Request to spawn a child session."""

    parent_session_id: str
    template_id: str = ""
    agent_name: str = ""
    purpose: str = ""
    model_override: str = ""
    effort_override: str = ""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SessionSpawnService:
    """Create child sessions from templates or ad-hoc parameters."""

    def __init__(
        self,
        session_service: OperatorSessionService,
        templates_dir: str = "",
    ) -> None:
        self._session_service = session_service
        self._templates_dir = templates_dir
        self._templates: dict[str, SessionSpawnTemplate] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        """Discover spawn templates from the templates directory."""
        if not self._templates_dir:
            return
        templates_path = Path(self._templates_dir)
        if not templates_path.is_dir():
            logger.debug("spawn_templates_dir_not_found path=%s", self._templates_dir)
            return
        for fp in sorted(templates_path.glob("*.json")):
            try:
                raw = json.loads(fp.read_text(encoding="utf-8"))
                template = SessionSpawnTemplate.model_validate(raw)
                self._templates[template.template_id] = template
                logger.debug("spawn_template_loaded id=%s", template.template_id)
            except Exception:
                logger.warning("spawn_template_load_failed file=%s", fp.name, exc_info=True)

    def list_templates(self) -> list[SessionSpawnTemplate]:
        """Return all available spawn templates."""
        return list(self._templates.values())

    async def spawn(
        self,
        request: SpawnRequest,
        tenant_id: str = "",
    ) -> OperatorSession:
        """Spawn a child session linked to the parent.

        Merges template defaults with request overrides. The child session's
        ``parent_session_id`` is set to the parent, and agent/model/effort
        metadata is stored in the session context.

        Raises:
            KeyError: If the parent session or template is not found.
            ValueError: If the parent session is not active or suspended.
        """
        # Validate parent exists
        parent = await self._session_service.get_session(request.parent_session_id)
        if parent is None:
            raise KeyError(f"Parent session {request.parent_session_id} not found")

        # Resolve template if specified
        template: SessionSpawnTemplate | None = None
        if request.template_id:
            template = self._templates.get(request.template_id)
            if template is None:
                raise KeyError(f"Spawn template '{request.template_id}' not found")

        # Merge: request overrides template defaults
        agent_name = request.agent_name or (template.agent_name if template else "")
        purpose = request.purpose or (template.purpose_template if template else "")
        model_override = request.model_override or (template.model_override if template else "")
        effort_override = request.effort_override or (template.effort_override if template else "")

        context = {
            "agent_name": agent_name,
            "parent_session_id": request.parent_session_id,
        }
        if model_override:
            context["model_override"] = model_override
        if effort_override:
            context["effort_override"] = effort_override
        if request.template_id:
            context["spawn_template_id"] = request.template_id

        child = await self._session_service.start_session(
            purpose=purpose,
            context=context,
            tenant_id=tenant_id,
        )
        # Set the parent_session_id on the child session
        child.parent_session_id = request.parent_session_id
        self._session_service.storage.save_session(child)

        logger.info(
            "session_spawned parent=%s child=%s agent=%s",
            request.parent_session_id,
            child.session_id,
            agent_name,
        )
        return child
