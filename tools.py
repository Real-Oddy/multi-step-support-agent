"""
tools.py
--------
PydanticAI tool functions for the Multi-Step Order Support Agent.

Each function is a plain async callable — no RunContext required because
this agent has no injectable dependencies. PydanticAI detects this
automatically via the absence of a RunContext first parameter.

Design rules applied throughout:
  - Docstrings are written for the LLM, not just the developer.
    PydanticAI sends the docstring to the model as the tool description,
    so each docstring explains *when* to call the tool, *what* it returns,
    and any ordering constraints relative to other tools.
  - Tools never raise exceptions to the model. All domain errors are caught
    and returned as plain-English strings the agent can reason about.
  - Every invocation is logged with a [TOOL] prefix for full observability
    of the decision trace (which tools were called, in what order).

Tools defined here:
  lookup_order          — Fetch order details from SQLite.
  track_shipment        — Get delivery checkpoint events from the logistics API.
  fetch_return_policy   — Retrieve the relevant return policy via RAG.
  open_support_ticket   — Create a support ticket in SQLite.
"""

from __future__ import annotations

from loguru import logger

from database import (
    OrderNotFoundError,
    TicketCreationError,
    create_support_ticket,
    get_order,
)
from mock_logistics_api import WaybillNotFoundError, get_tracking_info
from rag import RAGNotInitializedError, get_return_policy


# ---------------------------------------------------------------------------
# Tool 1 — Lookup Order
# ---------------------------------------------------------------------------


async def lookup_order(order_number: str) -> str:
    """
    Fetch full order details from the database for a given order number.

    Always call this tool first whenever a customer references an order number.
    The result tells you the order status (Processing / Shipped / Delivered /
    Cancelled), payment status (Pending / Paid), product category, and waybill
    number. You will need the waybill number to call track_shipment, and the
    product category to call fetch_return_policy.

    Returns a formatted summary of the order, or a plain-English error message
    if the order number is not found.
    """
    logger.info(f"[TOOL] lookup_order called | order_number='{order_number}'")

    try:
        order = await get_order(order_number)
    except OrderNotFoundError:
        logger.warning(f"[TOOL] lookup_order | NOT FOUND: '{order_number}'")
        return (
            f"Order '{order_number}' was not found in the system. "
            "Please verify the order number provided by the customer."
        )

    eta = (
        order.estimated_delivery.strftime("%Y-%m-%d")
        if order.estimated_delivery
        else "N/A"
    )
    waybill = order.waybill_number or "Not yet dispatched"

    result = "\n".join([
        f"Order Number      : {order.order_number}",
        f"Customer ID       : {order.customer_id}",
        f"Order Status      : {order.order_status}",
        f"Payment Status    : {order.payment_status}",
        f"Product Category  : {order.product_category}",
        f"Waybill Number    : {waybill}",
        f"Order Placed      : {order.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"Estimated Delivery: {eta}",
    ])

    logger.debug(f"[TOOL] lookup_order | result returned for '{order_number}'")
    return result


# ---------------------------------------------------------------------------
# Tool 2 — Track Shipment
# ---------------------------------------------------------------------------


