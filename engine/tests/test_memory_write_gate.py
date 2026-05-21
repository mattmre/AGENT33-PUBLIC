from __future__ import annotations

from agent33.memory.write_gate import (
    MemoryReviewState,
    MemoryWriteRequest,
    evaluate_memory_write,
)


def _request(**overrides: object) -> MemoryWriteRequest:
    payload = {
        "content": "The provider supports streaming.",
        "source": "run-1",
        "confidence": 0.9,
        "authority": "observed",
        "evidence_uri": "run://run-1/evidence/1",
        "tenant_id": "tenant-a",
        "scope": "workspace",
    }
    payload.update(overrides)
    return MemoryWriteRequest.model_validate(payload)


def test_memory_write_gate_allows_complete_request() -> None:
    result = evaluate_memory_write(_request())

    assert result.allowed is True
    assert result.missing_requirements == []


def test_memory_write_gate_requires_source_authority_evidence_tenant_and_scope() -> None:
    result = evaluate_memory_write(
        _request(source="", authority="", evidence_uri="", tenant_id="", scope="")
    )

    assert result.allowed is False
    assert result.missing_requirements == [
        "source",
        "authority",
        "evidence_uri",
        "tenant_id",
        "scope",
    ]


def test_memory_write_gate_blocks_low_confidence_without_verified_review() -> None:
    result = evaluate_memory_write(_request(confidence=0.2))

    assert result.allowed is False
    assert result.missing_requirements == ["verified_review_for_low_confidence"]


def test_memory_write_gate_allows_low_confidence_with_verified_review() -> None:
    result = evaluate_memory_write(
        _request(confidence=0.2, review_state=MemoryReviewState.VERIFIED)
    )

    assert result.allowed is True
