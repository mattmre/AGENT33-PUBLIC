"""Tests for CA-013: Artifact Filtering Module."""

from __future__ import annotations

import re
import time

import pytest

from agent33.automation.filters import Artifact, ArtifactFilter


def _make_artifacts() -> list[Artifact]:
    """Build a reusable fixture of diverse artifacts."""
    now = time.time()
    return [
        Artifact(id="1", name="report.py", artifact_type="code", created_at=now),
        Artifact(id="2", name="report.md", artifact_type="doc", created_at=now - 3600),
        Artifact(id="3", name="build-output.tar", artifact_type="archive", created_at=now - 86400),
        Artifact(id="4", name="test_utils.py", artifact_type="code", created_at=now),
        Artifact(id="5", name="notes.txt", artifact_type="doc", created_at=now - 7200),
    ]


class TestArtifactDataclass:
    """Verify Artifact construction and field defaults."""

    def test_required_fields_and_defaults(self) -> None:
        a = Artifact(id="x", name="hello.py")
        assert a.id == "x"
        assert a.name == "hello.py"
        assert a.artifact_type == ""
        assert isinstance(a.created_at, float)
        assert a.metadata == {}

    def test_metadata_isolation_between_instances(self) -> None:
        """Each Artifact must get its own metadata dict, not a shared mutable default."""
        a = Artifact(id="1", name="a")
        b = Artifact(id="2", name="b")
        a.metadata["key"] = "val"
        assert "key" not in b.metadata


