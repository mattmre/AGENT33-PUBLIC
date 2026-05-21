"""Tests for POST-3.4 seed packs.

Validates each of the 5 seed packs under engine/packs/:
1. PACK.yaml exists and has all required fields (name, version, description,
   author, skills with non-empty list)
2. Every skill path referenced in PACK.yaml maps to an existing SKILL.md
3. The real `agent33 packs validate` CLI command passes for each pack,
   exercising injection scanning and Pydantic schema validation

These are behavioral tests, not file-existence stubs. The validate command
actually parses the PACK.yaml, runs injection scanning on prompt_addenda and
tool_config, and validates via PackManifest.model_validate().
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from agent33.cli.main import app
from agent33.skills.loader import parse_frontmatter

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_PACKS_DIR = Path(__file__).parent.parent / "packs"

_SEED_PACKS = [
    "web-research",
    "code-review",
    "meeting-notes",
    "document-summarizer",
    "developer-assistant",
]

_REQUIRED_PACK_FIELDS = ("name", "version", "description", "author", "skills")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_pack_yaml(pack_name: str) -> dict[str, Any]:
    """Load and parse a PACK.yaml for the given seed pack."""
    pack_yaml = _PACKS_DIR / pack_name / "PACK.yaml"
    raw = pack_yaml.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    assert isinstance(data, dict), f"{pack_yaml} must be a YAML mapping"
    return data


def _skill_dir(pack_name: str, skill_path: str) -> Path:
    """Resolve a skill path entry to an absolute directory."""
    return _PACKS_DIR / pack_name / skill_path


# ---------------------------------------------------------------------------
# Parametrized: PACK.yaml structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack_name", _SEED_PACKS)
class TestPackYamlStructure:
    """Each seed pack's PACK.yaml must have required fields and valid structure."""

    def test_pack_yaml_exists(self, pack_name: str) -> None:
        """PACK.yaml file is present in the pack directory."""
        pack_yaml = _PACKS_DIR / pack_name / "PACK.yaml"
        assert pack_yaml.is_file(), f"PACK.yaml missing for pack '{pack_name}'"

    def test_required_fields_present(self, pack_name: str) -> None:
        """PACK.yaml contains all required top-level fields."""
        data = _load_pack_yaml(pack_name)
        missing = [f for f in _REQUIRED_PACK_FIELDS if f not in data]
        assert not missing, f"Pack '{pack_name}' is missing required fields: {missing}"

    def test_name_matches_directory(self, pack_name: str) -> None:
        """The name field in PACK.yaml matches the directory name."""
        data = _load_pack_yaml(pack_name)
        assert data["name"] == pack_name, (
            f"Pack name '{data['name']}' does not match directory '{pack_name}'"
        )

    def test_version_is_semver(self, pack_name: str) -> None:
        """The version field follows MAJOR.MINOR.PATCH semver format."""
        data = _load_pack_yaml(pack_name)
        version = data["version"]
        # Pydantic validator uses ^\d+\.\d+\.\d+$ — replicate it here
        assert re.match(r"^\d+\.\d+\.\d+$", str(version)), (
            f"Pack '{pack_name}' version '{version}' is not valid semver"
        )

    def test_skills_list_non_empty(self, pack_name: str) -> None:
        """The skills list contains at least one entry."""
        data = _load_pack_yaml(pack_name)
        skills = data.get("skills", [])
        assert isinstance(skills, list) and len(skills) >= 1, (
            f"Pack '{pack_name}' must have at least one skill"
        )

    def test_each_skill_entry_has_name_and_path(self, pack_name: str) -> None:
        """Every skill entry in the skills list has a non-empty name and path."""
        data = _load_pack_yaml(pack_name)
        for i, skill in enumerate(data.get("skills", [])):
            assert isinstance(skill, dict), f"Pack '{pack_name}' skill[{i}] must be a mapping"
            assert skill.get("name"), f"Pack '{pack_name}' skill[{i}] is missing 'name'"
            assert skill.get("path"), f"Pack '{pack_name}' skill[{i}] is missing 'path'"

    def test_description_non_empty(self, pack_name: str) -> None:
        """The description field is a non-empty string."""
        data = _load_pack_yaml(pack_name)
        desc = data.get("description", "")
        assert isinstance(desc, str) and desc.strip(), (
            f"Pack '{pack_name}' description must be a non-empty string"
        )

    def test_author_non_empty(self, pack_name: str) -> None:
        """The author field is a non-empty string."""
        data = _load_pack_yaml(pack_name)
        author = data.get("author", "")
        assert isinstance(author, str) and author.strip(), (
            f"Pack '{pack_name}' author must be a non-empty string"
        )


