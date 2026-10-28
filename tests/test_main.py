"""Tests for CLI startup and response helpers."""

import io
import sys
import unittest
from contextlib import redirect_stdout
from types import ModuleType
from unittest.mock import AsyncMock, Mock, patch
from unittest.async_case import IsolatedAsyncioTestCase

from models import AgentResponse


# Importing main configures Loguru sinks and creates a log directory. Give the
# module a mock logger so unit tests do not create files or alter global sinks.
async def _placeholder(*_args, **_kwargs):
    raise NotImplementedError


_logger_stub = Mock()
_loguru_stub = ModuleType("loguru")
_loguru_stub.logger = _logger_stub
_agent_stub = ModuleType("agent")
_agent_stub.ask = _placeholder
_database_stub = ModuleType("database")
_database_stub.init_db = _placeholder
_rag_stub = ModuleType("rag")
_rag_stub.init_rag = _placeholder
with patch.dict(
    sys.modules,
    {
        "loguru": _loguru_stub,
        "agent": _agent_stub,
        "database": _database_stub,
        "rag": _rag_stub,
    },
):
    import main as cli


class DisplayHelperTests(unittest.TestCase):
    def test_wrap_indents_and_respects_display_width(self) -> None:
        text = "A customer support response that is long enough to wrap across more than one line."

        wrapped = cli._wrap(text)
        lines = wrapped.splitlines()

        self.assertGreater(len(lines), 1)
        self.assertTrue(all(line.startswith("    ") for line in lines))
        self.assertTrue(all(len(line) <= cli._WIDTH for line in lines))

    def test_print_response_shows_structured_fields_and_escalation(self) -> None:
        response = AgentResponse(
            order_number="ORD-1234",
            current_status="Delayed",
            explanation="The delivery is delayed.",
            recommended_action="A support agent will follow up.",
            escalation_required=True,
        )
        output = io.StringIO()

        with redirect_stdout(output):
            cli._print_response(response)

        rendered = output.getvalue()
        self.assertIn("ORD-1234", rendered)
        self.assertIn("Delayed", rendered)
        self.assertIn("The delivery is delayed.", rendered)
        self.assertIn("A support agent will follow up.", rendered)
        self.assertIn("A support ticket has been raised", rendered)


class StartupTests(IsolatedAsyncioTestCase):
    async def test_startup_initializes_database_before_rag(self) -> None:
        calls = []

        async def initialize_db() -> None:
            calls.append("database")

        async def initialize_rag() -> None:
            calls.append("rag")

        with (
            patch.object(cli, "init_db", new=initialize_db),
            patch.object(cli, "init_rag", new=initialize_rag),
        ):
            await cli._startup()

        self.assertEqual(calls, ["database", "rag"])

    async def test_startup_propagates_environment_error(self) -> None:
        with (
            patch.object(cli, "init_db", new=AsyncMock()),
            patch.object(cli, "init_rag", new=AsyncMock(side_effect=EnvironmentError("missing key"))),
        ):
            with self.assertRaisesRegex(EnvironmentError, "missing key"):
                await cli._startup()


class RunLoopTests(IsolatedAsyncioTestCase):
    async def test_quit_command_runs_startup_then_exits_cleanly(self) -> None:
        startup = AsyncMock()
        output = io.StringIO()

        with (
            patch.object(cli, "_startup", new=startup),
            patch("builtins.input", return_value="quit"),
            redirect_stdout(output),
        ):
            await cli._run()

        startup.assert_awaited_once_with()
        self.assertIn("Goodbye!", output.getvalue())

    async def test_blank_input_is_skipped_and_query_response_is_printed(self) -> None:
        startup = AsyncMock()
        response = AgentResponse(
            order_number="ORD-1234",
            current_status="Shipped",
            explanation="The order is moving through the network.",
            recommended_action="Check tracking again tomorrow.",
        )
        ask = AsyncMock(return_value=response)
        inputs = iter(["  ", "Where is ORD-1234?", "q"])
        printed_response = Mock()
        output = io.StringIO()

        with (
            patch.object(cli, "_startup", new=startup),
            patch.object(cli, "ask", new=ask),
            patch.object(cli, "_print_response", new=printed_response),
            patch("builtins.input", side_effect=lambda _prompt: next(inputs)),
            redirect_stdout(output),
        ):
            await cli._run()

        ask.assert_awaited_once_with("Where is ORD-1234?")
        printed_response.assert_called_once_with(response)
        self.assertIn("Goodbye!", output.getvalue())

    async def test_startup_environment_error_exits_with_status_one(self) -> None:
        with (
            patch.object(cli, "_startup", new=AsyncMock(side_effect=EnvironmentError("missing key"))),
            patch.object(cli.sys, "exit", side_effect=SystemExit) as exit_process,
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(SystemExit):
                await cli._run()

        exit_process.assert_called_once_with(1)

    async def test_eof_exits_cleanly(self) -> None:
        output = io.StringIO()

        with (
            patch.object(cli, "_startup", new=AsyncMock()),
            patch("builtins.input", side_effect=EOFError),
            redirect_stdout(output),
        ):
            await cli._run()

        self.assertIn("Goodbye!", output.getvalue())


if __name__ == "__main__":
    unittest.main()
