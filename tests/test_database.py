"""SQLite integration tests for the database layer."""

import re
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import aiosqlite

import database
from demo_clock import DEMO_NOW
from database import OrderNotFoundError, create_support_ticket, get_order, get_ticket_for_order, init_db


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._db_path = Path(self._temp_dir.name) / "support_agent_test.db"
        self._db_path_patch = patch.object(database, "DB_PATH", self._db_path)
        self._db_path_patch.start()
        await init_db()

    async def asyncTearDown(self) -> None:
        self._db_path_patch.stop()
        self._temp_dir.cleanup()

    async def test_initializes_and_seeds_orders_idempotently(self) -> None:
        await init_db()

        async with aiosqlite.connect(self._db_path) as connection:
            async with connection.execute("SELECT COUNT(*) FROM orders") as cursor:
                (count,) = await cursor.fetchone()

        self.assertEqual(count, 5)
        order = await get_order("ORD-1001")
        self.assertEqual(order.payment_status, "Pending")
        self.assertEqual(order.order_status, "Processing")
        self.assertEqual(order.product_category, "Electronics")
        self.assertIsNone(order.waybill_number)
        self.assertEqual(order.estimated_delivery, DEMO_NOW + timedelta(days=5))

    async def test_refreshes_sample_dates_without_deleting_tickets(self) -> None:
        ticket = await create_support_ticket("ORD-1003", "Keep this ticket")
        old_date = "2020-01-01T00:00:00+00:00"
        async with aiosqlite.connect(self._db_path) as connection:
            await connection.execute(
                "UPDATE orders SET created_at = ?, estimated_delivery = ? WHERE order_number = ?",
                (old_date, old_date, "ORD-1003"),
            )
            await connection.commit()

        await init_db()

        refreshed_order = await get_order("ORD-1003")
        saved_ticket = await get_ticket_for_order("ORD-1003")
        self.assertEqual(refreshed_order.created_at, DEMO_NOW - timedelta(days=5))
        self.assertEqual(refreshed_order.estimated_delivery, DEMO_NOW + timedelta(days=5))
        self.assertEqual(refreshed_order.order_status, "Shipped")
        self.assertIsNotNone(saved_ticket)
        self.assertEqual(saved_ticket.ticket_id, ticket.ticket_id)

    async def test_get_order_raises_for_unknown_order(self) -> None:
        with self.assertRaisesRegex(OrderNotFoundError, "ORD-missing"):
            await get_order("ORD-missing")

    async def test_creates_and_retrieves_support_ticket(self) -> None:
        ticket = await create_support_ticket("ORD-1003", "Delivery is delayed")

        self.assertRegex(ticket.ticket_id, r"^TKT-[0-9A-F]{8}$")
        self.assertEqual(ticket.order_number, "ORD-1003")
        self.assertEqual(ticket.reason, "Delivery is delayed")
        self.assertEqual(ticket.status, "Open")
        self.assertIsNotNone(ticket.created_at.tzinfo)

        saved_ticket = await get_ticket_for_order("ORD-1003")
        self.assertIsNotNone(saved_ticket)
        self.assertEqual(saved_ticket.ticket_id, ticket.ticket_id)
        self.assertEqual(saved_ticket.reason, ticket.reason)

    async def test_get_ticket_returns_none_when_no_ticket_exists(self) -> None:
        self.assertIsNone(await get_ticket_for_order("ORD-1001"))

    async def test_ticket_creation_rejects_unknown_order(self) -> None:
        with self.assertRaisesRegex(OrderNotFoundError, "ORD-missing"):
            await create_support_ticket("ORD-missing", "Cannot locate order")

    async def test_ticket_id_generator_returns_expected_format(self) -> None:
        self.assertRegex(database._generate_ticket_id(), re.compile(r"^TKT-[0-9A-F]{8}$"))


if __name__ == "__main__":
    unittest.main()
