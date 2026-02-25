import json
from datetime import datetime, timezone as dt_timezone

try:
    import pytz
except ImportError:
    print("Installing pytz...")
    import subprocess
    subprocess.check_call(['pip', 'install', 'pytz'])
    import pytz


def utcnow() -> datetime:
    """Return current UTC datetime with timezone info."""
    return datetime.now(dt_timezone.utc)


def format_reference_context(
    reference_dt_utc: datetime,
    tz_name: str = "UTC",
) -> dict[str, str]:
    """
    Format reference datetime context for LLM prompts.
    
    Returns a dict with:
    - reference_datetime_utc: ISO format in UTC
    - reference_datetime_local: ISO format in target timezone
    - timezone: Target timezone name
    - date_local: Local date as YYYY-MM-DD
    - time_local: Local time as HH:MM
    """
    try:
        timezone = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        timezone = pytz.UTC
    
    if reference_dt_utc.tzinfo is None:
        reference_dt_utc = pytz.UTC.localize(reference_dt_utc)
    
    reference_local = reference_dt_utc.astimezone(timezone)
    
    return {
        "reference_datetime_utc": reference_dt_utc.isoformat(),
        "reference_datetime_local": reference_local.isoformat(),
        "timezone": tz_name,
        "date_local": reference_local.strftime("%Y-%m-%d"),
        "time_local": reference_local.strftime("%H:%M"),
        "day_of_week": reference_local.strftime("%A"),
    }


if __name__ == "__main__":
    reference_dt_utc = utcnow()

    # Get reference context for the prompt
    ref_context = format_reference_context(reference_dt_utc, 'UTC')

    print(json.dumps(ref_context, indent=2))