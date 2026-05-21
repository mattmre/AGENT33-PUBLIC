"""Durable workflow registry and execution-history state."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.history import WorkflowExecutionRecord, normalize_execution_record

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)


class WorkflowStateService:
    """Persist workflow definitions and bounded execution history.

    The service can either manage its own containers or attach to caller-supplied
    ``dict``/``deque`` instances so existing module-level workflow globals remain
    the live backing store.
    """

    _NAMESPACE = "workflows"

    def __init__(
        self,
        state_store: OrchestrationStateStore | None = None,
        *,
        namespace: str = "workflows",
        max_execution_history: int = 1000,
        registry: dict[str, WorkflowDefinition] | None = None,
        execution_history: deque[dict[str, Any]] | None = None,
    ) -> None:
        self._state_store = state_store
        self._namespace = namespace
        requested_max_history = max(1, max_execution_history)
        self._registry = registry if registry is not None else {}
        self._execution_history = (
            execution_history
            if execution_history is not None
            else deque(maxlen=requested_max_history)
        )
        supplied_maxlen = self._execution_history.maxlen
        self._max_execution_history = (
            supplied_maxlen if supplied_maxlen is not None else requested_max_history
        )
        self._trim_execution_history()
        self._load_state()

    @property
    def registry(self) -> dict[str, WorkflowDefinition]:
        return self._registry

    @property
    def execution_history(self) -> deque[dict[str, Any]]:
        return self._execution_history

    @property
    def max_execution_history(self) -> int:
        return self._max_execution_history

    def clear(self) -> None:
        """Clear workflow state and persist the reset when a store is configured."""
        self._registry.clear()
        self._execution_history.clear()
        self.persist_state()

    def list_workflows(self) -> list[WorkflowDefinition]:
        """Return all registered workflow definitions."""
        return list(self._registry.values())

    def get_workflow(self, name: str) -> WorkflowDefinition | None:
        """Return a workflow definition by name."""
        return self._registry.get(name)

    def register_workflow(
        self,
        definition: WorkflowDefinition | Mapping[str, Any],
    ) -> WorkflowDefinition:
        """Add or replace one workflow definition and persist it."""
        record = (
            definition
            if isinstance(definition, WorkflowDefinition)
            else WorkflowDefinition.model_validate(definition)
        )
        self._registry[record.name] = record
        self.persist_state()
        return record

    def delete_workflow(self, name: str) -> bool:
        """Delete one workflow definition and persist the change."""
        removed = self._registry.pop(name, None)
        if removed is None:
            return False
        self.persist_state()
        return True

    def list_execution_records(
        self,
        *,
        workflow_name: str | None = None,
    ) -> list[WorkflowExecutionRecord]:
        """Return normalized execution records, optionally filtered by workflow."""
        records = [normalize_execution_record(entry) for entry in self._execution_history]
        if workflow_name is None:
            return records
        return [record for record in records if record.workflow_name == workflow_name]

    def has_run_id(self, run_id: str) -> bool:
        """Return ``True`` when *run_id* exists in execution history."""
        target = run_id.strip()
        return any(record.run_id == target for record in self.list_execution_records())

    def record_execution(
        self,
        entry: WorkflowExecutionRecord | Mapping[str, Any],
    ) -> WorkflowExecutionRecord:
        """Append one execution-history entry and persist it."""
        record = normalize_execution_record(entry)
        self._execution_history.append(record.model_dump(mode="json"))
        self._trim_execution_history()
        self.persist_state()
        return record

    def persist_state(self) -> None:
        """Flush the current workflow state to the orchestration store."""
        normalized_registry = self._normalize_registry_in_place()
        normalized_history = self._normalize_execution_history_in_place()
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._namespace,
            {
                "registry": {
                    name: definition.model_dump(mode="json")
                    for name, definition in normalized_registry.items()
                },
                "execution_history": normalized_history,
            },
        )

    def persist(self) -> None:
        """Compatibility alias for callers persisting shared live containers."""
        self.persist_state()

    def _load_state(self) -> None:
        if self._state_store is None:
            return

        payload = self._state_store.read_namespace(self._namespace)

        registry_payload = payload.get("registry", payload.get("definitions"))
        if isinstance(registry_payload, dict):
            loaded_registry: dict[str, WorkflowDefinition] = {}
            for name, definition_payload in registry_payload.items():
                if not isinstance(name, str):
                    continue
                try:
                    definition = WorkflowDefinition.model_validate(definition_payload)
                except ValidationError:
                    logger.warning("workflow_definition_restore_failed name=%s", name)
                    continue
                loaded_registry[definition.name] = definition
            self._registry.clear()
            self._registry.update(loaded_registry)

        history_payload = payload.get("execution_history")
        if isinstance(history_payload, list):
            self._execution_history.clear()
            for entry in history_payload:
                if not isinstance(entry, Mapping):
                    logger.warning(
                        "workflow_history_restore_failed entry_type=%s",
                        type(entry).__name__,
                    )
                    continue
                try:
                    record = normalize_execution_record(entry)
                except (TypeError, ValidationError, ValueError):
                    logger.warning(
                        "workflow_history_restore_failed run=%s",
                        entry.get("run_id", ""),
                    )
                    continue
                self._execution_history.append(record.model_dump(mode="json"))
            self._trim_execution_history()

    def _normalize_registry_in_place(self) -> dict[str, WorkflowDefinition]:
        normalized: dict[str, WorkflowDefinition] = {}
        for key, raw_definition in list(self._registry.items()):
            try:
                definition = (
                    raw_definition
                    if isinstance(raw_definition, WorkflowDefinition)
                    else WorkflowDefinition.model_validate(raw_definition)
                )
            except ValidationError:
                logger.warning("workflow_definition_persist_failed name=%s", key)
                continue
            normalized[definition.name] = definition
        self._registry.clear()
        self._registry.update(normalized)
        return normalized

    def _normalize_execution_history_in_place(self) -> list[dict[str, Any]]:
        normalized_entries: list[dict[str, Any]] = []
        for raw_entry in list(self._execution_history):
            if not isinstance(raw_entry, (WorkflowExecutionRecord, Mapping)):
                logger.warning(
                    "workflow_history_persist_failed entry_type=%s",
                    type(raw_entry).__name__,
                )
                continue
            try:
                record = normalize_execution_record(raw_entry)
            except (TypeError, ValidationError, ValueError):
                logger.warning(
                    "workflow_history_persist_failed run=%s",
                    raw_entry.get("run_id", "") if isinstance(raw_entry, Mapping) else "",
                )
                continue
            normalized_entries.append(record.model_dump(mode="json"))

        self._execution_history.clear()
        for entry in normalized_entries:
            self._execution_history.append(entry)
        self._trim_execution_history()
        return list(self._execution_history)

    def _trim_execution_history(self) -> None:
        while len(self._execution_history) > self._max_execution_history:
            self._execution_history.popleft()
