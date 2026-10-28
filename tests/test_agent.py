"""Tests for the PydanticAI agent wrapper and tool trace extraction."""

import unittest
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from unittest.async_case import IsolatedAsyncioTestCase

from models import AgentResponse


class _ToolCallPart:
    def __init__(self, tool_name: str, args=None, tool_call_id: str = "call") -> None:
        self.tool_name = tool_name
        self.tool_kind = None
        self.args = args
        self.tool_call_id = tool_call_id


class _FakeAgent:
    def __class_getitem__(cls, _item):
        return cls

    def __init__(self, **configuration) -> None:
        self.configuration = configuration

    async def run(self, _user_message: str):
        raise NotImplementedError


class _FakeAnthropicModel:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name


async def _placeholder_tool(*_args, **_kwargs):
    raise NotImplementedError


# The agent module constructs its provider at import time. Stub only those
# boundaries here; these unit tests exercise trace parsing and ask() behavior.
_pydantic_ai = ModuleType("pydantic_ai")
_pydantic_ai.__path__ = []
_pydantic_ai.Agent = _FakeAgent
_messages = ModuleType("pydantic_ai.messages")
_messages.ToolCallPart = type("ToolCallPart", (_ToolCallPart,), {})
_messages.NativeToolCallPart = type("NativeToolCallPart", (_ToolCallPart,), {})
_models = ModuleType("pydantic_ai.models")
_models.__path__ = []
_anthropic = ModuleType("pydantic_ai.models.anthropic")
_anthropic.AnthropicModel = _FakeAnthropicModel
_tools_stub = ModuleType("tools")
for _tool_name in ("fetch_return_policy", "lookup_order", "open_support_ticket", "track_shipment"):
    setattr(_tools_stub, _tool_name, _placeholder_tool)
_logger_stub = ModuleType("loguru")
_logger_stub.logger = Mock()
with (
    patch.dict(
        sys.modules,
        {
            "loguru": _logger_stub,
            "pydantic_ai": _pydantic_ai,
            "pydantic_ai.messages": _messages,
            "pydantic_ai.models": _models,
            "pydantic_ai.models.anthropic": _anthropic,
            "tools": _tools_stub,
        },
    )
):
    import agent as support_agent


class ExtractToolTraceTests(unittest.TestCase):
    def test_extracts_ordered_tool_names_from_both_call_formats(self) -> None:
        regular_call = support_agent.ToolCallPart(
            "lookup_order", {"order_number": "ORD-1234"}, "call-1"
        )
        native_call = support_agent.NativeToolCallPart(
            "track_shipment", {"waybill_number": "WB-987"}, "call-2"
        )
        messages = [
            SimpleNamespace(parts=[regular_call, object()]),
            SimpleNamespace(parts=[native_call]),
        ]

        self.assertEqual(
            support_agent._extract_tool_trace(messages),
            ["lookup_order", "track_shipment"],
        )

    def test_ignores_messages_without_tool_calls(self) -> None:
        messages = [SimpleNamespace(parts=[object()]), SimpleNamespace()]

        self.assertEqual(support_agent._extract_tool_trace(messages), [])


class AskTests(IsolatedAsyncioTestCase):
    async def test_runs_agent_and_returns_structured_output(self) -> None:
        response = AgentResponse(
            order_number="ORD-1234",
            current_status="Shipped",
            explanation="The order is in transit.",
            recommended_action="Continue tracking the shipment.",
        )
        result = SimpleNamespace(
            output=response,
            all_messages=lambda: [],
            usage=SimpleNamespace(input_tokens=10, output_tokens=20, total_tokens=30),
        )
        run = AsyncMock(return_value=result)

        with patch.object(support_agent.agent, "run", run):
            actual = await support_agent.ask("Where is ORD-1234?")

        self.assertIs(actual, response)
        run.assert_awaited_once_with("Where is ORD-1234?")

    async def test_passes_tool_history_to_trace_logger(self) -> None:
        response = AgentResponse(
            order_number="ORD-1234",
            current_status="Shipped",
            explanation="The order is in transit.",
            recommended_action="Continue tracking the shipment.",
        )
        result = SimpleNamespace(
            output=response,
            all_messages=lambda: ["agent message"],
            usage=SimpleNamespace(input_tokens=1, output_tokens=2, total_tokens=3),
        )

        with (
            patch.object(support_agent.agent, "run", new=AsyncMock(return_value=result)),
            patch.object(support_agent, "_extract_tool_trace", return_value=["lookup_order"]) as trace,
            patch.object(support_agent.logger, "info") as log_info,
        ):
            actual = await support_agent.ask("Check ORD-1234")

        self.assertIs(actual, response)
        trace.assert_called_once_with(["agent message"])
        self.assertTrue(
            any("lookup_order" in str(call.args[0]) for call in log_info.call_args_list)
        )


if __name__ == "__main__":
    unittest.main()
