from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return a UTC timestamp in the naive format already used by Mongo docs."""
    return datetime.now(UTC).replace(tzinfo=None)


def utc_from_timestamp(timestamp: float) -> datetime:
    """Convert a Unix timestamp to the same UTC format as utc_now()."""
    return datetime.fromtimestamp(timestamp, UTC).replace(tzinfo=None)
