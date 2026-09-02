"""
rag.py
------
Return policy knowledge base using OpenAI embeddings + ChromaDB.

Provides two public async functions:
  init_rag()                — Embed and persist all policy documents (idempotent).
  get_return_policy(cat)    — Retrieve the most relevant policy for a product category.

OpenAI's text-embedding-3-small model is used for both indexing and retrieval.
ChromaDB stores vectors with cosine similarity.
"""

from __future__ import annotations

import os
from pathlib import Path

import chromadb
from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHROMA_PATH: Path = Path(
    os.getenv("CHROMA_PATH", str(Path(__file__).parent / "chroma_store"))
)
COLLECTION_NAME: str = "return_policies"
EMBEDDING_MODEL: str = "text-embedding-3-small"  # 1536 dims, cost-efficient
TOP_K: int = 1  # Return only the single most relevant policy document

# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class RAGNotInitializedError(RuntimeError):
    """Raised when get_return_policy() is called before init_rag()."""


# ---------------------------------------------------------------------------
# Policy documents
#
# Each dict maps to one ChromaDB document. The 'category' field is stored as
# metadata for logging/debugging — retrieval itself is purely vector-based,
# so semantically related queries (e.g. "gadgets", "phones") still resolve
# to the correct policy without requiring an exact category name match.
# ---------------------------------------------------------------------------

_POLICIES: list[dict[str, str]] = [
    {
        "id": "policy-electronics",
        "category": "Electronics",
        "text": (
            "Electronics Return Policy: Customers may return electronics within 30 days "
            "of the delivery date. Items must be in their original, unused condition and "
            "returned in all original packaging including accessories, manuals, and warranty "
            "cards. Devices that have been activated, registered, or show any signs of use "
            "are not eligible for a full refund. Software, digital downloads, and consumable "
            "items such as batteries sold separately are non-returnable once opened. A 15% "
            "restocking fee applies to opened electronics returned within the 30-day window. "
            "Defective items are eligible for a full replacement or refund within 30 days "
            "regardless of packaging condition, provided a fault report is submitted at the "
            "time of return. Refunds are processed within 5 to 7 business days after the "
            "returned item is inspected and approved."
        ),
    },
    {
        "id": "policy-clothing",
        "category": "Clothing",
        "text": (
            "Clothing and Apparel Return Policy: Unworn clothing items with all original tags "
            "still attached may be returned within 14 days of the delivery date for a full "
            "refund or store credit. Items must be unwashed, unaltered, and free from odours, "
            "stains, or any damage. Swimwear, lingerie, and pierced jewellery are non-returnable "
            "for hygiene reasons. Sale or clearance items are final sale and cannot be returned "
            "or exchanged unless they arrive damaged or defective. Customers are responsible for "
            "return shipping costs unless the item was received damaged or incorrect. Exchanges "
            "for a different size or colour are permitted within 14 days subject to stock "
            "availability. Refunds are issued to the original payment method within 3 to 5 "
            "business days after inspection is complete."
        ),
    },
    {
        "id": "policy-furniture",
        "category": "Furniture",
        "text": (
            "Furniture Return Policy: Furniture items may be returned within 7 days of delivery, "
            "provided the item is disassembled where applicable and returned in its original "
            "packaging in an undamaged condition. Custom-made, built-to-order, or personalised "
            "furniture pieces are strictly non-returnable. Items that have been assembled and "
            "show signs of use, surface scratches, or any modification are not eligible for a "
            "refund. A collection and restocking fee of 20% of the purchase price will be "
            "deducted from the refund on all standard furniture returns. Damaged or defective "
            "furniture must be reported with photographic evidence within 48 hours of delivery "
            "to qualify for a free replacement or full refund. Refunds are processed within 7 "
            "to 10 business days once the item has been collected and inspected at the warehouse."
        ),
    },
    {
        "id": "policy-general",
        "category": "General",
        "text": (
            "General Return Policy: Most items may be returned within 30 days of the delivery "
            "date for a full refund, provided they are unused, in their original condition, and "
            "include all original packaging and accessories. Items damaged through customer "
            "misuse, lost return shipments, or returned after the 30-day window are not eligible "
            "for a refund. To initiate a return, customers must contact support with their order "
            "number and reason for return. Once a return is approved, a prepaid shipping label "
            "will be provided. Refunds are credited to the original payment method within 5 to 7 "
            "business days after the returned item passes inspection. Items explicitly marked as "
            "non-returnable on their product listing are excluded from this policy."
        ),
    },
]

