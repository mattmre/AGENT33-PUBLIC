"""FastAPI router for slash-command invocation and discovery (Phase 54).

Endpoints:
- ``POST /v1/commands/invoke`` -- parse and invoke a slash-command
- ``GET  /v1/commands``        -- list available commands
- ``GET  /v1/commands/{command_name}`` -- get help for one command
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.security.permissions import require_scope
from agent33.skills.slash_commands import (
    CommandInfo,
    CommandRegistry,
    CommandResult,
    ParsedCommand,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/commands", tags=["commands"])

# Module-level reference for test overrides
_command_registry: CommandRegistry | None = None


def set_command_registry(registry: CommandRegistry | None) -> None:
    """Set the module-level command registry reference (for tests)."""
    global _command_registry  # noqa: PLW0603
    _command_registry = registry


def _get_command_registry(request: Request) -> CommandRegistry:
    """Resolve the command registry from test override or app state."""
    if _command_registry is not None:
        return _command_registry
    svc: Any = getattr(request.app.state, "command_registry", None)
    if svc is not None:
        return svc  # type: ignore[no-any-return]
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Command registry not initialized",
    )


def _get_skill_registry(request: Request) -> Any:
    """Resolve the skill registry from app state."""
    svc = getattr(request.app.state, "skill_registry", None)
    if svc is not None:
        return svc
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Skill registry not initialized",
    )


# -- Request / Response models --


class InvokeCommandRequest(BaseModel):
    """Body for the command invoke endpoint."""

    input: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="The slash-command string (e.g. '/deploy staging --dry-run').",
    )
    agent_name: str | None = Field(
        default=None,
        description="Optional agent to handle the skill invocation. Defaults to orchestrator.",
    )
    session_id: str | None = Field(
        default=None,
        description="Optional session ID for context continuity.",
    )


class InvokeCommandResponse(BaseModel):
    """Response from command invocation."""

    parsed: ParsedCommand = Field(description="The parsed command structure.")
    result: CommandResult = Field(description="The invocation result.")


class CommandListResponse(BaseModel):
    """Response for the command listing endpoint."""

    count: int = Field(description="Total number of available commands.")
    commands: list[CommandInfo] = Field(description="Available commands.")


# -- Routes --


@router.get(
    "",
    response_model=CommandListResponse,
    dependencies=[require_scope("agents:read")],
)
async def list_commands(request: Request) -> CommandListResponse:
    """List all available slash-commands with their help text."""
    cmd_registry = _get_command_registry(request)
    commands = cmd_registry.list_commands()
    return CommandListResponse(count=len(commands), commands=commands)


@router.get(
    "/{command_name}",
    response_model=CommandInfo,
    dependencies=[require_scope("agents:read")],
)
async def get_command(request: Request, command_name: str) -> CommandInfo:
    """Get help information for a specific slash-command."""
    cmd_registry = _get_command_registry(request)

    # Ensure the command has a leading slash for lookup
    lookup = command_name if command_name.startswith("/") else f"/{command_name}"
    info = cmd_registry.get_command_info(lookup)
    if info is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Command '{lookup}' not found",
        )
    return info


@router.post(
    "/invoke",
    response_model=InvokeCommandResponse,
    dependencies=[require_scope("agents:execute")],
)
async def invoke_command(
    request: Request,
    body: InvokeCommandRequest,
) -> InvokeCommandResponse:
    """Parse and invoke a slash-command.

    The command string is parsed to identify the target skill, positional
    arguments, and flags.  The skill is then invoked via the AgentRuntime
    if available, otherwise returns the parsed result with the skill's
    instructions as a direct response.
    """
    cmd_registry = _get_command_registry(request)

    # Parse the command
    parsed = cmd_registry.resolve(body.input)
    if parsed is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unrecognized command in: {body.input!r}",
        )

    skill_registry = _get_skill_registry(request)
    skill = skill_registry.get(parsed.skill_name)
    if skill is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{parsed.skill_name}' not found in registry",
        )

    # Attempt invocation via AgentRuntime if available
    agent_registry: Any = getattr(request.app.state, "agent_registry", None)
    model_router: Any = getattr(request.app.state, "model_router", None)
    skill_injector: Any = getattr(request.app.state, "skill_injector", None)

    if agent_registry is not None and model_router is not None:
        try:
            result = await _invoke_via_agent(
                agent_registry=agent_registry,
                model_router=model_router,
                skill_injector=skill_injector,
                parsed=parsed,
                skill=skill,
                agent_name=body.agent_name,
                session_id=body.session_id or "",
            )
            return InvokeCommandResponse(parsed=parsed, result=result)
        except Exception as exc:
            logger.warning(
                "command_agent_invocation_failed",
                command=parsed.command,
                skill=parsed.skill_name,
                error=str(exc),
            )
            return InvokeCommandResponse(
                parsed=parsed,
                result=CommandResult(
                    command=parsed.command,
                    skill_name=parsed.skill_name,
                    success=False,
                    error=f"Agent invocation failed: {exc}",
                ),
            )

    # Fallback: return skill instructions as the output
    output = skill.instructions if skill.instructions else skill.description
    return InvokeCommandResponse(
        parsed=parsed,
        result=CommandResult(
            command=parsed.command,
            skill_name=parsed.skill_name,
            success=True,
            output=output,
            metadata={"mode": "direct", "args": parsed.args, "flags": parsed.flags},
        ),
    )


async def _invoke_via_agent(
    agent_registry: Any,
    model_router: Any,
    skill_injector: Any,
    parsed: ParsedCommand,
    skill: Any,
    agent_name: str | None,
    session_id: str,
) -> CommandResult:
    """Invoke the skill through an AgentRuntime instance."""
    from agent33.agents.runtime import AgentRuntime

    # Determine which agent definition to use
    target_agent = agent_name or "orchestrator"
    definition = agent_registry.get(target_agent)
    if definition is None:
        # Fall back to first available agent
        all_agents = agent_registry.list_all()
        if not all_agents:
            return CommandResult(
                command=parsed.command,
                skill_name=parsed.skill_name,
                success=False,
                error="No agent definitions available",
            )
        definition = all_agents[0]

    # Build the input from parsed args and flags
    inputs: dict[str, Any] = {
        "command": parsed.command,
        "instruction": parsed.raw_args_string,
        "args": parsed.args,
        "flags": parsed.flags,
    }

    runtime = AgentRuntime(
        definition=definition,
        router=model_router,
        skill_injector=skill_injector,
        active_skills=[parsed.skill_name],
        session_id=session_id,
    )

    agent_result = await runtime.invoke(inputs)
    # AgentResult.output is a dict; serialize to string for the command result
    output_text = agent_result.raw_response or json.dumps(agent_result.output)
    return CommandResult(
        command=parsed.command,
        skill_name=parsed.skill_name,
        success=True,
        output=output_text,
        metadata={
            "mode": "agent",
            "agent": definition.name,
            "model": agent_result.model,
            "args": parsed.args,
            "flags": parsed.flags,
        },
    )
