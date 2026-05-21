"""Tests for WebhookRepository abstraction (P3.4)."""

from __future__ import annotations

from agent33.automation.webhook_repository import (
    InMemoryWebhookRepository,
    WebhookRepository,
    get_webhook_repository,
    set_webhook_repository,
)


class TestInMemoryWebhookRepository:
    """InMemoryWebhookRepository CRUD operations."""

    def test_register_webhook_returns_record(self) -> None:
        repo = InMemoryWebhookRepository()
        record = repo.register_webhook("/hooks/deploy", "secret123", "deploy-wf")
        assert record["path"] == "/hooks/deploy"
        assert record["secret"] == "secret123"
        assert record["workflow_name"] == "deploy-wf"

    def test_get_webhook_returns_none_when_missing(self) -> None:
        repo = InMemoryWebhookRepository()
        assert repo.get_webhook("/hooks/nope") is None

    def test_get_webhook_returns_registered_hook(self) -> None:
        repo = InMemoryWebhookRepository()
        repo.register_webhook("/hooks/ci", "sec", "ci-wf")
        hook = repo.get_webhook("/hooks/ci")
        assert hook is not None
        assert hook["workflow_name"] == "ci-wf"

    def test_register_overwrites_existing(self) -> None:
        repo = InMemoryWebhookRepository()
        repo.register_webhook("/hooks/deploy", "old-secret", "old-wf")
        repo.register_webhook("/hooks/deploy", "new-secret", "new-wf")
        hook = repo.get_webhook("/hooks/deploy")
        assert hook is not None
        assert hook["secret"] == "new-secret"
        assert hook["workflow_name"] == "new-wf"

    def test_unregister_returns_true_when_found(self) -> None:
        repo = InMemoryWebhookRepository()
        repo.register_webhook("/hooks/deploy", "sec", "wf")
        assert repo.unregister_webhook("/hooks/deploy") is True
        assert repo.get_webhook("/hooks/deploy") is None

    def test_unregister_returns_false_when_missing(self) -> None:
        repo = InMemoryWebhookRepository()
        assert repo.unregister_webhook("/hooks/ghost") is False

    def test_list_webhooks_empty(self) -> None:
        repo = InMemoryWebhookRepository()
        assert repo.list_webhooks() == []

    def test_list_webhooks_returns_all(self) -> None:
        repo = InMemoryWebhookRepository()
        repo.register_webhook("/hooks/a", "s1", "wf-a")
        repo.register_webhook("/hooks/b", "s2", "wf-b")
        hooks = repo.list_webhooks()
        assert len(hooks) == 2
        paths = {h["path"] for h in hooks}
        assert paths == {"/hooks/a", "/hooks/b"}


class TestWebhookRepositoryProtocol:
    """Verify InMemoryWebhookRepository satisfies the WebhookRepository protocol."""

    def test_inmemory_is_webhook_repository(self) -> None:
        repo = InMemoryWebhookRepository()
        assert isinstance(repo, WebhookRepository)


class TestWebhookRepositoryAccessors:
    """Test module-level get/set accessor pattern."""

    def test_get_webhook_repository_creates_default(self) -> None:
        import agent33.automation.webhook_repository as mod

        original = mod._repository
        try:
            mod._repository = None
            repo = get_webhook_repository()
            assert isinstance(repo, InMemoryWebhookRepository)
        finally:
            mod._repository = original

    def test_set_webhook_repository_overrides(self) -> None:
        import agent33.automation.webhook_repository as mod

        original = mod._repository
        try:
            custom = InMemoryWebhookRepository()
            set_webhook_repository(custom)
            assert get_webhook_repository() is custom
        finally:
            mod._repository = original

    def test_get_returns_same_instance(self) -> None:
        import agent33.automation.webhook_repository as mod

        original = mod._repository
        try:
            mod._repository = None
            repo1 = get_webhook_repository()
            repo2 = get_webhook_repository()
            assert repo1 is repo2
        finally:
            mod._repository = original
