"""
mock_logistics_api.py
---------------------
Simulates a third-party logistics/delivery tracking API.

In production this would be an async HTTP call to a carrier's REST API.
Here every waybill has a realistic set of checkpoint events and an estimated
delivery date relative to the shared demo clock. The `is_delayed` flag is
computed at call-time against the live system clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from demo_clock import DEMO_NOW
from models import TrackingEvent, TrackingResult

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Must match the business rule stated in the README.
DELAY_THRESHOLD_DAYS: int = 3

# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------


class WaybillNotFoundError(Exception):
    """Raised when a waybill number has no record in the logistics system."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _offset(days: int, *, hours: int = 0, minutes: int = 0) -> datetime:
    """Return a timestamp relative to the shared sample-data clock."""
    return DEMO_NOW + timedelta(days=days, hours=hours, minutes=minutes)


# ---------------------------------------------------------------------------
# Mock tracking data store
#
# Keyed by waybill number. Covers all three business-rule scenarios:
#   WB-5001  →  Shipped, in transit, on time         (ORD-1003)
#   WB-5002  →  Shipped, stuck in customs, DELAYED    (ORD-1004)
#   WB-5003  →  Delivered successfully                (ORD-1005)
# ---------------------------------------------------------------------------

_TRACKING_DATA: dict[str, dict] = {
    "WB-5001": {
        "estimated_delivery": _offset(5),
        "events": [
            TrackingEvent(
                timestamp=_offset(-5),
                location="Lagos Sorting Facility",
                status="Package picked up from seller",
            ),
            TrackingEvent(
                timestamp=_offset(-4, hours=2),
                location="Lagos Hub",
                status="Package processed at origin hub",
            ),
            TrackingEvent(
                timestamp=_offset(-3, hours=5),
                location="Abuja Transit Centre",
                status="In transit to destination city",
            ),
            TrackingEvent(
                timestamp=_offset(-1, hours=1),
                location="Port Harcourt Delivery Hub",
                status="Arrived at local delivery hub — awaiting dispatch",
            ),
        ],
    },
    "WB-5002": {
        "estimated_delivery": _offset(-5),
        "events": [
            TrackingEvent(
                timestamp=_offset(-10),
                location="Kano Sorting Facility",
                status="Package picked up from seller",
            ),
            TrackingEvent(
                timestamp=_offset(-9, hours=2),
                location="Kano Hub",
                status="Package processed at origin hub",
            ),
            TrackingEvent(
                timestamp=_offset(-7, hours=5),
                location="Apapa Port, Lagos",
                status="Package held at customs — documentation under review",
            ),
            TrackingEvent(
                timestamp=_offset(-5, hours=1),
                location="Apapa Port, Lagos",
                status="Customs clearance pending — awaiting authority release",
            ),
        ],
    },
    "WB-5003": {
        "estimated_delivery": _offset(-2),
        "events": [
            TrackingEvent(
                timestamp=_offset(-7),
                location="Ibadan Sorting Facility",
                status="Package picked up from seller",
            ),
            TrackingEvent(
                timestamp=_offset(-6, hours=2),
                location="Ibadan Hub",
                status="Package processed at origin hub",
            ),
            TrackingEvent(
                timestamp=_offset(-4, hours=5),
                location="Lagos Transit Centre",
                status="In transit to destination city",
            ),
            TrackingEvent(
                timestamp=_offset(-3, hours=1),
                location="Enugu Delivery Hub",
                status="Out for delivery",
            ),
            TrackingEvent(
                timestamp=_offset(-2, hours=6),
                location="Enugu",
                status="Package delivered — signed by recipient",
            ),
        ],
    },
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_tracking_info(waybill_number: str) -> TrackingResult:
    """
    Retrieve full tracking information for a given waybill number.

    The delay flag is computed dynamically against the live clock:
    a shipment is flagged as delayed only when ALL three conditions hold:
      1. The package has not yet been delivered.
      2. The estimated delivery date has passed.
      3. The overdue period exceeds ``DELAY_THRESHOLD_DAYS`` (3 days).

    Args:
        waybill_number: Carrier tracking number, e.g. ``'WB-5001'``.

    Returns:
        A :class:`~models.TrackingResult` with all checkpoint events,
        the current ETA, computed delay flag, and last known location.

    Raises:
        WaybillNotFoundError: If the waybill number is unrecognised.
    """
    logger.debug(f"Tracking lookup requested | waybill={waybill_number}")

    record = _TRACKING_DATA.get(waybill_number)
    if record is None:
        raise WaybillNotFoundError(
            f"Waybill '{waybill_number}' was not found in the logistics system."
        )

    events: list[TrackingEvent] = record["events"]
    estimated_delivery: datetime = record["estimated_delivery"]
    now = datetime.now(tz=timezone.utc)

    # Check the latest event to see if the package is already delivered.
    # We check the last event only — a delivered package cannot be delayed.
    last_event: TrackingEvent | None = events[-1] if events else None
    already_delivered: bool = (
        last_event is not None
        and "delivered" in last_event.status.lower()
    )

    # Apply the 3-day delay business rule.
    is_delayed: bool = (
        not already_delivered
        and estimated_delivery < now
        and (now - estimated_delivery) > timedelta(days=DELAY_THRESHOLD_DAYS)
    )

    result = TrackingResult(
        waybill_number=waybill_number,
        events=events,
        estimated_delivery=estimated_delivery,
        is_delayed=is_delayed,
        current_location=last_event.location if last_event else None,
    )

    logger.info(
        f"Tracking result | waybill={waybill_number} | "
        f"checkpoints={len(events)} | delayed={is_delayed} | "
        f"location='{result.current_location}'"
    )
    return result
