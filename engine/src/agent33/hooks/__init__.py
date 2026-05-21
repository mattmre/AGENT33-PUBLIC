"""Hook Framework (H01, Phase 32.1) -- 3-tier middleware hook chain system.

Public API:
    HookEventType, HookContext, AgentHookContext, ToolHookContext,
    WorkflowHookContext, RequestHookContext, HookResult, HookChainResult,
    HookDefinition, HookExecutionLog, Hook, HookAbortError, BaseHook,
    HookChainRunner, ConcurrentHookChainRunner, HookRegistry,
    ScriptHook, ScriptHookDiscovery.
"""

from agent33.hooks.chain import ConcurrentHookChainRunner, HookChainRunner
from agent33.hooks.models import (
    AgentHookContext,
    HookChainResult,
    HookContext,
    HookDefinition,
    HookEventType,
    HookExecutionLog,
    HookResult,
    RequestHookContext,
    ToolHookContext,
    WorkflowHookContext,
)
from agent33.hooks.protocol import BaseHook, HookAbortError
from agent33.hooks.registry import HookRegistry
from agent33.hooks.script_discovery import ScriptHookDiscovery
from agent33.hooks.script_hook import ScriptHook

__all__ = [
    "AgentHookContext",
    "BaseHook",
    "ConcurrentHookChainRunner",
    "HookAbortError",
    "HookChainResult",
    "HookChainRunner",
    "HookContext",
    "HookDefinition",
    "HookEventType",
    "HookExecutionLog",
    "HookRegistry",
    "HookResult",
    "RequestHookContext",
    "ScriptHook",
    "ScriptHookDiscovery",
    "ToolHookContext",
    "WorkflowHookContext",
]
