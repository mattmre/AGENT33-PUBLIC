"""Webhook trigger -- registers HTTP paths and validates HMAC-SHA256 signatures."""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import logging
from typing import TYPE_CHECKING, Any

from agent33.automation.webhook_repository import get_webhook_repository

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent33.automation.webhook_repository import WebhookRepository

logger = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class WebhookRegistration:
    """A registered webhook binding a URL path to a workflow."""

    path: str
    secret: str
    workflow_name: str


class WebhookTrigger:
    """Manages webhook registrations and dispatches incoming payloads.

    Registrations are persisted via a :class:`WebhookRepository`. If no
    repository is provided, the module-level default is used.

    When :meth:`trigger` is called the associated workflow callback is invoked
    with ``(workflow_name, payload)``.
    """

    def __init__(
        self,
        on_trigger: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
        *,
        repository: WebhookRepository | None = None,
    ) -> None:
        self._hooks: dict[str, WebhookRegistration] = {}
        self._on_trigger = on_trigger
        self._repository = repository

    @property
    def _repo(self) -> WebhookRepository:
        if self._repository is not None:
            return self._repository
        return get_webhook_repository()

    def register(self, path: str, secret: str, workflow_name: str) -> None:
        """Register a webhook path that triggers a workflow.

        Parameters
        ----------
        path:
            URL path segment (e.g. ``"/hooks/deploy"``).
        secret:
            Shared secret used for HMAC-SHA256 validation.
        workflow_name:
            Name of the workflow to execute when triggered.
        """
        self._hooks[path] = WebhookRegistration(
            path=path, secret=secret, workflow_name=workflow_name
        )
        self._repo.register_webhook(path, secret, workflow_name)
        logger.info("Registered webhook %s -> workflow %s", path, workflow_name)

    # -- validation -----------------------------------------------------------

    @staticmethod
    def validate_hmac(payload: bytes, signature: str, secret: str) -> bool:
        """Validate an HMAC-SHA256 signature for the given payload.

        Parameters
        ----------
        payload:
            Raw request body bytes.
        signature:
            Hex-encoded HMAC-SHA256 signature to verify.
        secret:
            Shared secret key.

        Returns
        -------
        bool:
            True if the signature is valid.
        """
        expected = hmac.new(
            secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    # -- trigger --------------------------------------------------------------

    async def trigger(self, path: str, payload: dict[str, Any]) -> Any:
        """Dispatch a webhook event to the associated workflow.

        Parameters
        ----------
        path:
            The URL path that was hit.
        payload:
            Parsed JSON body from the request.

        Returns
        -------
        The result of the workflow callback, or None if no callback is set.

        Raises
        ------
        KeyError:
            If no webhook is registered for the given path.
        """
        registration = self._hooks.get(path)
        if registration is None:
            raise KeyError(f"No webhook registered for path: {path}")

        logger.info("Webhook triggered on %s -> workflow %s", path, registration.workflow_name)

        if self._on_trigger is not None:
            return await self._on_trigger(registration.workflow_name, payload)
        return None
