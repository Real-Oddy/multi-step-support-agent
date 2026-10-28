"""Tests for the Streamlit session and chat workflow."""

import unittest
import sys
from contextlib import nullcontext
from types import ModuleType
from unittest.mock import Mock, patch

from models import AgentResponse


async def _placeholder(*_args, **_kwargs):
    raise NotImplementedError


# Keep this UI test independent of the agent provider and infrastructure imports.
_logger_stub = ModuleType("loguru")
_logger_stub.logger = Mock()
_streamlit_stub = ModuleType("streamlit")
_streamlit_stub.session_state = {}
_streamlit_stub.set_page_config = Mock()
_streamlit_stub.cache_resource = lambda **_options: lambda function: function
_agent_stub = ModuleType("agent")
_agent_stub.ask = _placeholder
_database_stub = ModuleType("database")
_database_stub.init_db = _placeholder
_rag_stub = ModuleType("rag")
_rag_stub.init_rag = _placeholder
with (
    patch.dict(
        sys.modules,
        {
            "loguru": _logger_stub,
            "streamlit": _streamlit_stub,
            "agent": _agent_stub,
            "database": _database_stub,
            "rag": _rag_stub,
        },
    ),
):
    import app as support_app


class SessionState(dict):
    """Dictionary with the attribute access Streamlit's session state supports."""

    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value) -> None:
        self[name] = value


class FakeStreamlit:
    def __init__(self, *, chat_input: str | None = None) -> None:
        self.session_state = SessionState()
        self.chat_input_value = chat_input
        self.chat_message = Mock(side_effect=lambda *_args, **_kwargs: nullcontext())
        self.spinner = Mock(side_effect=lambda *_args, **_kwargs: nullcontext())
        self.markdown = Mock()
        self.error = Mock()

    def __getattr__(self, name: str):
        if name == "chat_input":
            return Mock(return_value=self.chat_input_value)
        if name in {"title", "caption", "divider", "info", "warning", "success"}:
            return Mock()
        raise AttributeError(name)


class InitSessionTests(unittest.TestCase):
    def test_initializes_defaults_without_overwriting_existing_values(self) -> None:
        streamlit = FakeStreamlit()
        streamlit.session_state["messages"] = [{"role": "user", "content": "hello"}]
        streamlit.session_state["query_count"] = 3

        with patch.object(support_app, "st", streamlit):
            support_app._init_session()

        self.assertEqual(streamlit.session_state["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(streamlit.session_state["query_count"], 3)
        self.assertEqual(streamlit.session_state["escalation_count"], 0)


class InitSystemsTests(unittest.TestCase):
    def test_initializes_database_then_rag(self) -> None:
        run_calls = []

        def discard_coroutine(coroutine) -> None:
            run_calls.append(coroutine.cr_code.co_name)
            coroutine.close()

        async def init_db() -> None:
            pass

        async def init_rag() -> None:
            pass

        with (
            patch.object(support_app.asyncio, "run", side_effect=discard_coroutine),
            patch.object(support_app, "validate_api_keys") as mock_validator,
            patch.object(support_app, "init_db", new=init_db),
            patch.object(support_app, "init_rag", new=init_rag),
        ):
            result = support_app._init_systems()

        mock_validator.assert_called_once_with()
        self.assertTrue(result)
        self.assertEqual(run_calls, ["init_db", "init_rag"])


class RenderChatTests(unittest.TestCase):
    def test_returns_when_no_message_is_entered(self) -> None:
        streamlit = FakeStreamlit()
        streamlit.session_state.update(messages=[], query_count=0, escalation_count=0)

        with patch.object(support_app, "st", streamlit), patch.object(support_app, "ask") as ask:
            support_app._render_chat()

        ask.assert_not_called()
        self.assertEqual(streamlit.session_state["messages"], [])

    def test_appends_user_and_assistant_messages_and_updates_escalations(self) -> None:
        streamlit = FakeStreamlit(chat_input="Where is ORD-1234?")
        streamlit.session_state.update(messages=[], query_count=2, escalation_count=1)
        response = AgentResponse(
            order_number="ORD-1234",
            current_status="Delayed",
            explanation="The shipment is delayed.",
            recommended_action="A support agent will follow up.",
            escalation_required=True,
        )

        def return_response(coroutine):
            coroutine.close()
            return response

        with (
            patch.object(support_app, "st", streamlit),
            patch.object(support_app.asyncio, "run", side_effect=return_response) as run,
            patch.object(support_app, "_render_response_card") as render_card,
        ):
            support_app._render_chat()

        run.assert_called_once()
        run.assert_called_once()
        self.assertEqual(streamlit.session_state.query_count, 3)
        self.assertEqual(streamlit.session_state.escalation_count, 2)
        self.assertEqual(streamlit.session_state.messages[0], {
            "role": "user",
            "content": "Where is ORD-1234?",
        })
        self.assertEqual(streamlit.session_state.messages[1]["role"], "assistant")
        self.assertIs(streamlit.session_state.messages[1]["response"], response)
        render_card.assert_called_once_with(response)

    def test_shows_agent_exception_without_incrementing_stats(self) -> None:
        streamlit = FakeStreamlit(chat_input="Where is ORD-1234?")
        streamlit.session_state.update(messages=[], query_count=0, escalation_count=0)

        def fail_run(coroutine):
            coroutine.close()
            raise RuntimeError("agent offline")

        with (
            patch.object(support_app, "st", streamlit),
            patch.object(support_app.asyncio, "run", side_effect=fail_run),
        ):
            support_app._render_chat()

        streamlit.error.assert_called_once()
        self.assertIn("agent offline", streamlit.error.call_args.args[0])
        self.assertEqual(streamlit.session_state.query_count, 0)
        self.assertEqual(streamlit.session_state.escalation_count, 0)


if __name__ == "__main__":
    unittest.main()
