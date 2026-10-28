"""Tests for return-policy retrieval and RAG initialization."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import rag
from rag import RAGNotInitializedError, get_return_policy, init_rag


class InitRAGTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        rag._collection = None
        rag._openai_client = None

    def tearDown(self) -> None:
        rag._collection = None
        rag._openai_client = None

    async def test_requires_openai_api_key(self) -> None:
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
            patch.object(rag, "AsyncOpenAI") as openai_client,
        ):
            with self.assertRaisesRegex(EnvironmentError, "OPENAI_API_KEY is not set"):
                await init_rag()

        openai_client.assert_not_called()

    async def test_embeds_and_stores_policies_when_collection_is_empty(self) -> None:
        collection = Mock()
        collection.count.return_value = 0
        client = Mock()
        client.get_or_create_collection.return_value = collection
        embeddings = Mock()
        embeddings.create = AsyncMock(
            return_value=SimpleNamespace(
                data=[SimpleNamespace(embedding=[float(i)]) for i in range(len(rag._POLICIES))]
            )
        )
        openai_client = Mock(embeddings=embeddings)

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch.object(rag, "AsyncOpenAI", return_value=openai_client) as create_openai,
            patch.object(rag.chromadb, "PersistentClient", return_value=client) as create_chroma,
        ):
            await init_rag()

        self.assertIs(rag._collection, collection)
        self.assertIs(rag._openai_client, openai_client)
        create_openai.assert_called_once_with(api_key="test-key")
        create_chroma.assert_called_once_with(path=str(rag.CHROMA_PATH))
        client.get_or_create_collection.assert_called_once_with(
            name=rag.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        embeddings.create.assert_awaited_once_with(
            input=[policy["text"] for policy in rag._POLICIES],
            model=rag.EMBEDDING_MODEL,
        )
        collection.add.assert_called_once_with(
            ids=[policy["id"] for policy in rag._POLICIES],
            embeddings=[[float(i)] for i in range(len(rag._POLICIES))],
            documents=[policy["text"] for policy in rag._POLICIES],
            metadatas=[{"category": policy["category"]} for policy in rag._POLICIES],
        )

    async def test_skips_embedding_when_collection_is_already_populated(self) -> None:
        collection = Mock()
        collection.count.return_value = len(rag._POLICIES)
        client = Mock()
        client.get_or_create_collection.return_value = collection
        embeddings = Mock()
        embeddings.create = AsyncMock()
        openai_client = Mock(embeddings=embeddings)

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch.object(rag, "AsyncOpenAI", return_value=openai_client),
            patch.object(rag.chromadb, "PersistentClient", return_value=client),
        ):
            await init_rag()

        embeddings.create.assert_not_awaited()
        collection.add.assert_not_called()


class GetReturnPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        rag._collection = None
        rag._openai_client = None

    def tearDown(self) -> None:
        rag._collection = None
        rag._openai_client = None

    async def test_raises_when_rag_has_not_been_initialized(self) -> None:
        with self.assertRaises(RAGNotInitializedError):
            await get_return_policy("Electronics")

    async def test_embeds_query_and_returns_top_matching_document(self) -> None:
        policy_text = "Electronics return policy text."
        embeddings = Mock()
        embeddings.create = AsyncMock(
            return_value=SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
        )
        openai_client = Mock(embeddings=embeddings)
        collection = Mock()
        collection.query.return_value = {
            "documents": [[policy_text]],
            "metadatas": [[{"category": "Electronics"}]],
            "distances": [[0.12]],
        }
        rag._openai_client = openai_client
        rag._collection = collection

        result = await get_return_policy("Phones")

        self.assertEqual(result, policy_text)
        embeddings.create.assert_awaited_once_with(
            input=["Phones"],
            model=rag.EMBEDDING_MODEL,
        )
        collection.query.assert_called_once_with(
            query_embeddings=[[0.1, 0.2]],
            n_results=rag.TOP_K,
            include=["documents", "metadatas", "distances"],
        )


if __name__ == "__main__":
    unittest.main()
