from __future__ import annotations

from agent33.resources.federation import FederatedRegistry, registry_sync_hooks
from agent33.resources.moderation import (
    ModerationQueueItem,
    ModerationStatus,
    prioritize_moderation,
    recommend_moderation_action,
)


def test_registry_sync_hooks_emit_one_event_per_registry() -> None:
    hooks = registry_sync_hooks(
        [
            FederatedRegistry(
                registry_id="core",
                base_url="https://registry.example.test",
            )
        ]
    )

    assert hooks[0].event_type == "registry_sync_requested"
    assert hooks[0].registry_id == "core"
    assert hooks[0].trust_required is True


def test_moderation_queue_prioritizes_pending_reputation() -> None:
    items = [
        ModerationQueueItem(
            resource_id="approved",
            submitter="a",
            reputation=100,
            status=ModerationStatus.APPROVED,
        ),
        ModerationQueueItem(resource_id="low", submitter="b", reputation=1),
        ModerationQueueItem(resource_id="high", submitter="c", reputation=10),
    ]

    assert [item.resource_id for item in prioritize_moderation(items)] == [
        "high",
        "low",
        "approved",
    ]


def test_moderation_recommendation_uses_flags_and_reputation() -> None:
    flagged = ModerationQueueItem(
        resource_id="flagged",
        submitter="a",
        reputation=100,
        flags=["unknown network scope"],
    )
    trusted = ModerationQueueItem(resource_id="trusted", submitter="b", reputation=80)

    assert recommend_moderation_action(flagged).next_action == "manual_review"
    assert recommend_moderation_action(trusted).next_action == "expedite_review"
