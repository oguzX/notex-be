"""Tests for Turkish time parsing and relative date handling.

These tests specifically address the bug where "bu akşam" (this evening)
was incorrectly resolving to yesterday's date instead of today's.
"""

from datetime import datetime
from uuid import uuid4

import pytest
import pytz

from app.utils.time import parse_datetime_from_text


class TestTurkishRelativeDateBugFix:
    """
    Regression tests for the Turkish relative date interpretation bug.
    
    Bug description:
    - When user sends "Bu aksam ders calismam gerek, 18de baslarim"
    - With timezone=UTC and message received on 2026-01-29
    - System was producing due_at = "2026-01-28T18:00:00Z" (YESTERDAY)
    - Should be "2026-01-29T18:00:00Z" (TODAY)
    
    Root cause:
    - dateparser was using PREFER_DATES_FROM='past' by default
    - RELATIVE_BASE was not being set correctly
    """

    def test_bu_aksam_18de_resolves_to_today(self):
        """
        Main regression test for the reported bug.
        
        User message: "Bu aksam ders calismam gerek, 18de baslarim"
        Received at: 2026-01-29T08:32:00Z
        Expected due_at: 2026-01-29T18:00:00Z
        """
        # Message received timestamp (server time)
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 8, 32, 0))
        
        # The user's message content
        text = "Bu aksam ders calismam gerek, 18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None, "Should parse the datetime"
        
        # The critical assertion: should be Jan 29, NOT Jan 28
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 29, f"Expected day 29 (today), got day {result.day} (yesterday would be a bug!)"
        assert result.hour == 18
        assert result.minute == 0

    def test_bu_aksam_without_time_uses_default_evening(self):
        """
        When user says 'bu akşam' without a specific time,
        use default evening hour (19:00).
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        text = "bu aksam bir seyler yapacagim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.day == 29  # Today
        assert result.hour == 19  # Default evening

    def test_bu_aksam_with_turkish_timezone(self):
        """
        Test with Europe/Istanbul timezone.
        18:00 Istanbul = 15:00 UTC
        """
        # 10:00 UTC = 13:00 Istanbul
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        text = "Bu aksam 18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="Europe/Istanbul",
            languages=["tr"],
        )
        
        assert result is not None
        # Result is in UTC
        assert result.tzinfo is not None
        # 18:00 Istanbul = 15:00 UTC
        assert result.hour == 15
        assert result.day == 29

    def test_18de_time_already_passed_schedules_tomorrow(self):
        """
        When user says '18de' but 18:00 has already passed,
        schedule for tomorrow.
        """
        # Reference: 20:30 UTC (18:00 already passed)
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 20, 30, 0))
        text = "18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.day == 30  # Tomorrow
        assert result.hour == 18

    def test_yarin_aksam_schedules_tomorrow(self):
        """
        'yarın akşam' should schedule for tomorrow evening.
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 14, 0, 0))
        text = "yarin aksam goruselim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.day == 30  # Tomorrow
        assert result.hour == 19  # Default evening

    def test_yarin_with_specific_time(self):
        """
        'yarın 15:30' should schedule for tomorrow at 15:30.
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 14, 0, 0))
        text = "yarin 15:30'da toplanti"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.day == 30  # Tomorrow
        assert result.hour == 15
        assert result.minute == 30

    def test_saat_prefix_parsing(self):
        """
        'saat 14:00' should parse correctly.
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        text = "saat 14:00'da gel"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.day == 29  # Today
        assert result.hour == 14
        assert result.minute == 0

    def test_bu_gece_scheduling(self):
        """
        'bu gece' (tonight) should schedule for today's night.
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 14, 0, 0))
        text = "bu gece calisacagim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        assert result.day == 29  # Today
        # Should be evening/night time (default 19:00)
        assert result.hour >= 19


class TestEdgeCases:
    """Edge cases for time parsing."""

    def test_midnight_boundary(self):
        """
        Test parsing near midnight.
        """
        # Reference: 23:30 UTC on Jan 29
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 23, 30, 0))
        text = "18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        # 18:00 has passed, so schedule tomorrow
        assert result.day == 30
        assert result.hour == 18

    def test_early_morning_reference(self):
        """
        Test parsing in early morning (time not yet passed).
        """
        # Reference: 05:00 UTC on Jan 29
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 5, 0, 0))
        text = "18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        # 18:00 has not passed yet, so schedule today
        assert result.day == 29
        assert result.hour == 18

    def test_timezone_day_boundary(self):
        """
        Test timezone edge case where UTC and local are on different days.
        
        Example: 23:00 UTC on Jan 29 = 02:00 Istanbul on Jan 30
        """
        # Reference: 23:00 UTC on Jan 29 = 02:00 Istanbul on Jan 30
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 23, 0, 0))
        text = "18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="Europe/Istanbul",
            languages=["tr"],
        )
        
        assert result is not None
        # In Istanbul, it's already Jan 30 early morning
        # So 18:00 on Jan 30 Istanbul = 15:00 UTC on Jan 30
        local_result = result.astimezone(pytz.timezone("Europe/Istanbul"))
        assert local_result.day == 30
        assert local_result.hour == 18

    def test_exact_time_boundary(self):
        """
        Test when reference time is exactly the same as requested time.
        Should schedule for tomorrow.
        """
        # Reference: exactly 18:00 UTC
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 18, 0, 0))
        text = "18de baslarim"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["tr"],
        )
        
        assert result is not None
        # Current time is 18:00, so 18:00 today has passed (or is exactly now)
        # Should schedule tomorrow
        assert result.day == 30
        assert result.hour == 18


class TestEnglishTimeParsingWithReference:
    """Tests for English time parsing with proper reference handling."""

    def test_this_evening_7pm(self):
        """
        'this evening at 7pm' should schedule for today at 19:00.
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        text = "this evening at 7pm"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["en"],
        )
        
        assert result is not None
        assert result.day == 29
        assert result.hour == 19

    def test_7pm_after_passed(self):
        """
        '7pm' when it's already 9pm should schedule tomorrow.
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 21, 0, 0))
        text = "7pm meeting"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["en"],
        )
        
        assert result is not None
        assert result.day == 30  # Tomorrow
        assert result.hour == 19

    def test_tomorrow_at_3pm(self):
        """
        'tomorrow at 3pm' should schedule for next day.
        """
        reference_dt_utc = pytz.UTC.localize(datetime(2026, 1, 29, 10, 0, 0))
        text = "tomorrow at 3pm"
        
        result = parse_datetime_from_text(
            text,
            reference_dt_utc,
            tz_name="UTC",
            languages=["en"],
        )
        
        assert result is not None
        assert result.day == 30
        assert result.hour == 15