# ---------------------------------------------------------------------------
# Parametrized: skill files exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack_name", _SEED_PACKS)
class TestSkillFilesExist:
    """Every skill path referenced in PACK.yaml must have a SKILL.md file."""

    def test_all_referenced_skill_files_exist(self, pack_name: str) -> None:
        """Each skill path in PACK.yaml resolves to a SKILL.md file on disk."""
        data = _load_pack_yaml(pack_name)
        skills = data.get("skills", [])
        missing: list[str] = []
        for skill in skills:
            skill_path = skill.get("path", "")
            skill_md = _skill_dir(pack_name, skill_path) / "SKILL.md"
            if not skill_md.is_file():
                missing.append(str(skill_md))
        assert not missing, f"Pack '{pack_name}' has missing SKILL.md files:\n" + "\n".join(
            f"  {p}" for p in missing
        )

    def test_skill_md_has_frontmatter(self, pack_name: str) -> None:
        """Each SKILL.md starts with YAML frontmatter delimiters."""
        data = _load_pack_yaml(pack_name)
        for skill in data.get("skills", []):
            skill_md = _skill_dir(pack_name, skill["path"]) / "SKILL.md"
            assert skill_md.is_file(), f"{skill_md} does not exist"
            content = skill_md.read_text(encoding="utf-8")
            assert content.startswith("---"), (
                f"SKILL.md for '{skill['name']}' in pack '{pack_name}' "
                f"must start with --- frontmatter delimiter"
            )

    def test_skill_md_frontmatter_has_name_and_description(self, pack_name: str) -> None:
        """Each SKILL.md frontmatter contains at minimum a name and description."""
        data = _load_pack_yaml(pack_name)
        for skill in data.get("skills", []):
            skill_md = _skill_dir(pack_name, skill["path"]) / "SKILL.md"
            content = skill_md.read_text(encoding="utf-8")
            metadata, body = parse_frontmatter(content)
            assert metadata.get("name"), (
                f"SKILL.md for '{skill['name']}' in pack '{pack_name}' "
                f"frontmatter is missing 'name'"
            )
            assert metadata["name"] == skill["name"], (
                f"SKILL.md name {metadata['name']!r} does not match "
                f"manifest entry {skill['name']!r}"
            )
            assert metadata.get("description"), (
                f"SKILL.md for '{skill['name']}' in pack '{pack_name}' "
                f"frontmatter is missing 'description'"
            )
            # Body must be non-trivial (the actual skill instructions)
            assert len(body.strip()) >= 100, (
                f"SKILL.md for '{skill['name']}' in pack '{pack_name}' "
                f"has suspiciously short body ({len(body.strip())} chars); "
                f"skill instructions must be substantive"
            )


