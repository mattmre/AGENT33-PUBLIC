"""Tests for SLO configuration fields."""

from __future__ import annotations

import os
from unittest import mock

from agent33.config import Settings


class TestSLOConfigDefaults:
    """Verify SLO threshold fields have correct defaults."""

    def test_availability_target_default(self) -> None:
        s = Settings()
        assert s.slo_availability_target == 0.999

    def test_latency_p99_ms_default(self) -> None:
        s = Settings()
        assert s.slo_latency_p99_ms == 500

    def test_latency_agent_p99_ms_default(self) -> None:
        s = Settings()
        assert s.slo_latency_agent_p99_ms == 10000


class TestSLOConfigOverrides:
    """Verify SLO fields can be overridden via environment variables."""

    def test_availability_target_override(self) -> None:
        with mock.patch.dict(os.environ, {"SLO_AVAILABILITY_TARGET": "0.9999"}):
            s = Settings()
            assert s.slo_availability_target == 0.9999

    def test_latency_p99_ms_override(self) -> None:
        with mock.patch.dict(os.environ, {"SLO_LATENCY_P99_MS": "250"}):
            s = Settings()
            assert s.slo_latency_p99_ms == 250

    def test_latency_agent_p99_ms_override(self) -> None:
        with mock.patch.dict(os.environ, {"SLO_LATENCY_AGENT_P99_MS": "5000"}):
            s = Settings()
            assert s.slo_latency_agent_p99_ms == 5000

    def test_all_slo_fields_overridden(self) -> None:
        env = {
            "SLO_AVAILABILITY_TARGET": "0.995",
            "SLO_LATENCY_P99_MS": "1000",
            "SLO_LATENCY_AGENT_P99_MS": "30000",
        }
        with mock.patch.dict(os.environ, env):
            s = Settings()
            assert s.slo_availability_target == 0.995
            assert s.slo_latency_p99_ms == 1000
            assert s.slo_latency_agent_p99_ms == 30000
