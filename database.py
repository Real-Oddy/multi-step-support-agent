"""
database.py
-----------
SQLite database layer for the Multi-Step Order Support Agent.

Responsibilities:
  - Schema creation (idempotent — safe to call on every startup).
  - Seeding deterministic mock order data on first run.
  - Async CRUD operations for `orders` and `support_tickets` tables.

All public functions are async and use aiosqlite.
All SQL is parameterised — no string-interpolated queries.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import AsyncIterator

import aiosqlite
from loguru import logger

from models import OrderRecord, SupportTicket

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(
    os.getenv("DB_PATH", str(Path(__file__).parent / "support_agent.db"))
)

# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class OrderNotFoundError(Exception):
    """Raised when an order number does not exist in the database."""


class TicketCreationError(Exception):
    """Raised when a support ticket cannot be persisted."""


# ---------------------------------------------------------------------------
# DDL — table schemas (CHECK constraints enforce valid enum values at DB level)
# ---------------------------------------------------------------------------

_CREATE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS orders (
    order_number        TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL,
    payment_status      TEXT NOT NULL
                        CHECK(payment_status IN ('Pending', 'Paid')),
    order_status        TEXT NOT NULL
                        CHECK(order_status IN ('Processing', 'Shipped', 'Delivered', 'Cancelled')),
    waybill_number      TEXT,
    product_category    TEXT NOT NULL DEFAULT 'General',
    created_at          TEXT NOT NULL,
    estimated_delivery  TEXT
);
"""

_CREATE_TICKETS_TABLE = """
CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id       TEXT PRIMARY KEY,
    order_number    TEXT NOT NULL REFERENCES orders(order_number),
    reason          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'Open'
                    CHECK(status IN ('Open', 'In Progress', 'Resolved', 'Closed')),
    created_at      TEXT NOT NULL
);
"""

# ---------------------------------------------------------------------------
# Seed data — five deterministic mock orders covering all business-rule paths
# ---------------------------------------------------------------------------

_SEED_ORDERS: list[dict] = [
    # Cancellable: Processing + Pending payment
    {
        "order_number": "ORD-1001",
        "customer_id": "CUST-001",
        "payment_status": "Pending",
        "order_status": "Processing",
        "waybill_number": None,
        "product_category": "Electronics",
        "created_at": "2026-08-20T09:00:00+00:00",
        "estimated_delivery": None,
    },
    # NOT cancellable: Processing but payment already Paid
    {
        "order_number": "ORD-1002",
        "customer_id": "CUST-002",
        "payment_status": "Paid",
        "order_status": "Processing",
        "waybill_number": None,
        "product_category": "Clothing",
        "created_at": "2026-08-21T10:00:00+00:00",
        "estimated_delivery": None,
    },
    # Shipped — on time (ETA in the future)
    {
        "order_number": "ORD-1003",
        "customer_id": "CUST-003",
        "payment_status": "Paid",
        "order_status": "Shipped",
        "waybill_number": "WB-5001",
        "product_category": "Electronics",
        "created_at": "2026-08-18T08:00:00+00:00",
        "estimated_delivery": "2026-08-30T18:00:00+00:00",
    },
    # Shipped — DELAYED (ETA passed by > 3 days; triggers auto-escalation)
    {
        "order_number": "ORD-1004",
        "customer_id": "CUST-004",
        "payment_status": "Paid",
        "order_status": "Shipped",
        "waybill_number": "WB-5002",
        "product_category": "Furniture",
        "created_at": "2026-08-10T08:00:00+00:00",
        "estimated_delivery": "2026-08-19T18:00:00+00:00",  # 7 days overdue
    },
    # Delivered — no further action required
    {
        "order_number": "ORD-1005",
        "customer_id": "CUST-005",
        "payment_status": "Paid",
        "order_status": "Delivered",
        "waybill_number": "WB-5003",
        "product_category": "Clothing",
        "created_at": "2026-08-12T07:00:00+00:00",
        "estimated_delivery": "2026-08-22T18:00:00+00:00",
    },
]

# ---------------------------------------------------------------------------
# Internal helpers — NOT part of the public API
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _get_connection() -> AsyncIterator[aiosqlite.Connection]:
    """
    Async context manager that yields a configured aiosqlite connection.

    Settings applied per connection:
      - WAL journal mode   : better read concurrency.
      - Foreign keys ON    : enforce referential integrity.
      - Row factory        : rows accessible by column name.
    """
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        yield conn


def _row_to_order(row: aiosqlite.Row) -> OrderRecord:
    """Map a raw aiosqlite Row to a validated OrderRecord."""
    return OrderRecord(
        order_number=row["order_number"],
        customer_id=row["customer_id"],
        payment_status=row["payment_status"],
        order_status=row["order_status"],
        waybill_number=row["waybill_number"],
        product_category=row["product_category"],
        created_at=datetime.fromisoformat(row["created_at"]),
        estimated_delivery=(
            datetime.fromisoformat(row["estimated_delivery"])
            if row["estimated_delivery"]
            else None
        ),
    )


