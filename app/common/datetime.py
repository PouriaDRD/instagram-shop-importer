from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import jdatetime

IRAN_TIMEZONE = ZoneInfo("Asia/Tehran")

PERSIAN_DIGITS = str.maketrans(
    "0123456789",
    "۰۱۲۳۴۵۶۷۸۹",
)

PERSIAN_MONTHS: tuple[str, ...] = (
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


def to_persian_digits(
    value: str,
) -> str:
    return value.translate(
        PERSIAN_DIGITS,
    )


def to_iran_datetime(
    value: object,
) -> datetime | None:
    if not isinstance(
        value,
        datetime,
    ):
        return None

    normalized = value

    if normalized.tzinfo is None:
        normalized = normalized.replace(
            tzinfo=timezone.utc,
        )

    return normalized.astimezone(
        IRAN_TIMEZONE,
    )


def to_jalali_datetime(
    value: object,
) -> jdatetime.datetime | None:
    iran_datetime = to_iran_datetime(
        value,
    )

    if iran_datetime is None:
        return None

    return jdatetime.datetime.fromgregorian(
        datetime=iran_datetime,
    )


def format_iran_date(
    value: object,
) -> str:
    jalali = to_jalali_datetime(
        value,
    )

    if jalali is None:
        return "-"

    month_name = PERSIAN_MONTHS[jalali.month]

    result = f"{jalali.day} " f"{month_name} " f"{jalali.year}"

    return to_persian_digits(
        result,
    )


def format_iran_time(
    value: object,
) -> str:
    iran_datetime = to_iran_datetime(
        value,
    )

    if iran_datetime is None:
        return "-"

    result = f"{iran_datetime.hour:02d}:" f"{iran_datetime.minute:02d}"

    return to_persian_digits(
        result,
    )


def format_iran_datetime(
    value: object,
) -> str:
    date_text = format_iran_date(
        value,
    )

    time_text = format_iran_time(
        value,
    )

    if date_text == "-" or time_text == "-":
        return "-"

    return f"{date_text}، " f"ساعت {time_text}"
