"""Abstract base class for execution adapters."""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.execution.models import AdapterDefinition, ExecutionContract, ExecutionResult


class BaseAdapter(abc.ABC):
    """Base class that all execution adapters must implement.

    An adapter translates an :class:`ExecutionContract` into a concrete
    invocation (subprocess, HTTP call, SDK call, etc.) and returns an
    :class:`ExecutionResult`.
    """

    def __init__(self, definition: AdapterDefinition) -> None:
        self._definition = definition

    @property
    def adapter_id(self) -> str:
        """Unique identifier for this adapter instance."""
        return self._definition.adapter_id

    @property
    def tool_id(self) -> str:
        """The tool this adapter services."""
        return self._definition.tool_id

    @property
    def definition(self) -> AdapterDefinition:
        """Full adapter definition."""
        return self._definition

    @abc.abstractmethod
    async def execute(self, contract: ExecutionContract) -> ExecutionResult:
        """Execute the contract and return a result.

        Implementations must honour the sandbox timeout from the contract
        and must never raise unhandled exceptions — errors should be returned
        inside :class:`ExecutionResult` with ``success=False``.
        """
