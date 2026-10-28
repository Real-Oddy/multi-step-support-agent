"""Shared clock anchor for the app's moving sample order and tracking data."""

from datetime import datetime, timezone


# One anchor per process keeps database seed dates and mock tracking events in
# sync while making the demo dates recent each time the app starts.
DEMO_NOW = datetime.now(timezone.utc).replace(second=0, microsecond=0)
