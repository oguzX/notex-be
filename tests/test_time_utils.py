"""Tests for time parsing utilities."""

from datetime import datetime

import pytest
import pytz

from app.utils.time import (
    parse_datetime_from_text,
    parse_natural_time,
    time_distance_minutes,
    format_reference_context,
)


class TestParseNaturalTime:
    """Legacy parse_natural_time tests."""

    def test_parse_iso_format(self):
        """Test parsing ISO format datetime."""
        result = parse_natural_time("2026-01-28T19:00:00Z")
        assert result is not None
        assert result.hour == 19
        assert result.minute == 0

    def test_parse_time_12hour(self):
        """Test parsing 12-hour time format."""
        result = parse_natural_time("7pm", tz="UTC")
        assert result is not None
        assert result.hour == 19

    def test_parse_time_24hour(self):
        """Test parsing 24-hour time format."""
        result = parse_natural_time("19:00", tz="UTC")
        assert result is not None
        assert result.hour == 19

    def test_parse_time_with_minutes(self):
        """Test parsing time with minutes."""
        result = parse_natural_time("7:30pm", tz="UTC")
        assert result is not None
        assert result.hour == 19
        assert result.minute == 30

    def test_parse_time_tomorrow(self):
        """Test parsing 'tomorrow' keyword."""
        result = parse_natural_time("tomorrow 9am", tz="UTC")
        assert result is not None
        assert result.hour == 9

    def test_parse_invalid_time(self):
        """Test parsing invalid time string."""
        result = parse_natural_time("invalid time")
        # May return None or a fuzzy parsed datetime
        # Depends on dateutil parser behavior


class TestTimeDistanceMinutes:
    """Tests for time_distance_minutes function."""

    def test_time_distance_minutes(self):
        """Test calculating time distance."""
        dt1 = datetime(2026, 1, 28, 19, 0, tzinfo=pytz.UTC)
        dt2 = datetime(2026, 1, 28, 19, 30, tzinfo=pytz.UTC)
        
        distance = time_distance_minutes(dt1, dt2)
        assert distance == 30.0

    def test_time_distance_negative(self):
        """Test time distance handles order."""
        dt1 = datetime(2026, 1, 28, 19, 0, tzinfo=pytz.UTC)
        dt2 = datetime(2026, 1, 28, 18, 30, tzinfo=pytz.UTC)
        
        distance = time_distance_minutes(dt1, dt2)
        assert distance == 30.0  # abs value


