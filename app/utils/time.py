"""Time parsing and manipulation utilities."""

import re
from datetime import datetime, time, timedelta, timezone as dt_timezone
from typing import Any

import pytz
from dateutil import parser as dateutil_parser

# Turkish relative day/time phrases
TURKISH_EVENING_PHRASES = [
    "bu aksam", "bu akşam", "bu gece", "aksam", "akşam",
    "bu aksamki", "bu akşamki", "aksamleyin", "akşamleyin",
]
TURKISH_TODAY_PHRASES = [
    "bugun", "bugün", "simdi", "şimdi", "su an", "şu an",
]
TURKISH_TOMORROW_PHRASES = [
    "yarin", "yarın", "yarin aksam", "yarın akşam",
]

# English relative day/time phrases
ENGLISH_EVENING_PHRASES = [
    "this evening", "tonight", "this night",
]
ENGLISH_TOMORROW_PHRASES = [
    "tomorrow",
]

# Default evening hour when no specific time is given
DEFAULT_EVENING_HOUR = 19


def parse_datetime_from_text(
    text: str,
    reference_dt_utc: datetime,
    tz_name: str = "UTC",
    languages: list[str] | None = None,
) -> datetime | None:
    """
    Parse natural language datetime expressions with robust relative date handling.
    
    This is the primary parsing function that ensures:
    1. RELATIVE_BASE is properly set to reference_dt in target timezone
    2. PREFER_DATES_FROM = "future" to avoid picking past dates
    3. Time-only inputs schedule for today if still in future, else tomorrow
    4. Turkish evening phrases default to 19:00 local time
    
    Args:
        text: Natural language text containing date/time
        reference_dt_utc: Reference datetime in UTC (typically message.created_at)
        tz_name: Target timezone name (e.g., "Europe/Istanbul", "UTC")
        languages: Language hints for parsing (e.g., ["tr"] for Turkish)
    
    Returns:
        Parsed datetime in UTC, or None if parsing failed
    """
    if not text:
        return None
    
    text = text.strip()
    text_lower = text.lower()
    
    # Get timezone
    try:
        timezone = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        timezone = pytz.UTC
    
    # Convert reference time to target timezone
    if reference_dt_utc.tzinfo is None:
        reference_dt_utc = pytz.UTC.localize(reference_dt_utc)
    reference_local = reference_dt_utc.astimezone(timezone)
    
    # Try ISO format first (exact format)
    try:
        dt = dateutil_parser.isoparse(text)
        if dt.tzinfo is None:
            dt = timezone.localize(dt)
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError):
        pass
    
    # Check for evening phrases (Turkish and English)
    all_evening_phrases = TURKISH_EVENING_PHRASES + ENGLISH_EVENING_PHRASES
    is_evening_phrase = any(phrase in text_lower for phrase in all_evening_phrases)
    
    # Check for tomorrow phrases (Turkish and English)
    all_tomorrow_phrases = TURKISH_TOMORROW_PHRASES + ENGLISH_TOMORROW_PHRASES
    is_tomorrow = any(phrase in text_lower for phrase in all_tomorrow_phrases)
    
    # Extract time pattern (handles "18de", "18:00", "7pm", etc.)
    extracted_time = _extract_time_from_text(text_lower)
    
    if extracted_time is not None:
        hour, minute = extracted_time
        target_date = reference_local.date()
        
        # Check for tomorrow keyword
        if is_tomorrow:
            target_date = target_date + timedelta(days=1)
        else:
            # If time already passed today, schedule for tomorrow
            proposed_dt = datetime.combine(target_date, time(hour, minute))
            proposed_dt = timezone.localize(proposed_dt)
            if proposed_dt <= reference_local:
                target_date = target_date + timedelta(days=1)
        
        # Build final datetime
        try:
            dt = datetime.combine(target_date, time(hour, minute))
            dt = timezone.localize(dt)
            return dt.astimezone(pytz.UTC)
        except (ValueError, TypeError):
            pass
    
    # Evening phrase without specific time -> default evening hour
    if is_evening_phrase and extracted_time is None:
        target_date = reference_local.date()
        if is_tomorrow:
            target_date = target_date + timedelta(days=1)
        else:
            # If default evening time has passed, schedule tomorrow
            proposed_dt = datetime.combine(target_date, time(DEFAULT_EVENING_HOUR, 0))
            proposed_dt = timezone.localize(proposed_dt)
            if proposed_dt <= reference_local:
                target_date = target_date + timedelta(days=1)
        
        dt = datetime.combine(target_date, time(DEFAULT_EVENING_HOUR, 0))
        dt = timezone.localize(dt)
        return dt.astimezone(pytz.UTC)
    
    # Try dateutil parser as fallback with reference time
    try:
        dt = dateutil_parser.parse(text, default=reference_local, fuzzy=True)
        if dt.tzinfo is None:
            dt = timezone.localize(dt)
        
        # If parsed datetime is in the past relative to reference, shift forward
        if dt <= reference_local:
            # Check if it's just a time reference (no explicit date in text)
            if _is_time_only_reference(text_lower):
                dt = dt + timedelta(days=1)
        
        return dt.astimezone(pytz.UTC)
    except (ValueError, TypeError):
        return None


