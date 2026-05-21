"""Tests for the intake pipeline, validators, and intake API endpoints (Sprint 2).

Test plan:
  TC-I1   HIGH confidence asset → auto-advanced to VALIDATED
  TC-I2   MEDIUM confidence asset → stays CANDIDATE, has review_required in metadata
  TC-I3   LOW confidence asset → stays CANDIDATE, has review_required + quarantine
  TC-I4   batch_submit with mixed confidence levels → correct status distribution
  TC-I5   batch_submit with one invalid asset → error captured, others succeed
  TC-I6   validate_schema with missing required fields → error strings returned
  TC-I7   validate_schema with valid payload → empty error list
  TC-I8   validate_source_uri with valid and invalid URIs
  TC-I9   validate_confidence with valid and invalid values
  TC-I10  get_pipeline_stats returns correct status counts per tenant
  TC-I11  API POST /v1/ingestion/intake returns correct shape (201)
  TC-I12  API GET /v1/ingestion/intake/stats returns correct shape
  TC-I13  API intake auth: missing write scope returns 401/403
  TC-I14  API stats auth: missing read scope returns 401/403
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import ingestion as ingestion_mod
from agent33.ingestion.intake import IntakePipeline
from agent33.ingestion.models import CandidateStatus, ConfidenceLevel
from agent33.ingestion.service import IngestionService
from agent33.ingestion.validators import CandidateValidator
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_TENANT = "tenant-intake-test"


def _asset(
    name: str,
    *,
    confidence: str = "low",
    uri: str = "https://a.com/x",
    asset_type: str = "skill",
) -> dict[str, str]:
    """Build a minimal asset payload dict."""
    return {"name": name, "asset_type": asset_type, "source_uri": uri, "confidence": confidence}


# Reusable high/medium/low fixtures so individual tests stay readable.
_HIGH = _asset("h-skill", confidence="high", uri="https://a.com/h")
_MED = _asset("m-skill", confidence="medium", uri="https://a.com/m")
_LOW = _asset("l-skill", confidence="low", uri="https://a.com/l")


@pytest.fixture()
def service() -> IngestionService:
    return IngestionService()


@pytest.fixture()
def pipeline(service: IngestionService) -> IntakePipeline:
    return IntakePipeline(service)


@pytest.fixture()
def validator() -> CandidateValidator:
    return CandidateValidator()


def _client(scopes: list[str], *, tenant_id: str = _TENANT) -> TestClient:
    token = create_access_token("intake-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def reset_ingestion_state() -> None:
    """Isolate each test with a fresh service and pipeline on the module level."""
    saved_service = ingestion_mod._service
    saved_pipeline = ingestion_mod._intake_pipeline

    fresh_service = IngestionService()
    fresh_pipeline = IntakePipeline(fresh_service)
    ingestion_mod._service = fresh_service
    ingestion_mod._intake_pipeline = fresh_pipeline

    had_svc = hasattr(app.state, "ingestion_service")
    saved_svc_state = getattr(app.state, "ingestion_service", None)
    had_pipe = hasattr(app.state, "intake_pipeline")
    saved_pipe_state = getattr(app.state, "intake_pipeline", None)

    if had_svc:
        delattr(app.state, "ingestion_service")
    if had_pipe:
        delattr(app.state, "intake_pipeline")

    yield

    ingestion_mod._service = saved_service
    ingestion_mod._intake_pipeline = saved_pipeline

    if had_svc:
        app.state.ingestion_service = saved_svc_state
    elif hasattr(app.state, "ingestion_service"):
        delattr(app.state, "ingestion_service")

    if had_pipe:
        app.state.intake_pipeline = saved_pipe_state
    elif hasattr(app.state, "intake_pipeline"):
        delattr(app.state, "intake_pipeline")


# ---------------------------------------------------------------------------
# TC-I1: HIGH confidence → auto-advanced to VALIDATED
# ---------------------------------------------------------------------------


class TestHighConfidenceRouting:
    """TC-I1: A HIGH confidence asset is automatically advanced to VALIDATED."""

    def test_high_confidence_status_is_validated(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_HIGH.copy(), source="test", tenant_id=_TENANT)
        assert asset.status == CandidateStatus.VALIDATED

    def test_high_confidence_validated_at_is_set(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_HIGH.copy(), source="test", tenant_id=_TENANT)
        assert asset.validated_at is not None

    def test_high_confidence_no_review_required_flag(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_HIGH.copy(), source="test", tenant_id=_TENANT)
        assert asset.metadata.get("review_required") is None

    def test_high_confidence_no_quarantine_flag(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_HIGH.copy(), source="test", tenant_id=_TENANT)
        assert asset.metadata.get("quarantine") is None


# ---------------------------------------------------------------------------
# TC-I2: MEDIUM confidence → stays CANDIDATE with review_required
# ---------------------------------------------------------------------------


class TestMediumConfidenceRouting:
    """TC-I2: MEDIUM confidence stays at CANDIDATE with review_required in metadata."""

    def test_medium_confidence_status_is_candidate(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_MED.copy(), source="test", tenant_id=_TENANT)
        assert asset.status == CandidateStatus.CANDIDATE

    def test_medium_confidence_review_required_true(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_MED.copy(), source="test", tenant_id=_TENANT)
        assert asset.metadata.get("review_required") is True

    def test_medium_confidence_no_quarantine(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_MED.copy(), source="test", tenant_id=_TENANT)
        assert asset.metadata.get("quarantine") is None


# ---------------------------------------------------------------------------
# TC-I3: LOW confidence → stays CANDIDATE with review_required + quarantine
# ---------------------------------------------------------------------------


class TestLowConfidenceRouting:
    """TC-I3: LOW confidence stays at CANDIDATE with both review_required and quarantine."""

    def test_low_confidence_status_is_candidate(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_LOW.copy(), source="test", tenant_id=_TENANT)
        assert asset.status == CandidateStatus.CANDIDATE

    def test_low_confidence_review_required_true(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_LOW.copy(), source="test", tenant_id=_TENANT)
        assert asset.metadata.get("review_required") is True

    def test_low_confidence_quarantine_true(self, pipeline: IntakePipeline) -> None:
        asset = pipeline.submit(_LOW.copy(), source="test", tenant_id=_TENANT)
        assert asset.metadata.get("quarantine") is True

    def test_default_confidence_is_low_behavior(self, pipeline: IntakePipeline) -> None:
        """Omitting confidence should default to LOW routing behavior."""
        payload = {"name": "default-skill", "asset_type": "skill", "source_uri": "https://a.com"}
        asset = pipeline.submit(payload, source="test", tenant_id=_TENANT)
        assert asset.status == CandidateStatus.CANDIDATE
        assert asset.metadata.get("quarantine") is True


# ---------------------------------------------------------------------------
# TC-I4: batch_submit with mixed confidence levels
# ---------------------------------------------------------------------------


class TestBatchSubmitMixed:
    """TC-I4: batch_submit with HIGH/MEDIUM/LOW → correct distribution."""

    def test_batch_returns_correct_count(self, pipeline: IntakePipeline) -> None:
        assets = [_HIGH.copy(), _MED.copy(), _LOW.copy()]
        results = pipeline.batch_submit(assets, source="batch", tenant_id=_TENANT)
        assert len(results) == 3

    def test_batch_high_is_validated(self, pipeline: IntakePipeline) -> None:
        assets = [
            _asset("bh", confidence="high", uri="https://a.com/bh"),
            _asset("bm", confidence="medium", uri="https://a.com/bm"),
            _asset("bl", confidence="low", uri="https://a.com/bl"),
        ]
        results = pipeline.batch_submit(assets, source="batch", tenant_id=_TENANT)
        validated = [r for r in results if r.status == CandidateStatus.VALIDATED]
        candidates = [r for r in results if r.status == CandidateStatus.CANDIDATE]
        assert len(validated) == 1
        assert len(candidates) == 2

    def test_batch_medium_has_review_required(self, pipeline: IntakePipeline) -> None:
        assets = [_MED.copy()]
        results = pipeline.batch_submit(assets, source="batch", tenant_id=_TENANT)
        assert results[0].metadata.get("review_required") is True
        assert results[0].metadata.get("quarantine") is None

    def test_batch_low_has_quarantine(self, pipeline: IntakePipeline) -> None:
        assets = [_LOW.copy()]
        results = pipeline.batch_submit(assets, source="batch", tenant_id=_TENANT)
        assert results[0].metadata.get("quarantine") is True


# ---------------------------------------------------------------------------
# TC-I5: batch_submit with one invalid asset → error captured, others succeed
# ---------------------------------------------------------------------------


class TestBatchSubmitWithError:
    """TC-I5: One invalid asset does not abort the batch; error is captured."""

    def test_batch_length_preserved_on_error(self, pipeline: IntakePipeline) -> None:
        # Empty name triggers ValidationError so we can test the error-capture path.
        bad: dict[str, str] = {
            "name": "",
            "asset_type": "skill",
            "source_uri": "https://a.com/bad",
            "confidence": "low",
        }
        assets = [
            _asset("good-skill", confidence="low", uri="https://a.com/g"),
            bad,
            _asset("another-good", confidence="medium", uri="https://a.com/a"),
        ]
        results = pipeline.batch_submit(assets, source="test", tenant_id=_TENANT)
        assert len(results) == 3

    def test_good_assets_succeed_despite_one_error(self, pipeline: IntakePipeline) -> None:
        assets = [
            _asset("ok-1", confidence="medium", uri="https://a.com/ok1"),
            {"name": "", "source_uri": "https://a.com/bad", "confidence": "INVALID_LEVEL"},
            _asset("ok-2", confidence="high", uri="https://a.com/ok2", asset_type="tool"),
        ]
        results = pipeline.batch_submit(assets, source="test", tenant_id=_TENANT)
        names = [r.name for r in results]
        assert "ok-1" in names
        assert "ok-2" in names

    def test_failed_asset_has_intake_error_in_metadata(self, pipeline: IntakePipeline) -> None:
        """Verify the error asset record carries an intake_error key."""
        bad: dict[str, str] = {
            "name": "",
            "asset_type": "skill",
            "source_uri": "https://a.com/bad",
            "confidence": "low",
        }
        assets = [_asset("good", confidence="low", uri="https://a.com/g"), bad]
        results = pipeline.batch_submit(assets, source="test", tenant_id=_TENANT)
        error_assets = [r for r in results if "intake_error" in r.metadata]
        assert len(error_assets) == 1

    def test_failed_asset_status_is_candidate(self, pipeline: IntakePipeline) -> None:
        """Error placeholder records should be created as CANDIDATE (safe default)."""
        bad: dict[str, str] = {
            "name": "",
            "asset_type": "skill",
            "source_uri": "https://a.com/bad",
            "confidence": "low",
        }
        results = pipeline.batch_submit([bad], source="test", tenant_id=_TENANT)
        assert results[0].status == CandidateStatus.CANDIDATE
        assert "intake_error" in results[0].metadata


# ---------------------------------------------------------------------------
# TC-I6: validate_schema with missing required fields
# ---------------------------------------------------------------------------


class TestValidateSchemaInvalid:
    """TC-I6: validate_schema returns meaningful error strings for bad payloads."""

    def test_empty_dict_has_errors(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema({})
        assert len(errors) > 0

    def test_missing_name_reported(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {"source_uri": "https://example.com", "confidence": "low", "tenant_id": "t1"}
        )
        assert any("name" in e for e in errors)

    def test_missing_source_uri_reported(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {"name": "skill", "confidence": "low", "tenant_id": "t1"}
        )
        assert any("source_uri" in e for e in errors)

    def test_missing_confidence_reported(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {"name": "skill", "source_uri": "https://example.com", "tenant_id": "t1"}
        )
        assert any("confidence" in e for e in errors)

    def test_missing_tenant_id_reported(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {"name": "skill", "source_uri": "https://example.com", "confidence": "low"}
        )
        assert any("tenant_id" in e for e in errors)

    def test_invalid_confidence_value_reported(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {
                "name": "skill",
                "source_uri": "https://example.com",
                "confidence": "super-high",
                "tenant_id": "t1",
            }
        )
        assert any("confidence" in e for e in errors)

    def test_empty_name_reported(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {
                "name": "   ",
                "source_uri": "https://example.com",
                "confidence": "low",
                "tenant_id": "t1",
            }
        )
        assert any("name" in e for e in errors)

    def test_empty_asset_type_when_present_reported(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {
                "name": "skill",
                "source_uri": "https://example.com",
                "confidence": "low",
                "tenant_id": "t1",
                "asset_type": "   ",
            }
        )
        assert any("asset_type" in e for e in errors)

    def test_multiple_errors_returned_together(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema({})
        assert len(errors) >= 3  # name + source_uri + confidence (+ tenant_id)


# ---------------------------------------------------------------------------
# TC-I7: validate_schema with valid payload → empty error list
# ---------------------------------------------------------------------------


class TestValidateSchemaValid:
    """TC-I7: A fully valid payload produces an empty error list."""

    def test_minimal_valid_payload(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {
                "name": "my-skill",
                "source_uri": "https://example.com/skill",
                "confidence": "medium",
                "tenant_id": "tenant-1",
            }
        )
        assert errors == []

    def test_full_valid_payload(self, validator: CandidateValidator) -> None:
        errors = validator.validate_schema(
            {
                "name": "full-skill",
                "source_uri": "skill://registry/full-skill",
                "confidence": "high",
                "tenant_id": "tenant-2",
                "asset_type": "workflow",
                "metadata": {"version": "1.0"},
            }
        )
        assert errors == []

    def test_all_confidence_levels_are_valid(self, validator: CandidateValidator) -> None:
        for level in ("high", "medium", "low"):
            errors = validator.validate_schema(
                {
                    "name": f"skill-{level}",
                    "source_uri": "https://example.com",
                    "confidence": level,
                    "tenant_id": "t1",
                }
            )
            assert errors == [], f"Expected no errors for confidence={level!r}, got {errors}"


# ---------------------------------------------------------------------------
# TC-I8: validate_source_uri
# ---------------------------------------------------------------------------


class TestValidateSourceUri:
    """TC-I8: validate_source_uri returns True for known schemes and False otherwise."""

    @pytest.mark.parametrize(
        "uri",
        [
            "http://example.com/skill",
            "https://example.com/skill",
            "file:///local/path/skill.yaml",
            "skill://registry/my-skill",
            "agent://orchestrator/agent-1",
        ],
    )
    def test_valid_uris(self, validator: CandidateValidator, uri: str) -> None:
        assert validator.validate_source_uri(uri) is True

    @pytest.mark.parametrize(
        "uri",
        [
            "",
            "   ",
            "ftp://example.com/skill",
            "mailto:user@example.com",
            "no-scheme-at-all",
            "://missing-scheme",
        ],
    )
    def test_invalid_uris(self, validator: CandidateValidator, uri: str) -> None:
        assert validator.validate_source_uri(uri) is False


# ---------------------------------------------------------------------------
# TC-I9: validate_confidence
# ---------------------------------------------------------------------------


class TestValidateConfidence:
    """TC-I9: validate_confidence returns ConfidenceLevel or None."""

    def test_high_returns_enum(self, validator: CandidateValidator) -> None:
        assert validator.validate_confidence("high") == ConfidenceLevel.HIGH

    def test_medium_returns_enum(self, validator: CandidateValidator) -> None:
        assert validator.validate_confidence("medium") == ConfidenceLevel.MEDIUM

    def test_low_returns_enum(self, validator: CandidateValidator) -> None:
        assert validator.validate_confidence("low") == ConfidenceLevel.LOW

    def test_uppercase_is_normalised(self, validator: CandidateValidator) -> None:
        assert validator.validate_confidence("HIGH") == ConfidenceLevel.HIGH

    def test_mixed_case_is_normalised(self, validator: CandidateValidator) -> None:
        assert validator.validate_confidence("Medium") == ConfidenceLevel.MEDIUM

    def test_unknown_value_returns_none(self, validator: CandidateValidator) -> None:
        assert validator.validate_confidence("extreme") is None

    def test_empty_string_returns_none(self, validator: CandidateValidator) -> None:
        assert validator.validate_confidence("") is None


# ---------------------------------------------------------------------------
# TC-I10: get_pipeline_stats returns correct status counts
# ---------------------------------------------------------------------------


class TestGetPipelineStats:
    """TC-I10: get_pipeline_stats returns accurate per-status counts."""

    def test_empty_service_all_zeros(self, pipeline: IntakePipeline) -> None:
        stats = pipeline.get_pipeline_stats(_TENANT)
        assert stats == {
            "candidate": 0,
            "validated": 0,
            "published": 0,
            "revoked": 0,
        }

    def test_stats_reflect_submitted_assets(self, pipeline: IntakePipeline) -> None:
        pipeline.submit(_HIGH.copy(), source="test", tenant_id=_TENANT)
        pipeline.submit(_MED.copy(), source="test", tenant_id=_TENANT)
        pipeline.submit(_LOW.copy(), source="test", tenant_id=_TENANT)
        stats = pipeline.get_pipeline_stats(_TENANT)
        assert stats["validated"] == 1
        assert stats["candidate"] == 2

    def test_stats_scoped_to_tenant(self, pipeline: IntakePipeline) -> None:
        pipeline.submit(_LOW.copy(), source="test", tenant_id=_TENANT)
        pipeline.submit(_HIGH.copy(), source="test", tenant_id="other-tenant-xyz")
        stats = pipeline.get_pipeline_stats(_TENANT)
        assert stats["candidate"] == 1
        assert stats["validated"] == 0

    def test_stats_keys_include_all_statuses(self, pipeline: IntakePipeline) -> None:
        stats = pipeline.get_pipeline_stats(_TENANT)
        for status in CandidateStatus:
            assert status.value in stats


# ---------------------------------------------------------------------------
# TC-I11: API POST /v1/ingestion/intake
# ---------------------------------------------------------------------------


def _make_intake_body(
    assets: list[dict[str, object]],
    *,
    source: str = "api-test",
    tenant_id: str = _TENANT,
) -> dict[str, object]:
    return {"assets": assets, "source": source, "tenant_id": tenant_id}


class TestIntakeAPIPost:
    """TC-I11: POST /v1/ingestion/intake returns correct shape."""

    @pytest.fixture()
    def writer(self) -> TestClient:
        return _client(["ingestion:read", "ingestion:write"])

    def test_returns_201(self, writer: TestClient) -> None:
        resp = writer.post("/v1/ingestion/intake", json=_make_intake_body([_MED.copy()]))
        assert resp.status_code == 201

    def test_response_has_assets_key(self, writer: TestClient) -> None:
        resp = writer.post("/v1/ingestion/intake", json=_make_intake_body([_LOW.copy()]))
        data = resp.json()
        assert "assets" in data
        assert isinstance(data["assets"], list)

    def test_response_has_stats_key(self, writer: TestClient) -> None:
        resp = writer.post("/v1/ingestion/intake", json=_make_intake_body([_LOW.copy()]))
        data = resp.json()
        assert "stats" in data
        assert isinstance(data["stats"], dict)

    def test_high_confidence_asset_is_validated_in_response(self, writer: TestClient) -> None:
        resp = writer.post("/v1/ingestion/intake", json=_make_intake_body([_HIGH.copy()]))
        assets = resp.json()["assets"]
        assert len(assets) == 1
        assert assets[0]["status"] == "validated"

    def test_batch_count_reflected_in_response(self, writer: TestClient) -> None:
        assets = [_LOW.copy(), _MED.copy(), _HIGH.copy()]
        resp = writer.post("/v1/ingestion/intake", json=_make_intake_body(assets))
        assert resp.status_code == 201
        assert len(resp.json()["assets"]) == 3

    def test_stats_counts_reflect_batch(self, writer: TestClient) -> None:
        assets = [_MED.copy(), _HIGH.copy()]
        resp = writer.post("/v1/ingestion/intake", json=_make_intake_body(assets))
        stats = resp.json()["stats"]
        assert stats["candidate"] == 1
        assert stats["validated"] == 1


# ---------------------------------------------------------------------------
# TC-I12: API GET /v1/ingestion/intake/stats
# ---------------------------------------------------------------------------


class TestIntakeAPIStats:
    """TC-I12: GET /v1/ingestion/intake/stats returns correct shape."""

    @pytest.fixture()
    def reader(self) -> TestClient:
        return _client(["ingestion:read"])

    @pytest.fixture()
    def writer(self) -> TestClient:
        return _client(["ingestion:read", "ingestion:write"])

    def test_stats_returns_200(self, reader: TestClient) -> None:
        resp = reader.get(f"/v1/ingestion/intake/stats?tenant_id={_TENANT}")
        assert resp.status_code == 200

    def test_stats_response_has_all_status_keys(self, reader: TestClient) -> None:
        resp = reader.get(f"/v1/ingestion/intake/stats?tenant_id={_TENANT}")
        data = resp.json()
        for status in CandidateStatus:
            assert status.value in data

    def test_stats_reflect_prior_intake(self, writer: TestClient, reader: TestClient) -> None:
        writer.post("/v1/ingestion/intake", json=_make_intake_body([_HIGH.copy()]))
        resp = reader.get(f"/v1/ingestion/intake/stats?tenant_id={_TENANT}")
        data = resp.json()
        assert data["validated"] == 1
        assert data["candidate"] == 0


# ---------------------------------------------------------------------------
# TC-I13/TC-I14: Auth enforcement on intake endpoints
# ---------------------------------------------------------------------------


class TestIntakeAuthEnforcement:
    """TC-I13/TC-I14: Intake endpoints enforce required scopes."""

    @pytest.fixture()
    def no_scope(self) -> TestClient:
        return _client([])

    @pytest.fixture()
    def reader_only(self) -> TestClient:
        return _client(["ingestion:read"])

    def test_post_intake_without_write_scope_rejected(self, reader_only: TestClient) -> None:
        body = _make_intake_body([_LOW.copy()])
        resp = reader_only.post("/v1/ingestion/intake", json=body)
        assert resp.status_code in (401, 403)

    def test_post_intake_without_any_scope_rejected(self, no_scope: TestClient) -> None:
        body = _make_intake_body([_LOW.copy()])
        resp = no_scope.post("/v1/ingestion/intake", json=body)
        assert resp.status_code in (401, 403)

    def test_get_stats_without_read_scope_rejected(self, no_scope: TestClient) -> None:
        resp = no_scope.get(f"/v1/ingestion/intake/stats?tenant_id={_TENANT}")
        assert resp.status_code in (401, 403)

    def test_get_stats_with_read_scope_succeeds(self) -> None:
        reader = _client(["ingestion:read"])
        resp = reader.get(f"/v1/ingestion/intake/stats?tenant_id={_TENANT}")
        assert resp.status_code == 200