# ---------------------------------------------------------------------------
# Parametrized: real CLI validate command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pack_name", _SEED_PACKS)
class TestCLIValidateCommand:
    """Each seed pack must pass the real `agent33 packs validate` command.

    This exercises:
    - YAML parsing (malformed YAML would fail here)
    - Injection scanning on prompt_addenda and tool_config
    - PackManifest.model_validate() Pydantic schema validation
    - Output indicates validation passed
    """

    def test_validate_passes_default_output(self, pack_name: str) -> None:
        """agent33 packs validate exits 0 and reports 'Validation passed'."""
        pack_dir = str(_PACKS_DIR / pack_name)
        runner = CliRunner()
        result = runner.invoke(app, ["packs", "validate", pack_dir])
        assert result.exit_code == 0, (
            f"validate failed for '{pack_name}' (exit {result.exit_code}):\n{result.output}"
        )
        assert "Validation passed" in result.output, (
            f"Expected 'Validation passed' in output for '{pack_name}':\n{result.output}"
        )

    def test_validate_reports_correct_skill_count(self, pack_name: str) -> None:
        """Validate output reports the number of skills defined in PACK.yaml."""
        data = _load_pack_yaml(pack_name)
        expected_count = len(data.get("skills", []))

        pack_dir = str(_PACKS_DIR / pack_name)
        runner = CliRunner()
        result = runner.invoke(app, ["packs", "validate", pack_dir])
        assert result.exit_code == 0, f"validate failed for '{pack_name}':\n{result.output}"
        assert re.search(rf"\b{expected_count}\b.*skill", result.output), (
            f"Expected '{expected_count} skill(s)' in validate output for '{pack_name}':\n"
            f"{result.output}"
        )

    def test_validate_json_output_is_valid(self, pack_name: str) -> None:
        """--json flag produces valid JSON with validation: passed."""
        pack_dir = str(_PACKS_DIR / pack_name)
        runner = CliRunner()
        result = runner.invoke(app, ["packs", "validate", "--json", pack_dir])
        assert result.exit_code == 0, (
            f"validate --json failed for '{pack_name}' (exit {result.exit_code}):\n{result.output}"
        )
        try:
            payload = json.loads(result.output)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"validate --json output is not valid JSON for '{pack_name}': {exc}\n"
                f"Output: {result.output!r}"
            )
        assert payload.get("validation") == "passed", (
            f"JSON output for '{pack_name}' does not have validation=passed: {payload}"
        )
        assert payload["pack"]["name"] == pack_name, (
            f"JSON output pack name mismatch for '{pack_name}': {payload}"
        )

    def test_validate_plain_output_is_parseable(self, pack_name: str) -> None:
        """--plain flag produces key=value output parseable as a mapping."""
        pack_dir = str(_PACKS_DIR / pack_name)
        runner = CliRunner()
        result = runner.invoke(app, ["packs", "validate", "--plain", pack_dir])
        assert result.exit_code == 0, (
            f"validate --plain failed for '{pack_name}' (exit {result.exit_code}):\n"
            f"{result.output}"
        )
        # Plain output uses key=value lines; we expect at minimum name and validation
        lines = result.output.strip().splitlines()
        pairs = {}
        for line in lines:
            if "=" in line:
                k, _, v = line.partition("=")
                pairs[k.strip()] = v.strip()
        assert pairs.get("validation") == "passed", (
            f"Plain output for '{pack_name}' does not have validation=passed: {pairs}"
        )
        assert pairs.get("name") == pack_name, (
            f"Plain output name mismatch for '{pack_name}': {pairs}"
        )


# ---------------------------------------------------------------------------
# Individual pack-specific behavioral checks
# ---------------------------------------------------------------------------


class TestWebResearchPack:
    """web-research pack has the correct skills and tool config."""

    def test_has_three_skills(self) -> None:
        """web-research defines exactly 3 skills."""
        data = _load_pack_yaml("web-research")
        assert len(data["skills"]) == 3

    def test_skill_names(self) -> None:
        """web-research skills are search-web, summarize-results, extract-facts."""
        data = _load_pack_yaml("web-research")
        names = [s["name"] for s in data["skills"]]
        assert names == ["search-web", "summarize-results", "extract-facts"]

    def test_web_fetch_tool_config(self) -> None:
        """web-research configures web_fetch in tool_config."""
        data = _load_pack_yaml("web-research")
        assert "web_fetch" in data.get("tool_config", {}), (
            "web-research must configure web_fetch in tool_config"
        )
        assert data["tool_config"]["web_fetch"].get("enabled") is True


class TestCodeReviewPack:
    """code-review pack has security and file_ops / shell tool config."""

    def test_has_three_skills(self) -> None:
        """code-review defines exactly 3 skills."""
        data = _load_pack_yaml("code-review")
        assert len(data["skills"]) == 3

    def test_skill_names(self) -> None:
        """code-review skills are review-diff, check-security, suggest-improvements."""
        data = _load_pack_yaml("code-review")
        names = [s["name"] for s in data["skills"]]
        assert names == ["review-diff", "check-security", "suggest-improvements"]

    def test_file_ops_and_shell_enabled(self) -> None:
        """code-review enables file_ops and shell in tool_config."""
        data = _load_pack_yaml("code-review")
        tool_config = data.get("tool_config", {})
        assert "file_ops" in tool_config, "code-review must configure file_ops"
        assert "shell" in tool_config, "code-review must configure shell"