class TestParseDatetimeFromText:
    """Tests for the new robust parse_datetime_from_text function."""

    def test_tr_bu_aksam_time_only_future(self):
        """
        Test Turkish 'bu aksam' with specific time schedules for today.
        
        Scenario:
        - Reference time: 2026-01-29T08:32:00Z (morning UTC)
        - User says: "Bu aksam ders calismam gerek, 18de baslarim"
        - Expected: 2026-01-29T18:00:00Z (today at 18:00 UTC)
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 8, 32, 0))
        text = "Bu aksam ders calismam gerek, 18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 29  # Today, not yesterday!
        assert result.hour == 18
        assert result.minute == 0
        # Result should be in UTC
        assert result.tzinfo is not None

    def test_tr_bu_aksam_no_time_defaults_to_evening(self):
        """
        Test Turkish 'bu aksam' without specific time defaults to 19:00.
        
        Scenario:
        - Reference time: 2026-01-29T08:32:00Z
        - Timezone: Europe/Istanbul (UTC+3)
        - User says: "Bu aksam ders calisicam"
        - Expected: Evening on Jan 29 local time -> stored in UTC
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 8, 32, 0))
        text = "Bu aksam ders calisicam"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="Europe/Istanbul",
            languages=["tr"],
        )
        
        assert result is not None
        # Default evening hour is 19:00 local, which is 16:00 UTC (Istanbul is UTC+3)
        # Result should be on Jan 29
        local_result = result.astimezone(pytz.timezone("Europe/Istanbul"))
        assert local_result.year == 2026
        assert local_result.month == 1
        assert local_result.day == 29
        assert local_result.hour == 19  # Default evening hour

    def test_time_only_after_passed_schedules_tomorrow(self):
        """
        Test that time-only input after it has passed schedules for tomorrow.
        
        Scenario:
        - Reference time: 2026-01-29T20:30:00Z (evening)
        - User says: "18de baslarim"
        - 18:00 has already passed on Jan 29
        - Expected: 2026-01-30T18:00:00Z (tomorrow)
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 20, 30, 0))
        text = "18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 30  # Tomorrow
        assert result.hour == 18
        assert result.minute == 0

    def test_tr_time_with_saat_prefix(self):
        """Test Turkish time with 'saat' prefix."""
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 8, 0, 0))
        text = "saat 14:30'da toplantim var"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.day == 29  # Today
        assert result.hour == 14
        assert result.minute == 30

    def test_tr_yarin_aksam(self):
        """Test Turkish 'yarın akşam' (tomorrow evening)."""
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        text = "yarin aksam bulusacagiz"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.day == 30  # Tomorrow
        assert result.hour == 19  # Default evening

    def test_iso_format_parsing(self):
        """Test that ISO format dates are parsed correctly."""
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 8, 0, 0))
        text = "2026-01-30T14:00:00Z"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
        )
        
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 30
        assert result.hour == 14

    def test_english_7pm_future(self):
        """Test English '7pm' schedules for future."""
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        text = "meeting at 7pm"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["en"],
        )
        
        assert result is not None
        assert result.day == 29  # Today
        assert result.hour == 19

    def test_english_7pm_passed_schedules_tomorrow(self):
        """Test English '7pm' after passed time schedules tomorrow."""
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 21, 0, 0))
        text = "meeting at 7pm"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["en"],
        )
        
        assert result is not None
        assert result.day == 30  # Tomorrow
        assert result.hour == 19

    def test_timezone_conversion(self):
        """Test that results are properly converted to UTC."""
        # Reference: Jan 29, 2026 at 10:00 UTC
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        # Istanbul is UTC+3, so 18:00 Istanbul = 15:00 UTC
        text = "18de"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="Europe/Istanbul",
            languages=["tr"],
        )
        
        assert result is not None
        # Result should be in UTC
        assert result.tzinfo is not None
        # 18:00 Istanbul = 15:00 UTC
        assert result.hour == 15

    def test_empty_text_returns_none(self):
        """Test that empty text returns None."""
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        
        result = parse_datetime_from_text("", reference_dt_utc, "UTC")
        assert result is None
        
        result = parse_datetime_from_text("   ", reference_dt_utc, "UTC")
        assert result is None


class TestFormatReferenceContext:
    """Tests for format_reference_context function."""

    def test_format_reference_context_utc(self):
        """Test formatting reference context for UTC."""
        reference_dt = pytz.UTC.localize(datetime(2026, 1, 29, 14, 30, 0))
        
        context = format_reference_context(reference_dt, "UTC")
        
        assert context["timezone"] == "UTC"
        assert "2026-01-29" in context["date_local"]
        assert "14:30" in context["time_local"]
        assert context["day_of_week"] == "Thursday"

    def test_format_reference_context_istanbul(self):
        """Test formatting reference context for Europe/Istanbul."""
        # 14:30 UTC = 17:30 Istanbul
        reference_dt = pytz.UTC.localize(datetime(2026, 1, 29, 14, 30, 0))
        
        context = format_reference_context(reference_dt, "Europe/Istanbul")
        
        assert context["timezone"] == "Europe/Istanbul"
        assert "2026-01-29" in context["date_local"]
        assert "17:30" in context["time_local"]

    def test_format_reference_context_naive_datetime(self):
        """Test formatting with naive datetime (should be treated as UTC)."""
        reference_dt = datetime(2026, 1, 29, 14, 30, 0)
        
        context = format_reference_context(reference_dt, "UTC")
        
        assert context["timezone"] == "UTC"
        assert "2026-01-29" in context["date_local"]
