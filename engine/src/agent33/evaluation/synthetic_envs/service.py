"""Deterministic synthetic environment generation service."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import yaml

from agent33.evaluation.synthetic_envs.models import (
    SyntheticEnvironment,
    SyntheticEnvironmentBundle,
    SyntheticTaskPrompt,
    SyntheticToolContract,
    SyntheticVerificationQuery,
    SyntheticWorkflowCatalogEntry,
)
from agent33.workflows.definition import StepAction, WorkflowDefinition, WorkflowStep

logger = logging.getLogger(__name__)

_ACTION_TOOL_MAP: dict[StepAction, str] = {
    StepAction.RUN_COMMAND: "shell",
    StepAction.HTTP_REQUEST: "web_fetch",
    StepAction.TRANSFORM: "file_ops",
    StepAction.VALIDATE: "file_ops",
    StepAction.EXECUTE_CODE: "shell",
    StepAction.ROUTE: "search",
}


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class SyntheticEnvironmentService:
    """Generate DB-backed synthetic evaluation environments from workflows."""

    def __init__(
        self,
        workflow_dir: str | Path = "workflow-definitions",
        tool_dir: str | Path = "tool-definitions",
        max_saved_bundles: int = 100,
        persistence_path: str | Path | None = None,
    ) -> None:
        self._workflow_dir = Path(workflow_dir)
        self._tool_dir = Path(tool_dir)
        self._max_saved_bundles = max_saved_bundles
        self._persistence_path = Path(persistence_path) if persistence_path else None
        self._bundles: dict[str, SyntheticEnvironmentBundle] = {}
        self._bundle_order: list[str] = []
        self._load_persisted_bundles()

    def list_workflows(self) -> list[SyntheticWorkflowCatalogEntry]:
        """Discover workflow templates available for generation."""
        entries: list[SyntheticWorkflowCatalogEntry] = []
        for path in self._iter_workflow_files():
            workflow = WorkflowDefinition.load_from_file(path)
            entries.append(
                SyntheticWorkflowCatalogEntry(
                    workflow_name=workflow.name,
                    workflow_version=workflow.version,
                    description=workflow.description or "",
                    step_count=len(workflow.steps),
                    tags=list(workflow.metadata.tags),
                    inferred_tool_ids=self._infer_tool_ids(workflow.steps),
                )
            )
        return entries

    def generate_bundle(
        self,
        workflow_names: list[str] | None = None,
        variations_per_workflow: int = 1,
    ) -> SyntheticEnvironmentBundle:
        """Generate one or more synthetic environment variants."""
        if variations_per_workflow < 1:
            raise ValueError("variations_per_workflow must be at least 1")

        available = {entry.workflow_name: entry for entry in self.list_workflows()}
        if not available:
            raise ValueError("No workflow definitions available for synthetic generation")

        selected_names = workflow_names or sorted(available)
        unknown = [name for name in selected_names if name not in available]
        if unknown:
            raise ValueError(f"Unknown workflow templates: {', '.join(sorted(unknown))}")

        environments: list[SyntheticEnvironment] = []
        for workflow_name in selected_names:
            workflow = self._load_workflow(workflow_name)
            for variant_index in range(1, variations_per_workflow + 1):
                environment = self._build_environment(workflow, variant_index)
                self._validate_environment(environment)
                environments.append(environment)

        bundle = SyntheticEnvironmentBundle(
            source_workflows=list(selected_names),
            environments=environments,
        )
        self._store_bundle(bundle)
        logger.info(
            "synthetic_environment_bundle_generated bundle_id=%s environments=%d",
            bundle.bundle_id,
            len(bundle.environments),
        )
        return bundle

    def get_bundle(self, bundle_id: str) -> SyntheticEnvironmentBundle | None:
        """Return a previously generated bundle."""
        return self._bundles.get(bundle_id)

    def list_bundle_ids(self, limit: int = 20) -> list[str]:
        """Return recent bundle IDs, most recent first."""
        return list(reversed(self._bundle_order[-limit:]))

    def _iter_workflow_files(self) -> list[Path]:
        if not self._workflow_dir.is_dir():
            return []
        files = [
            path
            for path in self._workflow_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".json", ".yaml", ".yml"}
        ]
        return sorted(files, key=lambda item: item.name)

    def _load_workflow(self, workflow_name: str) -> WorkflowDefinition:
        for path in self._iter_workflow_files():
            workflow = WorkflowDefinition.load_from_file(path)
            if workflow.name == workflow_name:
                return workflow
        raise ValueError(f"Unknown workflow template: {workflow_name}")

    def _build_environment(
        self,
        workflow: WorkflowDefinition,
        variant_index: int,
    ) -> SyntheticEnvironment:
        tool_ids = self._infer_tool_ids(workflow.steps)
        tool_contracts = [
            contract
            for tool_id in tool_ids
            if (contract := self._load_tool_contract(tool_id)) is not None
        ]

        progress_index = min(variant_index - 1, max(len(workflow.steps) - 1, 0))
        active_step = workflow.steps[progress_index]
        initial_state_sql = self._build_initial_state_sql(workflow, variant_index, progress_index)
        completion_sql = self._build_completion_sql(workflow)
        tasks = self._build_tasks(workflow, variant_index, progress_index, tool_ids)
        verification_queries = self._build_verification_queries(workflow)
        tags = list(workflow.metadata.tags)
        if not tags:
            tags = [segment for segment in workflow.name.split("-") if segment]

        return SyntheticEnvironment(
            workflow_name=workflow.name,
            workflow_version=workflow.version,
            variant_index=variant_index,
            domain_tags=tags,
            inferred_tool_ids=tool_ids,
            tool_contracts=tool_contracts,
            workflow=workflow,
            initial_state_sql=initial_state_sql,
            completion_sql=completion_sql,
            tasks=tasks,
            verification_queries=verification_queries,
            metadata={
                "active_step": active_step.id,
                "variant_label": f"{workflow.name}-variant-{variant_index}",
            },
        )

    def _build_initial_state_sql(
        self,
        workflow: WorkflowDefinition,
        variant_index: int,
        progress_index: int,
    ) -> list[str]:
        active_step = workflow.steps[progress_index]
        artifact_rows = self._artifact_rows(workflow.steps)
        statements = [
            """
            CREATE TABLE workflow_context (
                workflow_name TEXT PRIMARY KEY,
                workflow_version TEXT NOT NULL,
                variant_index INTEGER NOT NULL,
                active_step TEXT NOT NULL,
                workflow_status TEXT NOT NULL,
                domain_tags TEXT NOT NULL
            );
            """.strip(),
            """
            CREATE TABLE workflow_steps (
                step_id TEXT PRIMARY KEY,
                step_name TEXT NOT NULL,
                action TEXT NOT NULL,
                status TEXT NOT NULL,
                depends_on TEXT NOT NULL,
                required_tool TEXT NOT NULL,
                output_keys TEXT NOT NULL
            );
            """.strip(),
            """
            CREATE TABLE expected_artifacts (
                artifact_id TEXT PRIMARY KEY,
                step_id TEXT NOT NULL,
                output_name TEXT NOT NULL,
                status TEXT NOT NULL
            );
            """.strip(),
            (
                "INSERT INTO workflow_context "
                "(workflow_name, workflow_version, variant_index, active_step, "
                "workflow_status, domain_tags) "
                f"VALUES ({_sql_literal(workflow.name)}, "
                f"{_sql_literal(workflow.version)}, {variant_index}, "
                f"{_sql_literal(active_step.id)}, 'in_progress', "
                f"{_sql_literal(','.join(workflow.metadata.tags))});"
            ),
        ]

        for index, step in enumerate(workflow.steps):
            if index < progress_index:
                status = "completed"
            elif index == progress_index:
                status = "ready"
            else:
                status = "blocked"
            depends_on = ",".join(step.depends_on)
            output_keys = ",".join(sorted(step.outputs)) if step.outputs else ""
            required_tool = self._infer_tool_for_step(step) or ""
            statements.append(
                "INSERT INTO workflow_steps "
                "(step_id, step_name, action, status, depends_on, required_tool, output_keys) "
                f"VALUES ({_sql_literal(step.id)}, {_sql_literal(step.name or step.id)}, "
                f"{_sql_literal(step.action.value)}, {_sql_literal(status)}, "
                f"{_sql_literal(depends_on)}, {_sql_literal(required_tool)}, "
                f"{_sql_literal(output_keys)});"
            )

        completed_step_ids = {step.id for step in workflow.steps[:progress_index]}
        for artifact_id, step_id, output_name in artifact_rows:
            artifact_status = "available" if step_id in completed_step_ids else "pending"
            statements.append(
                "INSERT INTO expected_artifacts "
                "(artifact_id, step_id, output_name, status) "
                f"VALUES ({_sql_literal(artifact_id)}, {_sql_literal(step_id)}, "
                f"{_sql_literal(output_name)}, {_sql_literal(artifact_status)});"
            )
        return statements

    def _build_completion_sql(self, workflow: WorkflowDefinition) -> list[str]:
        return [
            (
                "UPDATE workflow_context "
                "SET workflow_status = 'complete', active_step = 'done' "
                f"WHERE workflow_name = {_sql_literal(workflow.name)};"
            ),
            "UPDATE workflow_steps SET status = 'completed';",
            "UPDATE expected_artifacts SET status = 'verified';",
        ]

    def _build_tasks(
        self,
        workflow: WorkflowDefinition,
        variant_index: int,
        progress_index: int,
        tool_ids: list[str],
    ) -> list[SyntheticTaskPrompt]:
        active_step = workflow.steps[progress_index]
        artifact_names = [output_name for _, _, output_name in self._artifact_rows(workflow.steps)]
        artifact_summary = ", ".join(artifact_names[:3]) if artifact_names else "workflow outputs"
        success_criteria = [
            "Drive the workflow to a complete terminal state.",
            "Mark all workflow steps as completed in the synthetic state backend.",
            f"Verify the generated artifacts ({artifact_summary}).",
        ]
        tasks = [
            SyntheticTaskPrompt(
                title=f"Complete {workflow.name} variant {variant_index}",
                prompt=(
                    f"Continue workflow '{workflow.name}' from active step '{active_step.id}'. "
                    f"Use the available tools to satisfy dependencies and produce the verified "
                    f"artifacts required by the workflow."
                ),
                success_criteria=success_criteria,
                recommended_tool_ids=tool_ids,
            )
        ]

        if len(workflow.steps) > 2:
            blocked_steps = [step.id for step in workflow.steps[progress_index + 1 :]]
            recovery_target = blocked_steps[0] if blocked_steps else workflow.steps[-1].id
            tasks.append(
                SyntheticTaskPrompt(
                    title=f"Unblock {workflow.name} downstream work",
                    prompt=(
                        f"The downstream execution path is blocked at '{recovery_target}'. "
                        "Repair the dependency chain, complete the remaining steps, and leave "
                        "the synthetic environment ready for verification."
                    ),
                    success_criteria=[
                        f"Unblock step '{recovery_target}'.",
                        "Complete all downstream steps.",
                        "Leave every expected artifact verified.",
                    ],
                    recommended_tool_ids=tool_ids,
                )
            )
        return tasks

    def _build_verification_queries(
        self,
        workflow: WorkflowDefinition,
    ) -> list[SyntheticVerificationQuery]:
        artifact_count = len(self._artifact_rows(workflow.steps))
        return [
            SyntheticVerificationQuery(
                description="workflow reaches a complete terminal status",
                sql=(
                    "SELECT workflow_status FROM workflow_context "
                    f"WHERE workflow_name = {_sql_literal(workflow.name)};"
                ),
                expected_value="complete",
            ),
            SyntheticVerificationQuery(
                description="all workflow steps are completed",
                sql="SELECT COUNT(*) FROM workflow_steps WHERE status = 'completed';",
                expected_value=len(workflow.steps),
            ),
            SyntheticVerificationQuery(
                description="all expected artifacts are verified",
                sql="SELECT COUNT(*) FROM expected_artifacts WHERE status = 'verified';",
                expected_value=artifact_count,
            ),
        ]

    def _validate_environment(self, environment: SyntheticEnvironment) -> None:
        with sqlite3.connect(":memory:") as connection:
            connection.executescript("\n".join(environment.initial_state_sql))
            connection.executescript("\n".join(environment.completion_sql))
            for query in environment.verification_queries:
                row = connection.execute(query.sql).fetchone()
                actual = row[0] if row is not None else None
                if actual != query.expected_value:
                    raise ValueError(
                        "Synthetic environment verification failed for "
                        f"{environment.workflow_name}: {query.description}"
                    )

    def _artifact_rows(self, steps: list[WorkflowStep]) -> list[tuple[str, str, str]]:
        dependency_targets = {dep for step in steps for dep in step.depends_on}
        rows: list[tuple[str, str, str]] = []
        for step in steps:
            output_names = list(step.outputs) if step.outputs else []
            if not output_names and step.id not in dependency_targets:
                output_names = [f"{step.id}-result"]
            for output_name in output_names:
                rows.append((f"{step.id}:{output_name}", step.id, output_name))
        return rows

    def _infer_tool_ids(self, steps: list[WorkflowStep]) -> list[str]:
        tool_ids: list[str] = []
        for step in steps:
            tool_id = self._infer_tool_for_step(step)
            if tool_id is not None and tool_id not in tool_ids:
                tool_ids.append(tool_id)
        return tool_ids

    def _infer_tool_for_step(self, step: WorkflowStep) -> str | None:
        if step.action is StepAction.EXECUTE_CODE and step.tool_id:
            return step.tool_id
        return _ACTION_TOOL_MAP.get(step.action)

    def _load_tool_contract(self, tool_id: str) -> SyntheticToolContract | None:
        candidates = [
            self._tool_dir / f"{tool_id}.yml",
            self._tool_dir / f"{tool_id}.yaml",
            self._tool_dir / f"{tool_id}.json",
        ]
        for path in candidates:
            if not path.exists():
                continue
            if path.suffix.lower() == ".json":
                raw = json.loads(path.read_text(encoding="utf-8"))
            else:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return None
            return SyntheticToolContract(
                tool_id=str(raw.get("name", tool_id)),
                description=str(raw.get("description", "")),
                parameters=dict(raw.get("parameters", {})),
                governance=dict(raw.get("governance", {})),
            )
        return None

    def _store_bundle(self, bundle: SyntheticEnvironmentBundle) -> None:
        self._bundles[bundle.bundle_id] = bundle
        self._bundle_order.append(bundle.bundle_id)
        if len(self._bundle_order) > self._max_saved_bundles:
            oldest = self._bundle_order.pop(0)
            self._bundles.pop(oldest, None)
        self._persist_bundles()

    def _load_persisted_bundles(self) -> None:
        path = self._persistence_path
        if path is None or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("persistence payload must be an object")
            raw_order = raw.get("bundle_order", [])
            raw_bundles = raw.get("bundles", [])
            if not isinstance(raw_order, list) or not isinstance(raw_bundles, list):
                raise ValueError("persistence payload requires list fields")
            loaded_bundles: dict[str, SyntheticEnvironmentBundle] = {}
            for payload in raw_bundles:
                bundle = SyntheticEnvironmentBundle.model_validate(payload)
                loaded_bundles[bundle.bundle_id] = bundle

            normalized_order = [
                bundle_id
                for bundle_id in raw_order
                if isinstance(bundle_id, str) and bundle_id in loaded_bundles
            ]
            for bundle_id in loaded_bundles:
                if bundle_id not in normalized_order:
                    normalized_order.append(bundle_id)

            self._bundles = loaded_bundles
            self._bundle_order = normalized_order
            self._trim_to_retention()
            self._persist_bundles()
        except Exception:
            logger.warning(
                "synthetic_environment_persistence_load_failed path=%s",
                str(path),
                exc_info=True,
            )
            self._bundles = {}
            self._bundle_order = []

    def _persist_bundles(self) -> None:
        path = self._persistence_path
        if path is None:
            return
        payload = {
            "bundle_order": list(self._bundle_order),
            "bundles": [
                self._bundles[bundle_id].model_dump(mode="json")
                for bundle_id in self._bundle_order
                if bundle_id in self._bundles
            ],
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = Path(f"{path}.tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(path)
        except OSError:
            logger.warning(
                "synthetic_environment_persistence_save_failed path=%s",
                str(path),
                exc_info=True,
            )

    def _trim_to_retention(self) -> None:
        while len(self._bundle_order) > self._max_saved_bundles:
            oldest = self._bundle_order.pop(0)
            self._bundles.pop(oldest, None)
