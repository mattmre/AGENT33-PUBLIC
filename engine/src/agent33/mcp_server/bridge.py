"""Bridge between MCP server and AGENT-33 services."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.agents.registry import AgentRegistry
    from agent33.discovery.service import DiscoveryService
    from agent33.llm.router import ModelRouter
    from agent33.mcp_server.proxy_manager import ProxyManager
    from agent33.memory.rag import RAGPipeline
    from agent33.skills.registry import SkillRegistry
    from agent33.tools.discovery_runtime import ToolActivationManager
    from agent33.tools.governance import ToolGovernance
    from agent33.tools.registry import ToolRegistry
    from agent33.workflows.definition import WorkflowDefinition

logger = logging.getLogger(__name__)


class MCPServiceBridge:
    """Wires MCP tool handlers to live AGENT-33 services."""

    def __init__(
        self,
        agent_registry: AgentRegistry | None = None,
        tool_registry: ToolRegistry | None = None,
        model_router: ModelRouter | None = None,
        rag_pipeline: RAGPipeline | None = None,
        skill_registry: SkillRegistry | None = None,
        workflow_registry: dict[str, WorkflowDefinition] | None = None,
        proxy_manager: ProxyManager | None = None,
        discovery_service: DiscoveryService | None = None,
        tool_activation_manager: ToolActivationManager | None = None,
        tool_governance: ToolGovernance | None = None,
        tool_discovery_mode: str = "legacy",
    ) -> None:
        self.agent_registry = agent_registry
        self.tool_registry = tool_registry
        self.model_router = model_router
        self.rag_pipeline = rag_pipeline
        self.skill_registry = skill_registry
        self.workflow_registry = workflow_registry
        self.proxy_manager = proxy_manager
        self.discovery_service = discovery_service
        self.tool_activation_manager = tool_activation_manager
        self.tool_governance = tool_governance
        self.tool_discovery_mode = tool_discovery_mode

    def get_system_status(self) -> dict[str, Any]:
        """Return system status summary."""
        return {
            "status": "operational",
            "agents_loaded": (len(self.agent_registry.list_all()) if self.agent_registry else 0),
            "tools_loaded": (len(self.tool_registry.list_all()) if self.tool_registry else 0),
            "skills_loaded": (len(self.skill_registry.list_all()) if self.skill_registry else 0),
            "workflows_loaded": len(self.workflow_registry or {}),
            "proxy_servers_loaded": (
                len(self.proxy_manager.list_servers()) if self.proxy_manager is not None else 0
            ),
            "model_router_ready": self.model_router is not None,
            "rag_pipeline_ready": self.rag_pipeline is not None,
        }

    def get_agent(self, identifier: str) -> Any:
        """Return an agent definition by spec ID or registry name."""
        if self.agent_registry is None:
            return None

        get_by_agent_id = getattr(self.agent_registry, "get_by_agent_id", None)
        if callable(get_by_agent_id):
            agent = get_by_agent_id(identifier)
            if agent is not None:
                return agent

        return self.agent_registry.get(identifier)

    def get_workflow(self, identifier: str) -> Any:
        """Return a workflow definition by ID/name."""
        if self.workflow_registry is None:
            return None
        return self.workflow_registry.get(identifier)
