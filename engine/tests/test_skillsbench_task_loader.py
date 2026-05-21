"""Tests for SkillsBench task loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent33.benchmarks.skillsbench.models import TaskFilter
from agent33.benchmarks.skillsbench.task_loader import SkillsBenchTask, SkillsBenchTaskLoader

# ---------------------------------------------------------------------------
# Helpers to build task directory structures on disk
# ---------------------------------------------------------------------------


def _create_task(
    root: Path,
    category: str,
    task_name: str,
    instruction: str = "Do the task.",
    *,
    with_skills: bool = False,
) -> Path:
    """Create a minimal SkillsBench task directory structure."""
    task_dir = root / "tasks" / category / task_name
    task_dir.mkdir(parents=True, exist_ok=True)

    # instruction.md
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")

    # tests/test_outputs.py
    tests_dir = task_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_outputs.py").write_text(
        "def test_output():\n    assert True\n", encoding="utf-8"
    )

    # Optional skills directory
    if with_skills:
        skills_dir = task_dir / "environment" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "example.yaml").write_text(
            "name: example-skill\ndescription: Test skill\n", encoding="utf-8"
        )

    return task_dir


# ---------------------------------------------------------------------------
# SkillsBenchTask
# ---------------------------------------------------------------------------


class TestSkillsBenchTask:
    def test_equality_by_task_id(self) -> None:
        task_a = SkillsBenchTask(
            task_id="math/add",
            category="math",
            instruction="Add numbers",
            skills_dir=None,
            tests_path=Path("/x/tests/test_outputs.py"),
        )
        task_b = SkillsBenchTask(
            task_id="math/add",
            category="math",
            instruction="Different instruction",
            skills_dir=None,
            tests_path=Path("/y/tests/test_outputs.py"),
        )
        assert task_a == task_b

    def test_inequality(self) -> None:
        task_a = SkillsBenchTask(
            task_id="math/add",
            category="math",
            instruction="",
            skills_dir=None,
            tests_path=Path("/x"),
        )
        task_b = SkillsBenchTask(
            task_id="math/subtract",
            category="math",
            instruction="",
            skills_dir=None,
            tests_path=Path("/x"),
        )
        assert task_a != task_b

    def test_hash_consistency(self) -> None:
        task = SkillsBenchTask(
            task_id="science/chem",
            category="science",
            instruction="",
            skills_dir=None,
            tests_path=Path("/x"),
        )
        # Same task_id should produce the same hash
        task2 = SkillsBenchTask(
            task_id="science/chem",
            category="science",
            instruction="other",
            skills_dir=None,
            tests_path=Path("/y"),
        )
        assert hash(task) == hash(task2)

    def test_repr(self) -> None:
        task = SkillsBenchTask(
            task_id="cat/name",
            category="cat",
            instruction="",
            skills_dir=None,
            tests_path=Path("/x"),
        )
        r = repr(task)
        assert "cat/name" in r
        assert "SkillsBenchTask" in r


# ---------------------------------------------------------------------------
# SkillsBenchTaskLoader -- discover_tasks
# ---------------------------------------------------------------------------


class TestSkillsBenchTaskLoaderDiscovery:
    def test_discover_empty_root(self, tmp_path: Path) -> None:
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert tasks == []

    def test_discover_missing_tasks_dir(self, tmp_path: Path) -> None:
        """No tasks/ subdirectory -- should return empty, not crash."""
        loader = SkillsBenchTaskLoader(tmp_path)
        assert loader.discover_tasks() == []

    def test_discover_single_task(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "addition", "Add two numbers.")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_id == "math/addition"
        assert tasks[0].category == "math"
        assert tasks[0].instruction == "Add two numbers."

    def test_discover_multiple_categories(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "add")
        _create_task(tmp_path, "science", "chem")
        _create_task(tmp_path, "security", "vuln")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 3
        # Should be sorted by category then task name
        cats = [t.category for t in tasks]
        assert cats == sorted(cats)

    def test_discover_multiple_tasks_in_category(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "subtract")
        _create_task(tmp_path, "math", "add")
        _create_task(tmp_path, "math", "multiply")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 3
        # Within a category, tasks should be sorted by name
        names = [t.metadata["task_name"] for t in tasks]
        assert names == sorted(names)

    def test_discover_with_skills_dir(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "cat", "task_with_skills", with_skills=True)
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 1
        assert tasks[0].skills_dir is not None
        assert tasks[0].skills_dir.is_dir()

    def test_discover_without_skills_dir(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "cat", "task_no_skills", with_skills=False)
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 1
        assert tasks[0].skills_dir is None

    def test_discover_skips_files_in_tasks_dir(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "add")
        # Add a stray file in tasks/
        (tmp_path / "tasks" / "README.md").write_text("ignore me", encoding="utf-8")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 1

    def test_discover_skips_invalid_task(self, tmp_path: Path) -> None:
        """A task directory missing instruction.md should be skipped."""
        task_dir = tmp_path / "tasks" / "math" / "broken"
        task_dir.mkdir(parents=True)
        # No instruction.md -- should be skipped silently
        _create_task(tmp_path, "math", "valid")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 1
        assert tasks[0].task_id == "math/valid"


# ---------------------------------------------------------------------------
# SkillsBenchTaskLoader -- discover_tasks with TaskFilter
# ---------------------------------------------------------------------------


class TestSkillsBenchTaskLoaderFilter:
    def test_filter_by_category(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "add")
        _create_task(tmp_path, "science", "chem")
        _create_task(tmp_path, "security", "vuln")
        loader = SkillsBenchTaskLoader(tmp_path)
        f = TaskFilter(categories=["math"])
        tasks = loader.discover_tasks(task_filter=f)
        assert len(tasks) == 1
        assert tasks[0].category == "math"

    def test_filter_exclude_category(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "add")
        _create_task(tmp_path, "science", "chem")
        loader = SkillsBenchTaskLoader(tmp_path)
        f = TaskFilter(exclude_categories=["science"])
        tasks = loader.discover_tasks(task_filter=f)
        assert len(tasks) == 1
        assert tasks[0].category == "math"

    def test_filter_by_task_id(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "add")
        _create_task(tmp_path, "math", "subtract")
        _create_task(tmp_path, "science", "chem")
        loader = SkillsBenchTaskLoader(tmp_path)
        f = TaskFilter(task_ids=["math/subtract", "science/chem"])
        tasks = loader.discover_tasks(task_filter=f)
        assert len(tasks) == 2
        ids = {t.task_id for t in tasks}
        assert ids == {"math/subtract", "science/chem"}

    def test_filter_max_tasks(self, tmp_path: Path) -> None:
        for i in range(10):
            _create_task(tmp_path, "math", f"task_{i:02d}")
        loader = SkillsBenchTaskLoader(tmp_path)
        f = TaskFilter(max_tasks=3)
        tasks = loader.discover_tasks(task_filter=f)
        assert len(tasks) == 3


# ---------------------------------------------------------------------------
# SkillsBenchTaskLoader -- load_task
# ---------------------------------------------------------------------------


class TestSkillsBenchTaskLoaderLoadTask:
    def test_load_specific_task(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "addition", "Add numbers.")
        loader = SkillsBenchTaskLoader(tmp_path)
        task = loader.load_task("math/addition")
        assert task.task_id == "math/addition"
        assert task.instruction == "Add numbers."

    def test_load_task_not_found(self, tmp_path: Path) -> None:
        (tmp_path / "tasks").mkdir(parents=True)
        loader = SkillsBenchTaskLoader(tmp_path)
        with pytest.raises(FileNotFoundError, match="Task directory not found"):
            loader.load_task("nonexistent/task")

    def test_load_task_invalid_format(self, tmp_path: Path) -> None:
        loader = SkillsBenchTaskLoader(tmp_path)
        with pytest.raises(ValueError, match="category/task_name"):
            loader.load_task("no-slash")

    def test_load_task_missing_instruction(self, tmp_path: Path) -> None:
        """Task directory exists but has no instruction.md."""
        task_dir = tmp_path / "tasks" / "math" / "broken"
        task_dir.mkdir(parents=True)
        tests_dir = task_dir / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_outputs.py").write_text("pass", encoding="utf-8")
        loader = SkillsBenchTaskLoader(tmp_path)
        with pytest.raises(FileNotFoundError, match="instruction.md"):
            loader.load_task("math/broken")

    def test_load_task_missing_test_file(self, tmp_path: Path) -> None:
        """Task directory exists with instruction but no tests/test_outputs.py."""
        task_dir = tmp_path / "tasks" / "math" / "broken"
        task_dir.mkdir(parents=True)
        (task_dir / "instruction.md").write_text("Do something", encoding="utf-8")
        loader = SkillsBenchTaskLoader(tmp_path)
        with pytest.raises(FileNotFoundError, match="test_outputs.py"):
            loader.load_task("math/broken")


# ---------------------------------------------------------------------------
# SkillsBenchTaskLoader -- list_categories
# ---------------------------------------------------------------------------


class TestSkillsBenchTaskLoaderCategories:
    def test_list_categories_empty(self, tmp_path: Path) -> None:
        loader = SkillsBenchTaskLoader(tmp_path)
        assert loader.list_categories() == []

    def test_list_categories(self, tmp_path: Path) -> None:
        _create_task(tmp_path, "math", "add")
        _create_task(tmp_path, "science", "chem")
        _create_task(tmp_path, "security", "vuln")
        loader = SkillsBenchTaskLoader(tmp_path)
        cats = loader.list_categories()
        assert cats == ["math", "science", "security"]

    def test_tasks_dir_property(self, tmp_path: Path) -> None:
        loader = SkillsBenchTaskLoader(tmp_path)
        assert loader.tasks_dir == tmp_path / "tasks"

    def test_root_property(self, tmp_path: Path) -> None:
        loader = SkillsBenchTaskLoader(tmp_path)
        assert loader.root == tmp_path


# ---------------------------------------------------------------------------
# Helper for flat-layout task directories (upstream SkillsBench format)
# ---------------------------------------------------------------------------


def _create_flat_task(
    root: Path,
    task_name: str,
    instruction: str = "Do the task.",
    *,
    category: str | None = None,
    with_skills: bool = False,
) -> Path:
    """Create a flat-layout SkillsBench task directory.

    Flat layout: ``tasks/{task_name}/instruction.md`` with optional ``task.toml``.
    If *category* is provided, a ``task.toml`` with ``[task] category = ...`` is
    written; otherwise no ``task.toml`` is created.
    """
    task_dir = root / "tasks" / task_name
    task_dir.mkdir(parents=True, exist_ok=True)

    # instruction.md
    (task_dir / "instruction.md").write_text(instruction, encoding="utf-8")

    # tests/test_outputs.py
    tests_dir = task_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_outputs.py").write_text(
        "def test_output():\n    assert True\n", encoding="utf-8"
    )

    # Optional task.toml with category
    if category is not None:
        toml_content = f'[task]\ncategory = "{category}"\n'
        (task_dir / "task.toml").write_text(toml_content, encoding="utf-8")

    # Optional skills directory
    if with_skills:
        skills_dir = task_dir / "environment" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "example.yaml").write_text(
            "name: example-skill\ndescription: Test skill\n", encoding="utf-8"
        )

    return task_dir


# ---------------------------------------------------------------------------
# SkillsBenchTaskLoader -- flat layout discovery (upstream SkillsBench)
# ---------------------------------------------------------------------------


class TestFlatLayoutDiscovery:
    """Tests for flat-layout (upstream SkillsBench) task loading."""

    def test_discover_flat_with_category_from_toml(self, tmp_path: Path) -> None:
        """Flat layout discovery reads category from task.toml."""
        _create_flat_task(tmp_path, "numpy_stats", category="scientific_computing")
        _create_flat_task(tmp_path, "port_scan", category="security")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 2
        by_id = {t.task_id: t for t in tasks}
        assert "scientific_computing/numpy_stats" in by_id
        assert "security/port_scan" in by_id
        assert by_id["scientific_computing/numpy_stats"].category == "scientific_computing"
        assert by_id["security/port_scan"].category == "security"

    def test_discover_flat_missing_toml_defaults_to_unknown(self, tmp_path: Path) -> None:
        """Tasks without task.toml get category 'unknown'."""
        _create_flat_task(tmp_path, "mystery_task")  # No category kwarg -> no task.toml
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 1
        assert tasks[0].category == "unknown"
        assert tasks[0].task_id == "unknown/mystery_task"

    def test_load_task_flat_by_compound_id(self, tmp_path: Path) -> None:
        """load_task with category/task_name works in flat layout."""
        _create_flat_task(tmp_path, "numpy_stats", category="scientific_computing")
        loader = SkillsBenchTaskLoader(tmp_path)
        task = loader.load_task("scientific_computing/numpy_stats")
        assert task.task_id == "scientific_computing/numpy_stats"
        assert task.category == "scientific_computing"
        assert task.instruction == "Do the task."

    def test_load_task_flat_by_bare_name(self, tmp_path: Path) -> None:
        """load_task with bare task_name reads category from task.toml."""
        _create_flat_task(tmp_path, "port_scan", category="security")
        loader = SkillsBenchTaskLoader(tmp_path)
        task = loader.load_task("port_scan")
        assert task.task_id == "security/port_scan"
        assert task.category == "security"

    def test_load_task_flat_bare_name_no_toml(self, tmp_path: Path) -> None:
        """load_task with bare name and no task.toml defaults to 'unknown'."""
        _create_flat_task(tmp_path, "mystery_task")
        loader = SkillsBenchTaskLoader(tmp_path)
        task = loader.load_task("mystery_task")
        assert task.task_id == "unknown/mystery_task"
        assert task.category == "unknown"

    def test_list_categories_flat(self, tmp_path: Path) -> None:
        """list_categories scans task.toml files for unique categories."""
        _create_flat_task(tmp_path, "task_a", category="math")
        _create_flat_task(tmp_path, "task_b", category="science")
        _create_flat_task(tmp_path, "task_c", category="math")  # duplicate
        _create_flat_task(tmp_path, "task_d")  # no toml -> "unknown"
        loader = SkillsBenchTaskLoader(tmp_path)
        cats = loader.list_categories()
        assert cats == ["math", "science", "unknown"]

    def test_flat_filter_by_category(self, tmp_path: Path) -> None:
        """Category filtering works in flat layout."""
        _create_flat_task(tmp_path, "add", category="math")
        _create_flat_task(tmp_path, "chem", category="science")
        _create_flat_task(tmp_path, "vuln", category="security")
        loader = SkillsBenchTaskLoader(tmp_path)
        f = TaskFilter(categories=["math"])
        tasks = loader.discover_tasks(task_filter=f)
        assert len(tasks) == 1
        assert tasks[0].category == "math"

    def test_flat_filter_exclude_category(self, tmp_path: Path) -> None:
        """Exclude category filtering works in flat layout."""
        _create_flat_task(tmp_path, "add", category="math")
        _create_flat_task(tmp_path, "chem", category="science")
        loader = SkillsBenchTaskLoader(tmp_path)
        f = TaskFilter(exclude_categories=["science"])
        tasks = loader.discover_tasks(task_filter=f)
        assert len(tasks) == 1
        assert tasks[0].category == "math"

    def test_flat_filter_max_tasks(self, tmp_path: Path) -> None:
        """max_tasks filtering works in flat layout."""
        for i in range(10):
            _create_flat_task(tmp_path, f"task_{i:02d}", category="math")
        loader = SkillsBenchTaskLoader(tmp_path)
        f = TaskFilter(max_tasks=3)
        tasks = loader.discover_tasks(task_filter=f)
        assert len(tasks) == 3

    def test_flat_with_skills_directory(self, tmp_path: Path) -> None:
        """Skills directory detected in flat layout."""
        _create_flat_task(tmp_path, "skilled_task", category="tools", with_skills=True)
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 1
        assert tasks[0].skills_dir is not None
        assert tasks[0].skills_dir.is_dir()

    def test_flat_without_skills_directory(self, tmp_path: Path) -> None:
        """No skills directory yields None in flat layout."""
        _create_flat_task(tmp_path, "plain_task", category="math")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 1
        assert tasks[0].skills_dir is None

    def test_nested_layout_still_works(self, tmp_path: Path) -> None:
        """Existing nested layout is unaffected by the flat-layout additions."""
        _create_task(tmp_path, "math", "add", "Add numbers.")
        _create_task(tmp_path, "science", "chem", "Do chemistry.")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        assert len(tasks) == 2
        ids = {t.task_id for t in tasks}
        assert ids == {"math/add", "science/chem"}
        # Also verify load_task still works in nested mode
        task = loader.load_task("math/add")
        assert task.instruction == "Add numbers."

    def test_flat_load_task_not_found(self, tmp_path: Path) -> None:
        """load_task raises FileNotFoundError for missing task in flat layout."""
        _create_flat_task(tmp_path, "exists", category="math")
        loader = SkillsBenchTaskLoader(tmp_path)
        with pytest.raises(FileNotFoundError, match="Task directory not found"):
            loader.load_task("math/nonexistent")

    def test_flat_load_task_bare_name_not_found(self, tmp_path: Path) -> None:
        """load_task raises FileNotFoundError for missing bare name in flat layout."""
        _create_flat_task(tmp_path, "exists", category="math")
        loader = SkillsBenchTaskLoader(tmp_path)
        with pytest.raises(FileNotFoundError, match="Task directory not found"):
            loader.load_task("nonexistent")

    def test_flat_sorted_output(self, tmp_path: Path) -> None:
        """Flat layout discovery returns tasks sorted by category/task_name."""
        _create_flat_task(tmp_path, "z_task", category="alpha")
        _create_flat_task(tmp_path, "a_task", category="zeta")
        _create_flat_task(tmp_path, "m_task", category="alpha")
        loader = SkillsBenchTaskLoader(tmp_path)
        tasks = loader.discover_tasks()
        ids = [t.task_id for t in tasks]
        assert ids == sorted(ids)

    def test_flat_filter_by_task_id(self, tmp_path: Path) -> None:
        """Task ID filtering works in flat layout."""
        _create_flat_task(tmp_path, "add", category="math")
        _create_flat_task(tmp_path, "subtract", category="math")
        _create_flat_task(tmp_path, "chem", category="science")
        loader = SkillsBenchTaskLoader(tmp_path)
        f = TaskFilter(task_ids=["math/subtract", "science/chem"])
        tasks = loader.discover_tasks(task_filter=f)
        assert len(tasks) == 2
        ids = {t.task_id for t in tasks}
        assert ids == {"math/subtract", "science/chem"}

    def test_auto_detect_flat_via_task_toml_only(self, tmp_path: Path) -> None:
        """Auto-detection triggers on task.toml even without instruction.md."""
        task_dir = tmp_path / "tasks" / "partial_task"
        task_dir.mkdir(parents=True)
        (task_dir / "task.toml").write_text('[task]\ncategory = "test"\n', encoding="utf-8")
        # No instruction.md -> _is_flat_layout should still return True
        loader = SkillsBenchTaskLoader(tmp_path)
        assert loader._is_flat_layout() is True