# ---------------------------------------------------------------------------
# Module-level singletons — set once by init_rag(), used by get_return_policy()
# ---------------------------------------------------------------------------

_collection: chromadb.Collection | None = None
_openai_client: AsyncOpenAI | None = None

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def init_rag() -> None:
    """
    Initialise the RAG knowledge base.

    Workflow:
      1. Validate the OPENAI_API_KEY environment variable.
      2. Connect to (or create) a persistent ChromaDB collection.
      3. If the collection is already fully populated, skip embedding.
      4. Otherwise embed all policy documents via OpenAI and persist them.

    Safe to call on every application startup — fully idempotent.

    Raises:
        EnvironmentError: If ``OPENAI_API_KEY`` is missing from the environment.
    """
    global _collection, _openai_client

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY is not set. Add it to your .env file."
        )

    _openai_client = AsyncOpenAI(api_key=api_key)

    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    _collection = chroma_client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},  # cosine similarity — standard for text
    )

    existing_count = _collection.count()
    if existing_count >= len(_POLICIES):
        logger.info(
            f"RAG collection '{COLLECTION_NAME}' already has {existing_count} "
            f"document(s). Skipping embed step."
        )
        return

    logger.info(
        f"Embedding {len(_POLICIES)} policy documents "
        f"via OpenAI (model={EMBEDDING_MODEL})..."
    )

    texts: list[str] = [p["text"] for p in _POLICIES]

    embed_result = await _openai_client.embeddings.create(
        input=texts,
        model=EMBEDDING_MODEL,
    )
    embeddings: list[list[float]] = [item.embedding for item in embed_result.data]

    _collection.add(
        ids=[p["id"] for p in _POLICIES],
        embeddings=embeddings,
        documents=texts,
        metadatas=[{"category": p["category"]} for p in _POLICIES],
    )

    logger.info(
        f"RAG ready | collection='{COLLECTION_NAME}' | "
        f"documents={len(_POLICIES)} | model={EMBEDDING_MODEL}"
    )


async def get_return_policy(category: str) -> str:
    """
    Retrieve the most relevant return policy for a given product category.

    The category string is embedded as a query vector and compared against
    all stored policy documents using cosine similarity. Fuzzy matches work
    correctly — e.g. querying ``'Phones'`` returns the Electronics policy
    without requiring an exact category name match.

    Args:
        category: Product category string, e.g. ``'Electronics'``, ``'Clothing'``.

    Returns:
        The full text of the most relevant return policy document.

    Raises:
        RAGNotInitializedError: If :func:`init_rag` has not been called first.
    """
    if _collection is None or _openai_client is None:
        raise RAGNotInitializedError(
            "RAG is not initialised. Ensure init_rag() is awaited at startup."
        )

    logger.debug(f"RAG query | input='{category}'")

    query_embed_result = await _openai_client.embeddings.create(
        input=[category],
        model=EMBEDDING_MODEL,
    )
    query_vector: list[float] = query_embed_result.data[0].embedding

    results = _collection.query(
        query_embeddings=[query_vector],
        n_results=TOP_K,
        include=["documents", "metadatas", "distances"],
    )

    # results["documents"] is List[List[str]] — outer list = one entry per query
    top_document: str = results["documents"][0][0]
    top_metadata: dict = results["metadatas"][0][0]
    top_distance: float = results["distances"][0][0]

    logger.info(
        f"RAG result | matched='{top_metadata['category']}' | "
        f"cosine_distance={top_distance:.4f}"
    )

    return top_document
