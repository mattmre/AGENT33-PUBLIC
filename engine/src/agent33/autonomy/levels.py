"""P67 -- Autonomy Level System: integer levels 0-3 mapped to AutonomyBudget templates.

Maps user-facing autonomy levels (0=supervised, 1=default, 2=autonomous,
3=full) into concrete :class:`AutonomyBudget` objects with pre-configured
file, command, network, and resource scopes.  The returned budgets are
already in ``ACTIVE`` state because the user's level selection acts as the
approval mechanism.
"""

from __future__ import annotations

import uuid

from agent33.autonomy.models import (
    AutonomyBudget,
    BudgetState,
    CommandPermission,
    EscalationTrigger,
    FileScope,
    NetworkScope,
    ResourceLimits,
    StopAction,
    StopCondition,
)

AUTONOMY_LEVEL_DESCRIPTIONS: dict[int, str] = {
    0: "Fully supervised -- all actions require approval",
    1: "Read/analyze/report autonomously -- write and execute require approval (default)",
    2: "Autonomous except destructive operations and external network calls",
    3: "Fully autonomous -- all operations proceed without approval (opt-in)",
}

# Read-only commands safe for Level 1
_LEVEL_1_ALLOWED_COMMANDS: list[CommandPermission] = [
    CommandPermission(command="git", args_pattern=r"^(log|diff|status|show|branch|tag)\b.*"),
    CommandPermission(command="ls"),
    CommandPermission(command="dir"),
    CommandPermission(command="find"),
    CommandPermission(command="cat"),
    CommandPermission(command="head"),
    CommandPermission(command="tail"),
    CommandPermission(command="wc"),
    CommandPermission(command="grep"),
    CommandPermission(command="rg"),
    CommandPermission(command="tree"),
    CommandPermission(command="file"),
    CommandPermission(command="stat"),
    CommandPermission(command="which"),
    CommandPermission(command="where"),
    CommandPermission(command="echo"),
    CommandPermission(command="python", args_pattern=r"^-c\b.*"),
    CommandPermission(command="type"),
]

# Destructive commands blocked at Level 2
_LEVEL_2_DENIED_COMMANDS: list[str] = [
    "rm",
    "rmdir",
    "del",
    "sudo",
    "su",
    "chmod",
    "chown",
    "mkfs",
    "dd",
    "fdisk",
    "shutdown",
    "reboot",
    "systemctl",
    "docker",
    "kubectl",
    "curl",
    "wget",
    "ssh",
    "scp",
    "rsync",
    "nc",
    "ncat",
    "nmap",
]


def autonomy_level_to_budget(level: int, task_name: str = "agent-task") -> AutonomyBudget:
    """Translate an integer autonomy level (0-3) into a pre-configured AutonomyBudget.

    The returned budget is in ``ACTIVE`` state -- it bypasses the approval
    workflow because the user's level selection *is* the approval mechanism.

    Parameters
    ----------
    level:
        0 = fully supervised (reads allowed, writes/commands/network blocked)
        1 = read/analyze/report auto, writes/execute require approval (DEFAULT)
        2 = autonomous except destructive operations and external network
        3 = fully autonomous -- all operations proceed
    task_name:
        Optional label embedded in the budget for tracing.

    Raises
    ------
    ValueError
        If *level* is not in ``{0, 1, 2, 3}``.
    """
    if level not in (0, 1, 2, 3):
        msg = f"Autonomy level must be 0-3, got {level}"
        raise ValueError(msg)

    budget_id = f"level-{level}-{uuid.uuid4().hex[:8]}"

    builders = {
        0: _level_0_budget,
        1: _level_1_budget,
        2: _level_2_budget,
        3: _level_3_budget,
    }
    return builders[level](budget_id, task_name)


# ---------------------------------------------------------------------------
# Level 0 -- Fully Supervised
# ---------------------------------------------------------------------------


def _level_0_budget(budget_id: str, task_name: str) -> AutonomyBudget:
    """Level 0: reads allowed, everything else blocked.

    Uses a non-empty ``allowed_commands`` list containing only a sentinel
    entry (``__none__``) that never matches a real command.  This activates
    the RuntimeEnforcer's allowlist check, which then blocks every real
    command because none of them match.
    """
    return AutonomyBudget(
        budget_id=budget_id,
        task_id=task_name,
        state=BudgetState.ACTIVE,
        in_scope=["read-only observation"],
        out_of_scope=["file writes", "command execution", "network access"],
        files=FileScope(
            read=["**"],
            write=[],
            deny=[],
        ),
        # Sentinel entry activates the allowlist — no real command matches.
        allowed_commands=[CommandPermission(command="__none__")],
        denied_commands=[],
        require_approval_commands=[],
        network=NetworkScope(enabled=False),
        limits=ResourceLimits(
            max_iterations=5,
            max_duration_minutes=10,
            max_files_modified=0,
            max_lines_changed=0,
            max_tool_calls=10,
        ),
        stop_conditions=[
            StopCondition(
                condition_id="SC-L0-01",
                description="Stop on any write attempt",
                action=StopAction.ESCALATE,
            ),
        ],
        escalation_triggers=[
            EscalationTrigger(
                trigger_id="ET-L0-01",
                description="Any modification attempt requires approval",
                target="orchestrator",
            ),
        ],
        default_escalation_target="orchestrator",
    )


