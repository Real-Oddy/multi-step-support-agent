"""Run unit tests with external RAG services replaced by local test doubles."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock


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
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(TESTS),
        pattern="test*.py",
        top_level_dir=str(TESTS),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
