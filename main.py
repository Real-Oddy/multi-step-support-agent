"""
main.py
-------
Application entrypoint for the Multi-Step Order Support Agent.

Startup sequence:
  1. Configure logging (console INFO+, file DEBUG+ for full trace).
  2. Validate required API key configuration.
  3. Initialise the SQLite database (schema + seed data).
  4. Initialise the RAG knowledge base (embed policies into ChromaDB).
  5. Launch the interactive CLI loop.

Usage:
    python main.py
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from pathlib import Path

from dotenv import load_dotenv
from loguru import logger

from agent import ask
from database import init_db
from models import AgentResponse
from rag import init_rag
from config import validate_api_keys

load_dotenv()

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

# Remove the default loguru handler, then re-add two:
#   1. Console  — INFO and above, clean for the terminal.
#   2. Log file — DEBUG and above, full observability trace per session.
logger.remove()
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    colorize=True,
)
logger.add(
    _LOG_DIR / "agent_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
    rotation="1 day",
    retention="7 days",
    encoding="utf-8",
)

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

_WIDTH = 62
_DIVIDER = "─" * _WIDTH


def _wrap(text: str, indent: int = 4) -> str:
    """Wrap text to fit inside the display box with a leading indent."""
    prefix = " " * indent
    return textwrap.fill(text, width=_WIDTH - indent, initial_indent=prefix, subsequent_indent=prefix)


def _print_response(response: AgentResponse) -> None:
    """Render an AgentResponse to stdout in a clean, readable format."""
    escalation = (
        "⚠  YES — A support ticket has been raised."
        if response.escalation_required
        else "✓  No escalation required."
    )

    print()
    print(_DIVIDER)
    print(f"  Order  : {response.order_number}")
    print(f"  Status : {response.current_status}")
    print(_DIVIDER)
    print("  Explanation:")
    print(_wrap(response.explanation))
    print()
    print("  Recommended Action:")
    print(_wrap(response.recommended_action))
    print()
    print(f"  Escalation : {escalation}")
    print(_DIVIDER)
    print()


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------


async def _startup() -> None:
    """
    Initialise all subsystems before the agent loop begins.

    Raises:
        EnvironmentError: If required API keys are missing or a subsystem
            reports a configuration error.
    """
    logger.info("Validating API key configuration...")
    validate_api_keys()

    logger.info("Starting up — initialising database...")
    await init_db()

    logger.info("Initialising RAG knowledge base...")
    await init_rag()

    logger.info("All systems ready. Agent is online.")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


async def _run() -> None:
    """Interactive CLI loop — reads customer queries and prints responses."""

    print()
    print("=" * _WIDTH)
    print("   Multi-Step Order Support Agent")
    print("   Ask about any order (e.g. 'Where is ORD-1004?')")
    print("   Type 'quit' or press Ctrl+C to exit.")
    print("=" * _WIDTH)

    try:
        await _startup()
    except Exception:
        logger.exception("Startup failed")
        sys.exit(1)

    print()

    while True:
        # --- Read input ---
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        if user_input.lower() in {"quit", "exit", "q"}:
            print("Goodbye!")
            break

        # --- Run agent ---
        try:
            response = await ask(user_input)
            _print_response(response)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as exc:
            logger.error(f"Agent run failed: {exc}")
            print(f"\n  ✗ Something went wrong: {exc}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(_run())