# ---------------------------------------------------------------------------
# Level 1 -- Read/Analyze Auto, Write/Execute Require Approval (DEFAULT)
# ---------------------------------------------------------------------------


def _level_1_budget(budget_id: str, task_name: str) -> AutonomyBudget:
    """Level 1: autonomous reading and analysis, writes and execution need approval."""
    return AutonomyBudget(
        budget_id=budget_id,
        task_id=task_name,
        state=BudgetState.ACTIVE,
        in_scope=["file reading", "analysis", "reporting"],
        out_of_scope=["file modification without approval", "external network"],
        files=FileScope(
            read=["**"],
            write=["**"],
            deny=[],
        ),
        allowed_commands=list(_LEVEL_1_ALLOWED_COMMANDS),
        denied_commands=[],
        # Commands not in the allowlist above are blocked automatically.
        # Write-oriented git subcommands (push, commit, etc.) are blocked
        # because the allowlist only permits read-only git subcommands.
        require_approval_commands=["python", "pip", "npm", "node"],
        network=NetworkScope(enabled=False),
        limits=ResourceLimits(
            max_iterations=20,
            max_duration_minutes=30,
            max_files_modified=10,
            max_lines_changed=1000,
            max_tool_calls=50,
        ),
        stop_conditions=[
            StopCondition(
                condition_id="SC-L1-01",
                description="Stop when iteration limit reached",
                action=StopAction.STOP,
            ),
        ],
        escalation_triggers=[
            EscalationTrigger(
                trigger_id="ET-L1-01",
                description="Write operation requires approval",
                target="orchestrator",
            ),
        ],
        default_escalation_target="orchestrator",
    )


# ---------------------------------------------------------------------------
# Level 2 -- Autonomous Except Destructive / External
# ---------------------------------------------------------------------------


def _level_2_budget(budget_id: str, task_name: str) -> AutonomyBudget:
    """Level 2: autonomous except destructive commands and external network."""
    return AutonomyBudget(
        budget_id=budget_id,
        task_id=task_name,
        state=BudgetState.ACTIVE,
        in_scope=["file read/write", "local command execution", "local network"],
        out_of_scope=["destructive operations", "external network", "system administration"],
        files=FileScope(
            read=["**"],
            write=["**"],
            deny=["/etc/**", "/sys/**", "/proc/**", "~/.ssh/**", "**/.env", "**/.env.*"],
        ),
        allowed_commands=[],
        denied_commands=list(_LEVEL_2_DENIED_COMMANDS),
        require_approval_commands=[],
        network=NetworkScope(
            enabled=True,
            allowed_domains=["localhost", "127.0.0.1", "::1", "host.docker.internal"],
            denied_domains=[],
            max_requests=100,
        ),
        limits=ResourceLimits(
            max_iterations=50,
            max_duration_minutes=60,
            max_files_modified=30,
            max_lines_changed=3000,
            max_tool_calls=200,
        ),
        stop_conditions=[
            StopCondition(
                condition_id="SC-L2-01",
                description="Stop when iteration limit reached",
                action=StopAction.STOP,
            ),
            StopCondition(
                condition_id="SC-L2-02",
                description="Escalate on denied command attempt",
                action=StopAction.ESCALATE,
            ),
        ],
        escalation_triggers=[
            EscalationTrigger(
                trigger_id="ET-L2-01",
                description="Destructive operation blocked -- requires level 3",
                target="orchestrator",
            ),
        ],
        default_escalation_target="orchestrator",
    )


# ---------------------------------------------------------------------------
# Level 3 -- Fully Autonomous
# ---------------------------------------------------------------------------


def _level_3_budget(budget_id: str, task_name: str) -> AutonomyBudget:
    """Level 3: fully autonomous -- all operations proceed without approval."""
    return AutonomyBudget(
        budget_id=budget_id,
        task_id=task_name,
        state=BudgetState.ACTIVE,
        in_scope=["all operations"],
        out_of_scope=[],
        files=FileScope(
            read=["**"],
            write=["**"],
            deny=[],
        ),
        allowed_commands=[],
        denied_commands=[],
        require_approval_commands=[],
        network=NetworkScope(
            enabled=True,
            allowed_domains=[],
            denied_domains=[],
            max_requests=0,
        ),
        limits=ResourceLimits(
            max_iterations=100,
            max_duration_minutes=120,
            max_files_modified=50,
            max_lines_changed=5000,
            max_tool_calls=500,
        ),
        stop_conditions=[
            StopCondition(
                condition_id="SC-L3-01",
                description="Stop when iteration limit reached",
                action=StopAction.STOP,
            ),
        ],
        escalation_triggers=[],
        default_escalation_target="orchestrator",
    )
