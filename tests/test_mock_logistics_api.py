"""Tests for the deterministic mock logistics tracking API."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import mock_logistics_api as logistics_api
from mock_logistics_api import WaybillNotFoundError, get_tracking_info
from models import TrackingEvent


class GetTrackingInfoTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_tracking_events_and_latest_location(self) -> None:
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)
        with patch.object(logistics_api, "datetime", Mock(now=Mock(return_value=now))):
            result = await get_tracking_info("WB-5001")

        self.assertEqual(result.waybill_number, "WB-5001")
        self.assertEqual(len(result.events), 4)
        self.assertEqual(result.current_location, "Port Harcourt Delivery Hub")
        self.assertFalse(result.is_delayed)
        self.assertEqual(result.estimated_delivery, datetime(2026, 8, 30, 18, tzinfo=timezone.utc))

    async def test_raises_for_unknown_waybill(self) -> None:
        with self.assertRaisesRegex(WaybillNotFoundError, "WB-unknown"):
            await get_tracking_info("WB-unknown")

    async def test_delay_requires_more_than_three_full_days_overdue(self) -> None:
        eta = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        event = TrackingEvent(
            timestamp=eta - timedelta(days=1),
            location="Sorting Hub",
            status="In transit",
        )
        record = {"estimated_delivery": eta, "events": [event]}

        with patch.dict(logistics_api._TRACKING_DATA, {"WB-boundary": record}):
            exactly_three_days_later = eta + timedelta(days=logistics_api.DELAY_THRESHOLD_DAYS)
            with patch.object(
                logistics_api,
                "datetime",
                Mock(now=Mock(return_value=exactly_three_days_later)),
            ):
                at_threshold = await get_tracking_info("WB-boundary")

            just_over_three_days = exactly_three_days_later + timedelta(microseconds=1)
            with patch.object(
                logistics_api,
                "datetime",
                Mock(now=Mock(return_value=just_over_three_days)),
            ):
                past_threshold = await get_tracking_info("WB-boundary")

        self.assertFalse(at_threshold.is_delayed)
        self.assertTrue(past_threshold.is_delayed)

    async def test_delivered_package_is_never_marked_delayed(self) -> None:
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        with patch.object(logistics_api, "datetime", Mock(now=Mock(return_value=now))):
            result = await get_tracking_info("WB-5003")

        self.assertIn("delivered", result.events[-1].status.lower())
        self.assertFalse(result.is_delayed)
        self.assertEqual(result.current_location, "Enugu")

    async def test_empty_event_list_has_no_current_location(self) -> None:
        eta = datetime(2026, 8, 30, tzinfo=timezone.utc)
        record = {"estimated_delivery": eta, "events": []}
        now = datetime(2026, 8, 29, tzinfo=timezone.utc)

        with (
            patch.dict(logistics_api._TRACKING_DATA, {"WB-no-events": record}),
            patch.object(logistics_api, "datetime", Mock(now=Mock(return_value=now))),
        ):
            result = await get_tracking_info("WB-no-events")

        self.assertEqual(result.events, [])
        self.assertIsNone(result.current_location)
        self.assertFalse(result.is_delayed)


if __name__ == "__main__":
    unittest.main()
