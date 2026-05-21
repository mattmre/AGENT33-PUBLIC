from __future__ import annotations

from agent33.memory.retrieval_audit import (
    RetrievalAuditLog,
    RetrievalAuditRecord,
    RetrievalUsefulness,
)


def test_retrieval_audit_log_lists_records_for_run() -> None:
    log = RetrievalAuditLog()
    log.record(
        RetrievalAuditRecord(
            run_id="run-1",
            item_id="memory-1",
            item_type="memory",
            usefulness=RetrievalUsefulness.HELPFUL,
        )
    )
    log.record(RetrievalAuditRecord(run_id="run-2", item_id="resource-1", item_type="resource"))

    records = log.list_for_run("run-1")

    assert len(records) == 1
    assert records[0].item_id == "memory-1"
    assert records[0].usefulness == RetrievalUsefulness.HELPFUL