def _extract_time_from_text(text_lower: str) -> tuple[int, int] | None:
    """
    Extract time (hour, minute) from text.
    
    Handles patterns like:
    - "18:00", "18:30"
    - "7pm", "7:30pm", "7 pm"
    - "18de", "18'de" (Turkish style)
    - "saat 18", "saat 18:30"
    """
    # Standard 12-hour format FIRST: "7pm", "7:30 pm", "7:30pm"
    # Must check this before Turkish patterns to avoid "7" in "7pm" matching Turkish
    time_12h = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text_lower)
    if time_12h:
        hour = int(time_12h.group(1))
        minute = int(time_12h.group(2)) if time_12h.group(2) else 0
        meridiem = time_12h.group(3)
        
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    
    # Turkish style: "18de", "18'de", "saat 18", "saat 18:30"
    # Only match if followed by Turkish suffix or "saat" prefix
    turkish_time = re.search(r"(?:saat\s*)(\d{1,2})(?:[:\.](\d{2}))?(?:'?de|'da)?(?:\s|$)", text_lower)
    if turkish_time:
        hour = int(turkish_time.group(1))
        minute = int(turkish_time.group(2)) if turkish_time.group(2) else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    
    # Turkish time with suffix (without saat prefix): "18de", "18'de"
    turkish_suffix = re.search(r"(\d{1,2})(?:[:\.](\d{2}))?'?(?:de|da)\b", text_lower)
    if turkish_suffix:
        hour = int(turkish_suffix.group(1))
        minute = int(turkish_suffix.group(2)) if turkish_suffix.group(2) else 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    
    # 24-hour format: "18:00", "18:30"
    time_24h = re.search(r"(\d{1,2}):(\d{2})(?!\d)", text_lower)
    if time_24h:
        hour = int(time_24h.group(1))
        minute = int(time_24h.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return (hour, minute)
    
    return None


def _is_time_only_reference(text_lower: str) -> bool:
    """
    Check if text appears to be just a time reference without an explicit date.
    
    Returns True for patterns like "18de", "7pm", "at 7" without date words.
    """
    # Contains explicit date indicators
    date_indicators = [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
        "ocak", "şubat", "mart", "nisan", "mayıs", "haziran",
        "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar",
        r"\d{1,2}/\d{1,2}",  # Date patterns
        r"\d{4}-\d{2}-\d{2}",
    ]
    
    for indicator in date_indicators:
        if re.search(indicator, text_lower):
            return False
    
    return True


def parse_natural_time(
    text: str,
    reference_time: datetime | None = None,
    tz: str = "UTC",
) -> datetime | None:
    """
    Parse natural language time expressions (legacy function).
    
    This function is kept for backward compatibility.
    For new code, prefer parse_datetime_from_text() which handles
    relative dates more robustly.
    
    Examples:
        - "7pm", "7:00 PM", "19:00"
        - "today at 8", "this evening at 8"
        - "tomorrow 9am"
        - ISO format: "2026-01-28T19:00:00Z"
    """
    if not text:
        return None
    
    # Get timezone
    try:
        timezone = pytz.timezone(tz)
    except pytz.UnknownTimeZoneError:
        timezone = pytz.UTC
    
    # Reference time (defaults to now in specified timezone)
    if reference_time is None:
        reference_time = datetime.now(timezone)
    elif reference_time.tzinfo is None:
        reference_time = timezone.localize(reference_time)
    
    # Convert reference to UTC for the new function
    reference_utc = reference_time.astimezone(pytz.UTC)
    
    # Use the new robust parser
    result = parse_datetime_from_text(text, reference_utc, tz)
    
    if result is not None:
        # Convert back to the target timezone for backward compatibility
        return result.astimezone(timezone)
    
    return None


def time_distance_minutes(dt1: datetime, dt2: datetime) -> float:
    """Calculate distance between two datetimes in minutes."""
    delta = abs(dt1 - dt2)
    return delta.total_seconds() / 60


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is in UTC."""
    if dt.tzinfo is None:
        return pytz.UTC.localize(dt)
    return dt.astimezone(pytz.UTC)


def utcnow() -> datetime:
    """Get current time in UTC."""
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
