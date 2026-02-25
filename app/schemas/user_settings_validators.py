"""Timezone validation helpers."""

from zoneinfo import ZoneInfo, available_timezones


# Cache the set for fast lookups
_VALID_TIMEZONES: set[str] | None = None


def _get_valid_timezones() -> set[str]:
    global _VALID_TIMEZONES
    if _VALID_TIMEZONES is None:
        _VALID_TIMEZONES = available_timezones()
    return _VALID_TIMEZONES


def validate_iana_timezone(value: str) -> str:
    """Validate that *value* is a valid IANA timezone name.

    Returns the canonical timezone string on success.
    Raises ``ValueError`` on failure (Pydantic will convert this to a
    422 validation error).
    """
    if value not in _get_valid_timezones():
        raise ValueError(
            f"Invalid IANA timezone: '{value}'. "
            "Use a valid timezone such as 'Europe/Istanbul' or 'America/New_York'."
        )
    # Normalise by round-tripping through ZoneInfo
    return str(ZoneInfo(value))
