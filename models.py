"""
models.py
---------
All Pydantic data models for the Multi-Step Order Support Agent.

Covers:
  - AgentResponse       : The structured output the agent returns to the customer.
  - OrderRecord         : Represents a row from the `orders` SQLite table.
  - SupportTicket       : Represents a row from the `support_tickets` SQLite table.
  - TrackingEvent       : A single delivery event from the mock logistics API.
  - TrackingResult      : The full tracking response (list of events + ETA).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Order statuses & payment statuses — used as Literal types for safety
# ---------------------------------------------------------------------------

OrderStatus = Literal["Processing", "Shipped", "Delivered", "Cancelled"]
PaymentStatus = Literal["Pending", "Paid"]
TicketStatus = Literal["Open", "In Progress", "Resolved", "Closed"]


# ---------------------------------------------------------------------------
# 1. Agent Output Schema
#    This is what the agent returns to the customer at the end of every run.
# ---------------------------------------------------------------------------

class AgentResponse(BaseModel):
    """Structured response returned by the support agent to the customer."""

    order_number: str = Field(
        description="The order identifier extracted from the conversation, e.g. 'ORD-1234'. "
                    "Use 'UNKNOWN' if no order number could be identified."
    )
    current_status: str = Field(
        description="Short human-readable summary of the order's current status, "
                    "e.g. 'Shipped', 'Pending Payment', 'Cancelled', 'Delayed'."
    )
    explanation: str = Field(
        description="Polite, natural-language explanation detailing what was found — "
                    "includes transit info, policy details, or reason for escalation."
    )
    recommended_action: str = Field(
        description="Clear, actionable next step for the customer or support team."
    )
    escalation_required: bool = Field(
        default=False,
        description="True if a support ticket was auto-created or human intervention "
                    "is needed. False if the query was fully resolved."
    )


# ---------------------------------------------------------------------------
# 2. Order Record
#    Mirrors the `orders` table in SQLite.
# ---------------------------------------------------------------------------

class OrderRecord(BaseModel):
    """Represents a single order row returned from the database."""

    order_number: str = Field(description="Unique order identifier, e.g. 'ORD-1234'.")
    customer_id: str = Field(description="Unique identifier for the customer.")
    payment_status: PaymentStatus = Field(description="Payment status: 'Pending' or 'Paid'.")
    order_status: OrderStatus = Field(
        description="Fulfillment status: 'Processing', 'Shipped', 'Delivered', or 'Cancelled'."
    )
    waybill_number: str | None = Field(
        default=None,
        description="Logistics waybill/tracking number. None if not yet dispatched."
    )
    product_category: str = Field(
        default="General",
        description="Product category for RAG policy lookup, e.g. 'Electronics', 'Clothing'."
    )
    created_at: datetime = Field(description="Timestamp when the order was placed.")
    estimated_delivery: datetime | None = Field(
        default=None,
        description="Expected delivery date set at time of dispatch."
    )


# ---------------------------------------------------------------------------
# 3. Support Ticket
#    Mirrors the `support_tickets` table in SQLite.
# ---------------------------------------------------------------------------

class SupportTicket(BaseModel):
    """Represents a support ticket created by the agent or queried from the DB."""

    ticket_id: str = Field(description="Auto-generated unique ticket ID, e.g. 'TKT-0001'.")
    order_number: str = Field(description="The order this ticket is linked to.")
    reason: str = Field(description="Short description of why the ticket was created.")
    status: TicketStatus = Field(
        default="Open",
        description="Current ticket status: 'Open', 'In Progress', 'Resolved', or 'Closed'."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the ticket was created."
    )


# ---------------------------------------------------------------------------
# 4. Tracking Event
#    A single checkpoint event from the mock logistics/delivery API.
# ---------------------------------------------------------------------------

class TrackingEvent(BaseModel):
    """A single delivery checkpoint event from the logistics API."""

    timestamp: datetime = Field(description="When this event occurred.")
    location: str = Field(description="City or facility where the event occurred.")
    status: str = Field(
        description="Description of the event, e.g. 'Package picked up', "
                    "'In transit to Lagos', 'Out for delivery'."
    )


# ---------------------------------------------------------------------------
# 5. Tracking Result
#    The full response from the mock logistics API for a given waybill.
# ---------------------------------------------------------------------------

class TrackingResult(BaseModel):
    """Full tracking response for a waybill number."""

    waybill_number: str = Field(description="The waybill/tracking number queried.")
    events: list[TrackingEvent] = Field(
        default_factory=list,
        description="Chronological list of delivery checkpoint events."
    )
    estimated_delivery: datetime | None = Field(
        default=None,
        description="Current estimated delivery date from the logistics provider."
    )
    is_delayed: bool = Field(
        default=False,
        description="True if the shipment is delayed by more than 3 days past the ETA."
    )
    current_location: str | None = Field(
        default=None,
        description="The most recent known location of the package."
    )