async def track_shipment(waybill_number: str) -> str:
    """
    Retrieve live delivery tracking events for a given waybill number.

    Call this tool after lookup_order returns a waybill number. It tells you
    where the package currently is, whether it is delayed beyond the 3-day
    threshold, and the full chronological list of delivery checkpoint events.

    You MUST call this tool if the order status is 'Shipped' — it is required
    to determine whether the delay escalation business rule applies. If the
    'Delayed' field in the result reads 'YES', you must call open_support_ticket
    and set escalation_required=True in your final response.

    Returns a formatted tracking summary, or a plain-English error message
    if the waybill is not recognised by the logistics system.
    """
    logger.info(f"[TOOL] track_shipment called | waybill='{waybill_number}'")

    try:
        result = await get_tracking_info(waybill_number)
    except WaybillNotFoundError:
        logger.warning(f"[TOOL] track_shipment | NOT FOUND: '{waybill_number}'")
        return (
            f"Waybill '{waybill_number}' was not found in the logistics system. "
            "The shipment may not yet be registered with the carrier."
        )

    events_block = "\n".join(
        f"  [{e.timestamp.strftime('%Y-%m-%d %H:%M UTC')}] "
        f"{e.location} — {e.status}"
        for e in result.events
    ) or "  No checkpoint events recorded yet."

    eta = (
        result.estimated_delivery.strftime("%Y-%m-%d")
        if result.estimated_delivery
        else "Unknown"
    )

    delayed_label = (
        "YES — shipment is more than 3 days overdue"
        if result.is_delayed
        else "No"
    )

    summary = "\n".join([
        f"Waybill           : {result.waybill_number}",
        f"Current Location  : {result.current_location or 'Unknown'}",
        f"Estimated Delivery: {eta}",
        f"Delayed           : {delayed_label}",
        "Checkpoint Events :",
        events_block,
    ])

    logger.debug(
        f"[TOOL] track_shipment | waybill='{waybill_number}' | "
        f"delayed={result.is_delayed} | checkpoints={len(result.events)}"
    )
    return summary


# ---------------------------------------------------------------------------
# Tool 3 — Fetch Return Policy
# ---------------------------------------------------------------------------


async def fetch_return_policy(category: str) -> str:
    """
    Retrieve the return and refund policy for a given product category.

    Call this tool when the customer asks about returns, refunds, cancellations,
    or policy terms for their product. Pass the product category exactly as
    returned by lookup_order (e.g. 'Electronics', 'Clothing', 'Furniture').
    Retrieval is semantic — approximate terms such as 'phones' or 'gadgets'
    will still resolve to the correct policy.

    Returns the full policy text as a plain string, ready to be quoted or
    summarised in your response to the customer.
    """
    logger.info(f"[TOOL] fetch_return_policy called | category='{category}'")

    try:
        policy = await get_return_policy(category)
    except RAGNotInitializedError:
        logger.error("[TOOL] fetch_return_policy | RAG not initialised")
        return (
            "Return policy information is temporarily unavailable. "
            "Please advise the customer to contact our support team directly "
            "for policy details."
        )

    logger.debug(f"[TOOL] fetch_return_policy | policy retrieved for '{category}'")
    return policy


# ---------------------------------------------------------------------------
# Tool 4 — Open Support Ticket
# ---------------------------------------------------------------------------


async def open_support_ticket(order_number: str, reason: str) -> str:
    """
    Create a support ticket in the database for an order that requires
    human intervention.

    Call this tool when any of the following conditions are true:
      1. A cancellation request cannot be fulfilled automatically
         (e.g. the order is already Shipped, or payment is Paid).
      2. The track_shipment result shows the shipment is delayed by more
         than 3 days (Delayed field reads 'YES').
      3. The customer's request cannot be resolved by any other tool.

    After calling this tool, you MUST set escalation_required=True in your
    final structured response. Always include the returned ticket ID in your
    explanation to the customer.

    Returns a confirmation string with the ticket ID, or a plain-English
    error message if ticket creation failed.
    """
    logger.info(
        f"[TOOL] open_support_ticket called | "
        f"order='{order_number}' | reason='{reason}'"
    )

    try:
        ticket = await create_support_ticket(order_number, reason)
    except OrderNotFoundError:
        logger.error(
            f"[TOOL] open_support_ticket | ORDER NOT FOUND: '{order_number}'"
        )
        return (
            f"Failed to create support ticket — order '{order_number}' does not "
            "exist in the system. Verify the order number and try again."
        )
    except TicketCreationError as exc:
        logger.error(f"[TOOL] open_support_ticket | DB ERROR: {exc}")
        return (
            f"A database error occurred while creating the ticket for "
            f"'{order_number}'. Escalation must be handled manually."
        )

    result = "\n".join([
        "Support ticket successfully created.",
        f"Ticket ID    : {ticket.ticket_id}",
        f"Order Number : {ticket.order_number}",
        f"Reason       : {ticket.reason}",
        f"Status       : {ticket.status}",
        f"Created At   : {ticket.created_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ])

    logger.info(
        f"[TOOL] open_support_ticket | ticket created: {ticket.ticket_id}"
    )
    return result