class TestIncludeExcludeGlobs:
    """Verify include/exclude glob filtering on artifact names."""

    def test_include_selects_matching_names(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().include(["*.py"]).apply(arts)
        names = [a.name for a in result]
        assert names == ["report.py", "test_utils.py"]

    def test_exclude_removes_matching_names(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().exclude(["*.py"]).apply(arts)
        names = [a.name for a in result]
        assert "report.py" not in names
        assert "test_utils.py" not in names
        assert len(names) == 3

    def test_include_and_exclude_combined(self) -> None:
        """Include *.py then exclude test_*: should keep report.py but not test_utils.py."""
        arts = _make_artifacts()
        result = ArtifactFilter().include(["*.py"]).exclude(["test_*"]).apply(arts)
        names = [a.name for a in result]
        assert names == ["report.py"]

    def test_include_no_matches_returns_empty(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().include(["*.nonexistent"]).apply(arts)
        assert result == []

    def test_exclude_all_returns_empty(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().exclude(["*"]).apply(arts)
        assert result == []


class TestTypeFilter:
    """Verify by_type filtering on artifact_type field."""

    def test_single_type(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().by_type(["doc"]).apply(arts)
        assert all(a.artifact_type == "doc" for a in result)
        assert len(result) == 2

    def test_multiple_types(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().by_type(["code", "archive"]).apply(arts)
        types = {a.artifact_type for a in result}
        assert types == {"code", "archive"}
        assert len(result) == 3

    def test_nonexistent_type_returns_empty(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().by_type(["video"]).apply(arts)
        assert result == []


class TestAgeFilter:
    """Verify by_age filters based on created_at relative to current time."""

    def test_recent_only(self) -> None:
        """max_age=1800 should keep only items created in the last 30 minutes."""
        arts = _make_artifacts()
        result = ArtifactFilter().by_age(1800).apply(arts)
        # arts[0] and arts[3] are created_at=now, the rest are older
        names = {a.name for a in result}
        assert "report.py" in names
        assert "test_utils.py" in names
        # 1-hour-old and older items must be excluded
        assert "report.md" not in names
        assert "build-output.tar" not in names

    def test_large_age_keeps_everything(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().by_age(999_999).apply(arts)
        assert len(result) == len(arts)

    def test_tiny_age_excludes_old_items(self) -> None:
        """max_age=1 should exclude items created more than 1 second ago."""
        now = time.time()
        old = Artifact(id="old", name="old.py", created_at=now - 60)
        fresh = Artifact(id="new", name="new.py", created_at=now)
        result = ArtifactFilter().by_age(1).apply([old, fresh])
        assert len(result) == 1
        assert result[0].id == "new"


class TestRegexFilter:
    """Verify by_regex filtering on artifact name."""

    def test_regex_matches_substring(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().by_regex(r"report").apply(arts)
        names = [a.name for a in result]
        assert names == ["report.py", "report.md"]

    def test_regex_anchored_pattern(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().by_regex(r"^test_").apply(arts)
        assert len(result) == 1
        assert result[0].name == "test_utils.py"

    def test_invalid_regex_raises(self) -> None:
        with pytest.raises(re.error):
            ArtifactFilter().by_regex(r"[invalid")

    def test_regex_timeout_requires_positive_value(self) -> None:
        with pytest.raises(ValueError, match="timeout must be positive"):
            ArtifactFilter().by_regex(r"report", timeout=0)

    def test_regex_timeout_is_enforced_when_regex_package_available(self) -> None:
        pytest.importorskip("regex")
        arts = _make_artifacts()
        result = ArtifactFilter().by_regex(r"report", timeout=0.1).apply(arts)
        names = [a.name for a in result]
        assert names == ["report.py", "report.md"]


class TestPredicateFilter:
    """Verify by_predicate with custom callables."""

    def test_custom_predicate(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().by_predicate(lambda a: len(a.name) <= 10).apply(arts)
        assert all(len(a.name) <= 10 for a in result)
        assert len(result) > 0

    def test_predicate_on_metadata(self) -> None:
        a1 = Artifact(id="1", name="a", metadata={"priority": "high"})
        a2 = Artifact(id="2", name="b", metadata={"priority": "low"})
        a3 = Artifact(id="3", name="c", metadata={})
        result = (
            ArtifactFilter()
            .by_predicate(lambda a: a.metadata.get("priority") == "high")
            .apply([a1, a2, a3])
        )
        assert len(result) == 1
        assert result[0].id == "1"


class TestFilterChaining:
    """Verify that multiple filters compose correctly via method chaining."""

    def test_chained_filters_narrow_results(self) -> None:
        """Chain include + type + predicate: each stage must further narrow the set."""
        arts = _make_artifacts()
        result = (
            ArtifactFilter()
            .include(["*.py", "*.md"])  # report.py, report.md, test_utils.py
            .by_type(["code"])  # report.py, test_utils.py
            .by_predicate(lambda a: "report" in a.name)  # report.py
            .apply(arts)
        )
        assert len(result) == 1
        assert result[0].name == "report.py"

    def test_fluent_api_returns_same_instance(self) -> None:
        f = ArtifactFilter()
        assert f.include(["*"]) is f
        assert f.exclude(["*"]) is f
        assert f.by_type(["x"]) is f
        assert f.by_age(10) is f
        assert f.by_regex(r"x") is f
        assert f.by_predicate(lambda a: True) is f


class TestEdgeCases:
    """Boundary conditions and empty inputs."""

    def test_empty_input_list(self) -> None:
        result = ArtifactFilter().include(["*"]).apply([])
        assert result == []

    def test_no_filters_returns_all(self) -> None:
        arts = _make_artifacts()
        result = ArtifactFilter().apply(arts)
        assert len(result) == len(arts)

    def test_multiple_regex_filters_compose(self) -> None:
        """Regression test: multiple regex filters must compose with AND logic."""
        arts = _make_artifacts()
        result = ArtifactFilter().by_regex(r"\.py$").by_regex(r"^report").apply(arts)
        assert len(result) == 1
        assert result[0].name == "report.py"

    def test_predicate_and_regex_filters_compose(self) -> None:
        """Predicate and regex filters should compose generically, not just regex+regex."""
        arts = _make_artifacts()
        result = (
            ArtifactFilter()
            .by_regex(r"^report")
            .by_predicate(lambda a: a.artifact_type == "doc")
            .apply(arts)
        )
        assert len(result) == 1
        assert result[0].name == "report.md"
