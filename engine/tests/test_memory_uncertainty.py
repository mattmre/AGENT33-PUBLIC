from __future__ import annotations

from agent33.memory.uncertainty import MemoryTruthLedger, MemoryTruthRecord, MemoryTruthState


def test_memory_truth_ledger_filters_by_state() -> None:
    ledger = MemoryTruthLedger()
    ledger.record(MemoryTruthRecord(memory_id="m1", state=MemoryTruthState.VERIFIED))
    ledger.record(MemoryTruthRecord(memory_id="m2", state=MemoryTruthState.DISPUTED))

    records = ledger.list_records(state=MemoryTruthState.DISPUTED)

    assert [record.memory_id for record in records] == ["m2"]


def test_memory_truth_ledger_finds_contradictions_for_related_memory() -> None:
    ledger = MemoryTruthLedger()
    ledger.record(
        MemoryTruthRecord(
            memory_id="m1",
            state=MemoryTruthState.CONTRADICTED,
            related_memory_ids=["m2"],
            evidence_uri="run://evidence/1",
        )
    )

    contradictions = ledger.contradictions_for("m2")

    assert len(contradictions) == 1
    assert contradictions[0].memory_id == "m1"