def _row_to_ticket(row: aiosqlite.Row) -> SupportTicket:
    """Map a raw aiosqlite Row to a validated SupportTicket."""
    return SupportTicket(
        ticket_id=row["ticket_id"],
        order_number=row["order_number"],
        reason=row["reason"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def _generate_ticket_id() -> str:
    """Return a short, unique, prefixed ticket ID — e.g. 'TKT-3F9A2C1B'."""
    return f"TKT-{uuid.uuid4().hex[:8].upper()}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def init_db() -> None:
    """
    Initialise the database.

    Creates the `orders` and `support_tickets` tables if they do not already
    exist, then seeds mock order data on the very first run.  Safe to call
    on every application startup — fully idempotent.
    """
    async with _get_connection() as conn:
        await conn.execute(_CREATE_ORDERS_TABLE)
        await conn.execute(_CREATE_TICKETS_TABLE)
        await conn.commit()
        logger.info("Database schema ready.")

        async with conn.execute("SELECT COUNT(*) FROM orders") as cursor:
            (count,) = await cursor.fetchone()

        if count == 0:
            await conn.executemany(
                """
                INSERT INTO orders (
                    order_number, customer_id, payment_status, order_status,
                    waybill_number, product_category, created_at, estimated_delivery
                ) VALUES (
                    :order_number, :customer_id, :payment_status, :order_status,
                    :waybill_number, :product_category, :created_at, :estimated_delivery
                )
                """,
                _SEED_ORDERS,
            )
            await conn.commit()
            logger.info(f"Seeded {len(_SEED_ORDERS)} mock orders.")
        else:
            logger.debug(f"Skipping seed — database already has {count} order(s).")


async def get_order(order_number: str) -> OrderRecord:
    """
    Retrieve a single order by its order number.

    Args:
        order_number: The order identifier, e.g. ``'ORD-1234'``.

    Returns:
        A fully validated :class:`~models.OrderRecord`.

    Raises:
        OrderNotFoundError: If no order matches the given number.
    """
    async with _get_connection() as conn:
        async with conn.execute(
            "SELECT * FROM orders WHERE order_number = ?",
            (order_number,),
        ) as cursor:
            row = await cursor.fetchone()

    if row is None:
        raise OrderNotFoundError(
            f"Order '{order_number}' was not found in the database."
        )

    order = _row_to_order(row)
    logger.debug(
        f"Fetched {order.order_number} | "
        f"status={order.order_status} | payment={order.payment_status}"
    )
    return order


async def create_support_ticket(order_number: str, reason: str) -> SupportTicket:
    """
    Create and persist a new support ticket linked to an order.

    Args:
        order_number: The order identifier this ticket relates to.
        reason: Human-readable description of why the ticket was raised.

    Returns:
        The newly created :class:`~models.SupportTicket`.

    Raises:
        OrderNotFoundError: If the referenced order does not exist.
        TicketCreationError: If the insert fails for any other reason.
    """
    ticket = SupportTicket(
        ticket_id=_generate_ticket_id(),
        order_number=order_number,
        reason=reason,
        status="Open",
        created_at=datetime.now(tz=timezone.utc),
    )

    async with _get_connection() as conn:
        try:
            await conn.execute(
                """
                INSERT INTO support_tickets
                    (ticket_id, order_number, reason, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    ticket.ticket_id,
                    ticket.order_number,
                    ticket.reason,
                    ticket.status,
                    ticket.created_at.isoformat(),
                ),
            )
            await conn.commit()
        except aiosqlite.IntegrityError as exc:
            # FK violation means the order_number doesn't exist
            raise OrderNotFoundError(
                f"Cannot create ticket — order '{order_number}' does not exist."
            ) from exc
        except aiosqlite.Error as exc:
            raise TicketCreationError(
                f"Failed to persist ticket for order '{order_number}'."
            ) from exc

    logger.info(
        f"Support ticket created | id={ticket.ticket_id} | "
        f"order={order_number} | reason='{reason}'"
    )
    return ticket


async def get_ticket_for_order(order_number: str) -> SupportTicket | None:
    """
    Return the most recent open support ticket for an order, or ``None``.

    Args:
        order_number: The order identifier to look up.

    Returns:
        The most recent :class:`~models.SupportTicket`, or ``None`` if the
        order has no tickets.
    """
    async with _get_connection() as conn:
        async with conn.execute(
            """
            SELECT * FROM support_tickets
            WHERE  order_number = ?
            ORDER  BY created_at DESC
            LIMIT  1
            """,
            (order_number,),
        ) as cursor:
            row = await cursor.fetchone()

    if row is None:
        logger.debug(f"No support ticket found for order '{order_number}'.")
        return None

    ticket = _row_to_ticket(row)
    logger.debug(f"Found ticket {ticket.ticket_id} for order '{order_number}'.")
    return ticket