class TestMeetingNotesPack:
    """meeting-notes pack has correct skills and structured-output addenda."""

    def test_has_three_skills(self) -> None:
        """meeting-notes defines exactly 3 skills."""
        data = _load_pack_yaml("meeting-notes")
        assert len(data["skills"]) == 3

    def test_skill_names(self) -> None:
        """meeting-notes skills: extract-action-items, summarize-transcript, identify-decisions."""
        data = _load_pack_yaml("meeting-notes")
        names = [s["name"] for s in data["skills"]]
        assert names == [
            "extract-action-items",
            "summarize-transcript",
            "identify-decisions",
        ]

    def test_prompt_addenda_mentions_structured_output(self) -> None:
        """meeting-notes addenda instruct the agent to produce structured output."""
        data = _load_pack_yaml("meeting-notes")
        addenda_text = " ".join(data.get("prompt_addenda", []))
        # The plan requires structured output with attendees, decisions, action items
        assert "structured" in addenda_text.lower() or "action item" in addenda_text.lower(), (
            "meeting-notes prompt_addenda must mention structured output or action items"
        )


class TestDocumentSummarizerPack:
    """document-summarizer pack has hierarchical summary addenda and file_ops."""

    def test_has_three_skills(self) -> None:
        """document-summarizer defines exactly 3 skills."""
        data = _load_pack_yaml("document-summarizer")
        assert len(data["skills"]) == 3

    def test_skill_names(self) -> None:
        """document-summarizer has correct skill names in order."""
        data = _load_pack_yaml("document-summarizer")
        names = [s["name"] for s in data["skills"]]
        assert names == [
            "chunk-and-summarize",
            "extract-key-points",
            "generate-abstract",
        ]

    def test_file_ops_enabled(self) -> None:
        """document-summarizer enables file_ops in tool_config."""
        data = _load_pack_yaml("document-summarizer")
        assert "file_ops" in data.get("tool_config", {}), (
            "document-summarizer must configure file_ops in tool_config"
        )

    def test_prompt_addenda_mentions_accuracy(self) -> None:
        """document-summarizer addenda emphasize technical accuracy."""
        data = _load_pack_yaml("document-summarizer")
        addenda_text = " ".join(data.get("prompt_addenda", []))
        assert "accuracy" in addenda_text.lower() or "accurate" in addenda_text.lower(), (
            "document-summarizer prompt_addenda must mention technical accuracy"
        )


class TestDeveloperAssistantPack:
    """developer-assistant pack has 4 skills and shell / file_ops tools."""

    def test_has_four_skills(self) -> None:
        """developer-assistant defines exactly 4 skills."""
        data = _load_pack_yaml("developer-assistant")
        assert len(data["skills"]) == 4

    def test_skill_names(self) -> None:
        """developer-assistant skills are run-tests, lint-code, git-workflow, explain-error."""
        data = _load_pack_yaml("developer-assistant")
        names = [s["name"] for s in data["skills"]]
        assert names == ["run-tests", "lint-code", "git-workflow", "explain-error"]

    def test_shell_and_file_ops_enabled(self) -> None:
        """developer-assistant enables both shell and file_ops in tool_config."""
        data = _load_pack_yaml("developer-assistant")
        tool_config = data.get("tool_config", {})
        assert "shell" in tool_config, "developer-assistant must configure shell"
        assert "file_ops" in tool_config, "developer-assistant must configure file_ops"

    def test_prompt_addenda_mentions_show_commands(self) -> None:
        """developer-assistant addenda instruct showing commands before running."""
        data = _load_pack_yaml("developer-assistant")
        addenda_text = " ".join(data.get("prompt_addenda", []))
        assert "command" in addenda_text.lower(), (
            "developer-assistant prompt_addenda must mention showing commands"
        )
