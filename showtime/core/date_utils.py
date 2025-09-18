"""Date and time utilities for consistent timestamp handling."""

from datetime import datetime
from typing import Optional

# Custom timestamp format used in circus labels
# Format: YYYY-MM-DDTHH-MM (using dashes instead of colons for GitHub label compatibility)
CIRCUS_TIME_FORMAT = "%Y-%m-%dT%H-%M"


def format_utc_now() -> str:
    """Get current UTC time formatted for circus labels."""
    return datetime.utcnow().strftime(CIRCUS_TIME_FORMAT)


def parse_circus_time(timestamp: str) -> Optional[datetime]:
    """Parse a circus timestamp string into a datetime object.

    Args:
        timestamp: String in format "YYYY-MM-DDTHH-MM"

    Returns:
        datetime object or None if parsing fails
    """
    if not timestamp:
        return None

    try:
        return datetime.strptime(timestamp, CIRCUS_TIME_FORMAT)
    except (ValueError, AttributeError):
        return None


def age_display(created_at: str) -> str:
    """Convert a circus timestamp to human-readable age.

    Args:
        created_at: Timestamp string in circus format

    Returns:
        Human-readable age like "2d 5h" or "45m"
    """
    created_dt = parse_circus_time(created_at)
    if not created_dt:
        return "-"

    # Compare UTC to UTC for accurate age
    age = datetime.utcnow() - created_dt

    # Format age nicely
    days = age.days
    hours = age.seconds // 3600
    minutes = (age.seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


def is_expired(created_at: str, max_age_hours: int) -> bool:
    """Check if a timestamp is older than the specified hours.

    Args:
        created_at: Timestamp string in circus format
        max_age_hours: Maximum age in hours

    Returns:
        True if timestamp is older than max_age_hours
    """
    created_dt = parse_circus_time(created_at)
    if not created_dt:
        return False

    from datetime import timedelta

    expiry_time = created_dt + timedelta(hours=max_age_hours)
    return datetime.utcnow() > expiry_time
