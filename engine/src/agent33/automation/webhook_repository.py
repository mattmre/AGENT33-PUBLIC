"""Repository abstraction for webhook registrations.

Provides a protocol-based repository pattern that supports both in-memory
and database-backed implementations for multi-replica safety.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class WebhookRepository(Protocol):
    """Protocol for webhook registration storage."""

    def get_webhook(self, path: str) -> dict[str, Any] | None:
        """Get a webhook registration by path."""
        ...

    def register_webhook(self, path: str, secret: str, workflow_name: str) -> dict[str, Any]:
        """Register a webhook. Returns the registration record."""
        ...

    def unregister_webhook(self, path: str) -> bool:
        """Unregister a webhook. Returns True if found and removed."""
        ...

    def list_webhooks(self) -> list[dict[str, Any]]:
        """List all registered webhooks."""
        ...


class InMemoryWebhookRepository:
    """In-memory implementation preserving current behavior."""

    def __init__(self) -> None:
        self._hooks: dict[str, dict[str, Any]] = {}

    def get_webhook(self, path: str) -> dict[str, Any] | None:
        return self._hooks.get(path)

    def register_webhook(self, path: str, secret: str, workflow_name: str) -> dict[str, Any]:
        record = {
            "path": path,
            "secret": secret,
            "workflow_name": workflow_name,
        }
        self._hooks[path] = record
        return record

    def unregister_webhook(self, path: str) -> bool:
        return self._hooks.pop(path, None) is not None

    def list_webhooks(self) -> list[dict[str, Any]]:
        return list(self._hooks.values())


_repository: WebhookRepository | None = None


def get_webhook_repository() -> WebhookRepository:
    """Get the current webhook repository. Creates in-memory default if not set."""
    global _repository  # noqa: PLW0603
    if _repository is None:
        _repository = InMemoryWebhookRepository()
    return _repository


def set_webhook_repository(repo: WebhookRepository) -> None:
    """Set the webhook repository. Called during app lifespan."""
    global _repository  # noqa: PLW0603
    _repository = repo
