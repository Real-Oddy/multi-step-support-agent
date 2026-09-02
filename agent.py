"""
agent.py
--------
PydanticAI agent definition for the Multi-Step Order Support Agent.

The system prompt is loaded from prompts/system_prompt.md — completely
separate from code so it can be edited and versioned independently.

Exposes:
  agent   — the configured Agent instance (useful for testing or inspection).
  ask()   — async entry point: runs the agent on one customer message and
             returns a validated AgentResponse.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger
from pydantic_ai import Agent
from pydantic_ai.messages import NativeToolCallPart, ToolCallPart
from pydantic_ai.models.anthropic import AnthropicModel

from models import AgentResponse
from tools import (
    fetch_return_policy,
    lookup_order,
    open_support_ticket,
    track_shipment,
)

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_PROMPTS_DIR: Path = Path(__file__).parent / "prompts"

# Read the system prompt once at import time — fail fast if the file is missing.
_SYSTEM_PROMPT: str = (_PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8")

# Model is configurable via .env so you can swap models without code changes.
# Defaults to claude-haiku-4-5 — fast and cost-efficient for tool-use workflows.
_MODEL_NAME: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

agent: Agent[None, AgentResponse] = Agent(
    model=AnthropicModel(_MODEL_NAME),
    output_type=AgentResponse,
    system_prompt=_SYSTEM_PROMPT,
    tools=[lookup_order, track_shipment, fetch_return_policy, open_support_ticket],
    retries=2,  # retry on transient tool or model errors before raising
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_tool_trace(messages: list) -> list[str]:
    """
    Walk the message history and return an ordered list of tool names called.

    Works with both ToolCallPart and NativeToolCallPart (Anthropic uses native
    tool call format under the hood).
    """
    tool_calls: list[str] = []
    for message in messages:
        for part in getattr(message, "parts", []):
            if isinstance(part, (ToolCallPart, NativeToolCallPart)):
                # tool_kind holds the function name registered with the agent
                name = getattr(part, "tool_kind", None) or getattr(part, "tool_name", None)
                if name:
                    tool_calls.append(name)
    return tool_calls


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def ask(user_message: str) -> AgentResponse:
    """
    Run the support agent on a single customer message.

    Executes the full multi-step tool call loop, applies all business rules
    via the agent's reasoning, and returns a validated AgentResponse.

    Args:
        user_message: The raw message text from the customer.

    Returns:
        A fully validated AgentResponse with all five fields populated.
    """
    preview = (
        user_message[:80] + "..." if len(user_message) > 80 else user_message
    )
    logger.info(f"Agent run started | message='{preview}'")

    result = await agent.run(user_message)

    # --- Observability: log the full tool decision trace ---
    tool_trace = _extract_tool_trace(result.all_messages())
    if tool_trace:
        logger.info(f"Tool trace | {' → '.join(tool_trace)}")
    else:
        logger.debug("No tool calls were made in this run.")

    # --- Log token usage ---
    usage = result.usage
    logger.debug(
        f"Token usage | input={usage.input_tokens} | "
        f"output={usage.output_tokens} | total={usage.total_tokens}"
    )

    response: AgentResponse = result.output

    logger.info(
        f"Agent run complete | order={response.order_number} | "
        f"status='{response.current_status}' | "
        f"escalation={response.escalation_required}"
    )

    return response
