from __future__ import annotations

from agent33.policy.shards import (
    ActivePolicySet,
    PolicyShard,
    PolicyShardKind,
    default_policy_shards,
)


def test_default_policy_shards_cover_tool_and_evidence_gates() -> None:
    shards = default_policy_shards()

    assert {shard.kind for shard in shards} == {
        PolicyShardKind.TOOL_USE,
        PolicyShardKind.EVIDENCE_GATE,
    }
    assert shards[0].version == "1.0.0"


def test_active_policy_set_lists_enabled_kinds_only() -> None:
    policy_set = ActivePolicySet(
        run_id="run-1",
        shards=[
            PolicyShard(id="p1", version="1", kind=PolicyShardKind.NETWORK),
            PolicyShard(id="p2", version="1", kind=PolicyShardKind.MEMORY_WRITE, enabled=False),
        ],
    )

    assert policy_set.active_kinds() == [PolicyShardKind.NETWORK]
