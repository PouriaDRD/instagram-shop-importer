from __future__ import annotations

from datetime import datetime, timezone

from app.common.datetime import (
    format_iran_date,
    format_iran_datetime,
    format_iran_time,
    to_iran_datetime,
)


def test_utc_datetime_converts_to_tehran() -> None:
    value = datetime(
        2026,
        9,
        2,
        10,
        36,
        57,
        tzinfo=timezone.utc,
    )

    result = to_iran_datetime(value)

    assert result is not None

    assert result.hour == 14
    assert result.minute == 6


def test_naive_datetime_is_treated_as_utc() -> None:
    value = datetime(
        2026,
        9,
        2,
        10,
        36,
        57,
    )

    result = to_iran_datetime(value)

    assert result is not None
    assert result.hour == 14
    assert result.minute == 6


def test_jalali_date_is_correct() -> None:
    value = datetime(
        2026,
        9,
        2,
        10,
        36,
        57,
        tzinfo=timezone.utc,
    )

    assert format_iran_date(value) == "۱۱ شهریور ۱۴۰۵"


def test_iran_time_is_correct() -> None:
    value = datetime(
        2026,
        9,
        2,
        10,
        36,
        57,
        tzinfo=timezone.utc,
    )

    assert format_iran_time(value) == "۱۴:۰۶"


def test_full_iran_datetime_is_correct() -> None:
    value = datetime(
        2026,
        9,
        2,
        10,
        36,
        57,
        tzinfo=timezone.utc,
    )

    assert format_iran_datetime(value) == ("۱۱ شهریور ۱۴۰۵، " "ساعت ۱۴:۰۶")


def test_none_date_does_not_crash() -> None:
    assert format_iran_date(None) == "-"
    assert format_iran_time(None) == "-"
    assert format_iran_datetime(None) == "-"


def test_invalid_object_does_not_crash() -> None:
    assert format_iran_date("wrong") == "-"
    assert format_iran_time(123) == "-"
    assert format_iran_datetime(object()) == "-"
