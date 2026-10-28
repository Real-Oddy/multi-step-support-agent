"""Run the test suite with external RAG services replaced by local test doubles."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(ROOT))


def _install_external_service_stubs() -> None:
    """Stub network-backed integrations that unit tests replace with mocks."""
    chromadb = ModuleType("chromadb")
    chromadb.PersistentClient = Mock()
    openai = ModuleType("openai")
    openai.AsyncOpenAI = Mock()
    sys.modules["chromadb"] = chromadb
    sys.modules["openai"] = openai


if __name__ == "__main__":
    _install_external_service_stubs()
    raise SystemExit(pytest.main(["-v", str(TESTS)]))
