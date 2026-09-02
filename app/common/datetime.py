from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import jdatetime

IRAN_TIMEZONE = ZoneInfo("Asia/Tehran")

PERSIAN_DIGITS = str.maketrans(
    "0123456789",
    "۰۱۲۳۴۵۶۷۸۹",
)


def to_iran_datetime(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        value = value.replace(
            tzinfo=timezone.utc,
        )

    return value.astimezone(
        IRAN_TIMEZONE,
    )


def to_jalali_datetime(
    value: datetime | None,
) -> jdatetime.datetime | None:
    iran_datetime = to_iran_datetime(
        value,
    )

    if iran_datetime is None:
        return None

    return jdatetime.datetime.fromgregorian(
        datetime=iran_datetime,
    )


def format_iran_datetime(
    value: datetime | None,
) -> str:
    jalali_datetime = to_jalali_datetime(
        value,
    )

    if jalali_datetime is None:
        return "-"

    formatted = (
        f"{jalali_datetime.year:04d}/"
        f"{jalali_datetime.month:02d}/"
        f"{jalali_datetime.day:02d}"
        " - "
        f"{jalali_datetime.hour:02d}:"
        f"{jalali_datetime.minute:02d}:"
        f"{jalali_datetime.second:02d}"
    )

    return formatted.translate(
        PERSIAN_DIGITS,
    )
