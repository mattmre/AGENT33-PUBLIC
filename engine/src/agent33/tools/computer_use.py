"""Computer Use tool for autonomous spatial desktop interaction.

Follows the reference paradigm set by Anthropic's Computer Use API, allowing
the agent to manipulate standard OS interfaces via mouse and keyboard tracking.
Pairs effectively with the Vision MCP server.
"""

from __future__ import annotations

import logging
from typing import Any

from agent33.tools.base import SchemaAwareTool, ToolContext, ToolResult
from agent33.tools.browser_gate import evaluate_browser_computer_use_gate

logger = logging.getLogger(__name__)


class ComputerUseTool(SchemaAwareTool):
    """Executes actions on the operating system's desktop environment."""

    @property
    def name(self) -> str:
        return "computer_use"

    @property
    def description(self) -> str:
        return (
            "Interact with the desktop environment via"
            " coordinate clicking, typing, and screenshots."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "mouse_move",
                        "left_click",
                        "left_click_drag",
                        "right_click",
                        "middle_click",
                        "double_click",
                        "screenshot",
                        "cursor_position",
                        "type",
                        "key",
                    ],
                    "description": "The desktop action to perform.",
                },
                "coordinate": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "[x, y] coordinates. Required for mouse_move and drag actions.",
                },
                "text": {
                    "type": "string",
                    "description": (
                        "Text to type or keys to press. Required for 'type' and 'key' actions."
                    ),
                },
            },
            "required": ["action"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        action = params.get("action")
        logger.info(f"Executing computer_use: {action}")
        gate = evaluate_browser_computer_use_gate(self.name, str(action or ""), context)
        if not gate.allowed:
            return ToolResult.fail(f"{gate.reason} Evidence: {gate.evidence_line()}")

        return ToolResult.fail(
            "computer_use is not available in this deployment. "
            "OS automation (PyAutoGUI/xdotool) is not configured."
        )
