"""Tests for SkillsBench pytest binary reward runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from agent33.benchmarks.skillsbench.runner import PytestBinaryRewardRunner, PytestResult

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# PytestResult
# ---------------------------------------------------------------------------


class TestPytestResult:
    def test_passed_result(self) -> None:
        result = PytestResult(
            passed=True, returncode=0, stdout="1 passed", stderr="", duration_ms=100.0
        )
        assert result.passed is True
        assert result.returncode == 0
        assert result.duration_ms == 100.0

    def test_failed_result(self) -> None:
        result = PytestResult(
            passed=False, returncode=1, stdout="1 failed", stderr="", duration_ms=200.0
        )
        assert result.passed is False
        assert result.returncode == 1

    def test_timeout_result(self) -> None:
        result = PytestResult(
            passed=False, returncode=-1, stdout="", stderr="Timed out", duration_ms=5000.0
        )
        assert result.passed is False
        assert result.returncode == -1
        assert "Timed out" in result.stderr

    def test_frozen(self) -> None:
        """PytestResult is a frozen dataclass -- attributes cannot be set."""
        result = PytestResult(passed=True, returncode=0, stdout="", stderr="", duration_ms=0.0)
        with pytest.raises(AttributeError):
            result.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PytestBinaryRewardRunner -- construction
# ---------------------------------------------------------------------------


class TestPytestBinaryRewardRunnerInit:
    def test_default_timeout(self) -> None:
        runner = PytestBinaryRewardRunner()
        assert runner.timeout_seconds == 300.0

    def test_custom_timeout(self) -> None:
        runner = PytestBinaryRewardRunner(timeout_seconds=60.0)
        assert runner.timeout_seconds == 60.0

    def test_custom_python_executable(self) -> None:
        runner = PytestBinaryRewardRunner(python_executable="/usr/bin/python3.12")
        assert runner._python_executable == "/usr/bin/python3.12"


# ---------------------------------------------------------------------------
# PytestBinaryRewardRunner.evaluate
# ---------------------------------------------------------------------------


class TestPytestBinaryRewardRunnerEvaluate:
    @pytest.mark.asyncio
    async def test_evaluate_missing_test_file(self, tmp_path: Path) -> None:
        """Missing test file should return failure without spawning subprocess."""
        runner = PytestBinaryRewardRunner()
        result = await runner.evaluate(
            tests_path=tmp_path / "nonexistent" / "test_outputs.py",
            working_dir=tmp_path,
        )
        assert result.passed is False
        assert result.returncode == -1
        assert "not found" in result.stderr

    @pytest.mark.asyncio
    async def test_evaluate_passing_tests(self, tmp_path: Path) -> None:
        """Integration test: run a real pytest that passes."""
        test_file = tmp_path / "test_pass.py"
        test_file.write_text(
            "def test_always_passes():\n    assert True\n",
            encoding="utf-8",
        )
        runner = PytestBinaryRewardRunner(timeout_seconds=30.0)
        result = await runner.evaluate(
            tests_path=test_file,
            working_dir=tmp_path,
        )
        assert result.passed is True
        assert result.returncode == 0
        assert result.duration_ms > 0
        assert "passed" in result.stdout.lower()

    @pytest.mark.asyncio
    async def test_evaluate_failing_tests(self, tmp_path: Path) -> None:
        """Integration test: run a real pytest that fails."""
        test_file = tmp_path / "test_fail.py"
        test_file.write_text(
            "def test_always_fails():\n    assert 1 == 2, 'expected failure'\n",
            encoding="utf-8",
        )
        runner = PytestBinaryRewardRunner(timeout_seconds=30.0)
        result = await runner.evaluate(
            tests_path=test_file,
            working_dir=tmp_path,
        )
        assert result.passed is False
        assert result.returncode == 1
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_evaluate_uses_working_dir(self, tmp_path: Path) -> None:
        """Test that the subprocess runs in the specified working directory."""
        # Create a test that checks for a file in cwd
        data_file = tmp_path / "data.txt"
        data_file.write_text("hello", encoding="utf-8")
        test_file = tmp_path / "test_cwd.py"
        test_file.write_text(
            "from pathlib import Path\n"
            "def test_data_file_exists():\n"
            "    assert Path('data.txt').read_text() == 'hello'\n",
            encoding="utf-8",
        )
        runner = PytestBinaryRewardRunner(timeout_seconds=30.0)
        result = await runner.evaluate(
            tests_path=test_file,
            working_dir=tmp_path,
        )
        assert result.passed is True

    @pytest.mark.asyncio
    async def test_evaluate_timeout(self, tmp_path: Path) -> None:
        """Test that a long-running pytest is killed after timeout."""
        test_file = tmp_path / "test_slow.py"
        test_file.write_text(
            "import time\ndef test_slow():\n    time.sleep(60)\n",
            encoding="utf-8",
        )
        runner = PytestBinaryRewardRunner(timeout_seconds=1.0)
        result = await runner.evaluate(
            tests_path=test_file,
            working_dir=tmp_path,
        )
        assert result.passed is False
        assert result.returncode == -1
        assert "Timed out" in result.stderr

    @pytest.mark.asyncio
    async def test_evaluate_multiple_tests(self, tmp_path: Path) -> None:
        """All tests must pass for binary reward."""
        test_file = tmp_path / "test_multi.py"
        test_file.write_text(
            "def test_one():\n    assert True\n\n"
            "def test_two():\n    assert True\n\n"
            "def test_three():\n    assert True\n",
            encoding="utf-8",
        )
        runner = PytestBinaryRewardRunner(timeout_seconds=30.0)
        result = await runner.evaluate(
            tests_path=test_file,
            working_dir=tmp_path,
        )
        assert result.passed is True
        assert "3 passed" in result.stdout

    @pytest.mark.asyncio
    async def test_evaluate_partial_failure(self, tmp_path: Path) -> None:
        """One failing test out of three should produce a failure."""
        test_file = tmp_path / "test_partial.py"
        test_file.write_text(
            "def test_ok1():\n    assert True\n\n"
            "def test_fail():\n    assert False\n\n"
            "def test_ok2():\n    assert True\n",
            encoding="utf-8",
        )
        runner = PytestBinaryRewardRunner(timeout_seconds=30.0)
        result = await runner.evaluate(
            tests_path=test_file,
            working_dir=tmp_path,
        )
        assert result.passed is False
        assert result.returncode != 0
