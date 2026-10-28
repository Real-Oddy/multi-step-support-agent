"""Tests for the async customer support tools."""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from database import OrderNotFoundError, TicketCreationError
from models import OrderRecord, SupportTicket, TrackingEvent, TrackingResult
from mock_logistics_api import WaybillNotFoundError
from rag import RAGNotInitializedError
from tools import fetch_return_policy, lookup_order, open_support_ticket, track_shipment


class LookupOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_formats_order_details(self) -> None:
        order = OrderRecord(
            order_number="ORD-1234",
            customer_id="CUS-42",
            payment_status="Paid",
            order_status="Shipped",
            waybill_number="WB-987",
            product_category="Electronics",
            created_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
            estimated_delivery=datetime(2026, 1, 5, tzinfo=timezone.utc),
        )

        with patch("tools.get_order", new=AsyncMock(return_value=order)) as get_order:
            result = await lookup_order("ORD-1234")

        get_order.assert_awaited_once_with("ORD-1234")
        self.assertIn("Order Number      : ORD-1234", result)
        self.assertIn("Customer ID       : CUS-42", result)
        self.assertIn("Order Status      : Shipped", result)
        self.assertIn("Payment Status    : Paid", result)
        self.assertIn("Product Category  : Electronics", result)
        self.assertIn("Waybill Number    : WB-987", result)
        self.assertIn("Estimated Delivery: 2026-01-05", result)

    async def test_formats_missing_optional_order_details(self) -> None:
        order = OrderRecord(
            order_number="ORD-1234",
            customer_id="CUS-42",
            payment_status="Pending",
            order_status="Processing",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )

        with patch("tools.get_order", new=AsyncMock(return_value=order)):
            result = await lookup_order("ORD-1234")

        self.assertIn("Waybill Number    : Not yet dispatched", result)
        self.assertIn("Estimated Delivery: N/A", result)

    async def test_returns_plain_language_message_when_order_is_missing(self) -> None:
        with patch("tools.get_order", new=AsyncMock(side_effect=OrderNotFoundError)):
            result = await lookup_order("ORD-missing")

        self.assertIn("Order 'ORD-missing' was not found", result)
        self.assertIn("verify the order number", result)


class TrackShipmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_formats_tracking_events_and_delay_status(self) -> None:
        tracking = TrackingResult(
            waybill_number="WB-987",
            events=[
                TrackingEvent(
                    timestamp=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
                    location="Lagos Hub",
                    status="In transit",
                )
            ],
            estimated_delivery=datetime(2026, 1, 5, tzinfo=timezone.utc),
            is_delayed=True,
            current_location="Lagos Hub",
        )

        with patch("tools.get_tracking_info", new=AsyncMock(return_value=tracking)) as get_tracking:
            result = await track_shipment("WB-987")

        get_tracking.assert_awaited_once_with("WB-987")
        self.assertIn("Waybill           : WB-987", result)
        self.assertIn("Current Location  : Lagos Hub", result)
        self.assertIn("Estimated Delivery: 2026-01-05", result)
        self.assertIn("Delayed           : YES", result)
        self.assertIn("Lagos Hub — In transit", result)

    async def test_formats_empty_tracking_result(self) -> None:
        tracking = TrackingResult(waybill_number="WB-987")

        with patch("tools.get_tracking_info", new=AsyncMock(return_value=tracking)):
            result = await track_shipment("WB-987")

        self.assertIn("Current Location  : Unknown", result)
        self.assertIn("Estimated Delivery: Unknown", result)
        self.assertIn("Delayed           : No", result)
        self.assertIn("No checkpoint events recorded yet.", result)

    async def test_returns_plain_language_message_when_waybill_is_missing(self) -> None:
        with patch("tools.get_tracking_info", new=AsyncMock(side_effect=WaybillNotFoundError)):
            result = await track_shipment("WB-missing")

        self.assertIn("Waybill 'WB-missing' was not found", result)
        self.assertIn("may not yet be registered", result)


class FetchReturnPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_policy_text(self) -> None:
        policy = "Electronics may be returned within 30 days."

        with patch("tools.get_return_policy", new=AsyncMock(return_value=policy)) as get_policy:
            result = await fetch_return_policy("Electronics")

        get_policy.assert_awaited_once_with("Electronics")
        self.assertEqual(result, policy)

    async def test_reports_when_rag_is_not_initialized(self) -> None:
        with patch("tools.get_return_policy", new=AsyncMock(side_effect=RAGNotInitializedError)):
            result = await fetch_return_policy("Electronics")

        self.assertIn("temporarily unavailable", result)
        self.assertIn("contact our support team", result)


class OpenSupportTicketTests(unittest.IsolatedAsyncioTestCase):
    async def test_formats_ticket_creation_confirmation(self) -> None:
        ticket = SupportTicket(
            ticket_id="TKT-ABC12345",
            order_number="ORD-1234",
            reason="Delivery delay",
            created_at=datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        )

        with patch("tools.create_support_ticket", new=AsyncMock(return_value=ticket)) as create_ticket:
            result = await open_support_ticket("ORD-1234", "Delivery delay")

        create_ticket.assert_awaited_once_with("ORD-1234", "Delivery delay")
        self.assertIn("Support ticket successfully created.", result)
        self.assertIn("Ticket ID    : TKT-ABC12345", result)
        self.assertIn("Order Number : ORD-1234", result)
        self.assertIn("Reason       : Delivery delay", result)
        self.assertIn("Status       : Open", result)

    async def test_reports_missing_order_when_ticket_cannot_be_created(self) -> None:
        with patch("tools.create_support_ticket", new=AsyncMock(side_effect=OrderNotFoundError)):
            result = await open_support_ticket("ORD-missing", "Delivery delay")

        self.assertIn("order 'ORD-missing' does not exist", result)
        self.assertIn("Verify the order number", result)

    async def test_reports_database_error_when_ticket_creation_fails(self) -> None:
        with patch(
            "tools.create_support_ticket",
            new=AsyncMock(side_effect=TicketCreationError("database unavailable")),
        ):
            result = await open_support_ticket("ORD-1234", "Delivery delay")

        self.assertIn("A database error occurred", result)
        self.assertIn("Escalation must be handled manually", result)


if __name__ == "__main__":
    unittest.main()
