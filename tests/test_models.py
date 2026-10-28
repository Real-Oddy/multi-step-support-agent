"""Tests for the Pydantic data models in :mod:`models`."""

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from models import (
    AgentResponse,
    OrderRecord,
    SupportTicket,
    TrackingEvent,
    TrackingResult,
)


class AgentResponseTests(unittest.TestCase):
    def test_requires_response_fields_and_defaults_escalation(self) -> None:
        response = AgentResponse(
            order_number="ORD-1234",
            current_status="Shipped",
            explanation="Your order is on its way.",
            recommended_action="Track the shipment online.",
        )

        self.assertFalse(response.escalation_required)

    def test_accepts_explicit_escalation_value(self) -> None:
        response = AgentResponse(
            order_number="ORD-1234",
            current_status="Delayed",
            explanation="The delivery is delayed.",
            recommended_action="A support agent will follow up.",
            escalation_required=True,
        )

        self.assertTrue(response.escalation_required)

    def test_rejects_missing_required_field(self) -> None:
        with self.assertRaises(ValidationError):
            AgentResponse(
                order_number="ORD-1234",
                current_status="Shipped",
                explanation="Your order is on its way.",
            )


class OrderRecordTests(unittest.TestCase):
    def test_optional_fields_use_documented_defaults(self) -> None:
        created_at = datetime(2026, 1, 2, 3, 4)
        order = OrderRecord(
            order_number="ORD-1234",
            customer_id="CUS-42",
            payment_status="Paid",
            order_status="Shipped",
            created_at=created_at,
        )

        self.assertIsNone(order.waybill_number)
        self.assertEqual(order.product_category, "General")
        self.assertIsNone(order.estimated_delivery)
        self.assertEqual(order.created_at, created_at)

    def test_accepts_all_supported_statuses(self) -> None:
        for payment_status in ("Pending", "Paid"):
            for order_status in ("Processing", "Shipped", "Delivered", "Cancelled"):
                with self.subTest(payment_status=payment_status, order_status=order_status):
                    order = OrderRecord(
                        order_number="ORD-1234",
                        customer_id="CUS-42",
                        payment_status=payment_status,
                        order_status=order_status,
                        created_at=datetime(2026, 1, 2),
                    )
                    self.assertEqual(order.payment_status, payment_status)
                    self.assertEqual(order.order_status, order_status)

    def test_rejects_unsupported_status_values(self) -> None:
        with self.assertRaises(ValidationError):
            OrderRecord(
                order_number="ORD-1234",
                customer_id="CUS-42",
                payment_status="Refunded",
                order_status="Shipped",
                created_at=datetime(2026, 1, 2),
            )


class SupportTicketTests(unittest.TestCase):
    def test_defaults_to_open_with_creation_timestamp(self) -> None:
        before_creation = datetime.now(timezone.utc)
        ticket = SupportTicket(
            ticket_id="TKT-0001",
            order_number="ORD-1234",
            reason="Delivery delay",
        )
        after_creation = datetime.now(timezone.utc)

        self.assertEqual(ticket.status, "Open")
        self.assertGreaterEqual(ticket.created_at, before_creation)
        self.assertLessEqual(ticket.created_at, after_creation)

    def test_accepts_supported_ticket_statuses(self) -> None:
        for status in ("Open", "In Progress", "Resolved", "Closed"):
            with self.subTest(status=status):
                ticket = SupportTicket(
                    ticket_id="TKT-0001",
                    order_number="ORD-1234",
                    reason="Delivery delay",
                    status=status,
                )
                self.assertEqual(ticket.status, status)

    def test_rejects_unsupported_ticket_status(self) -> None:
        with self.assertRaises(ValidationError):
            SupportTicket(
                ticket_id="TKT-0001",
                order_number="ORD-1234",
                reason="Delivery delay",
                status="Pending",
            )


class TrackingEventTests(unittest.TestCase):
    def test_builds_event_with_datetime_fields(self) -> None:
        timestamp = datetime(2026, 1, 2, 3, 4)
        event = TrackingEvent(
            timestamp=timestamp,
            location="Lagos sorting facility",
            status="In transit",
        )

        self.assertEqual(event.timestamp, timestamp)
        self.assertEqual(event.location, "Lagos sorting facility")
        self.assertEqual(event.status, "In transit")

    def test_parses_iso_timestamp(self) -> None:
        event = TrackingEvent(
            timestamp="2026-01-02T03:04:00",
            location="Lagos",
            status="Arrived",
        )

        self.assertEqual(event.timestamp, datetime(2026, 1, 2, 3, 4))

    def test_rejects_missing_event_fields(self) -> None:
        with self.assertRaises(ValidationError):
            TrackingEvent(timestamp=datetime(2026, 1, 2), location="Lagos")


class TrackingResultTests(unittest.TestCase):
    def test_optional_fields_and_events_have_defaults(self) -> None:
        result = TrackingResult(waybill_number="WB-987")

        self.assertEqual(result.events, [])
        self.assertIsNone(result.estimated_delivery)
        self.assertFalse(result.is_delayed)
        self.assertIsNone(result.current_location)

    def test_accepts_nested_events_and_delivery_details(self) -> None:
        event_time = datetime(2026, 1, 2, 3, 4)
        eta = datetime(2026, 1, 5)
        result = TrackingResult(
            waybill_number="WB-987",
            events=[
                {
                    "timestamp": event_time,
                    "location": "Lagos",
                    "status": "In transit",
                }
            ],
            estimated_delivery=eta,
            is_delayed=True,
            current_location="Lagos",
        )

        self.assertEqual(len(result.events), 1)
        self.assertIsInstance(result.events[0], TrackingEvent)
        self.assertEqual(result.events[0].timestamp, event_time)
        self.assertEqual(result.estimated_delivery, eta)
        self.assertTrue(result.is_delayed)
        self.assertEqual(result.current_location, "Lagos")

    def test_rejects_invalid_nested_event(self) -> None:
        with self.assertRaises(ValidationError):
            TrackingResult(
                waybill_number="WB-987",
                events=[{"timestamp": "not-a-date", "location": "Lagos", "status": "In transit"}],
            )


if __name__ == "__main__":
    unittest.main()
