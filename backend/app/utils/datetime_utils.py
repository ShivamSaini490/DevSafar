import re
from datetime import date, datetime, time, timedelta, timezone

INDIA_TIME_ZONE = timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")

_DATE_WITH_YEAR_FORMATS = (
    "%d %b %Y",
    "%d %B %Y",
    "%b %d %Y",
    "%B %d %Y",
    "%d/%m/%Y",
)
_DATE_WITHOUT_YEAR_FORMATS = ("%d %b", "%d %B", "%b %d", "%B %d")
_DATETIME_WITH_YEAR_FORMATS = tuple(
    f"{date_format} {time_format}"
    for date_format in _DATE_WITH_YEAR_FORMATS
    for time_format in ("%H:%M", "%I:%M %p", "%I %p")
)
_DATETIME_WITHOUT_YEAR_FORMATS = tuple(
    f"{date_format} {time_format}"
    for date_format in _DATE_WITHOUT_YEAR_FORMATS
    for time_format in ("%H:%M", "%I:%M %p", "%I %p")
)
_DAYPART_PATTERN = r"subah|morning|dopahar|afternoon|shaam|evening|raat|night"
_TIME_WITH_PREFIX_RE = re.compile(
    rf"(?i)\b(?P<daypart>{_DAYPART_PATTERN})\s+"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?:baje|o'clock)?\b"
)
_TIME_WITH_SUFFIX_RE = re.compile(
    rf"(?i)\b(?P<hour>\d{{1,2}})(?::(?P<minute>\d{{2}}))?\s*baje"
    rf"(?:\s*(?P<daypart>{_DAYPART_PATTERN}))?\b"
)
_TIME_WITH_MERIDIEM_RE = re.compile(
    r"(?i)\b(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<daypart>am|pm)\b"
)
_TIME_24_HOUR_RE = re.compile(r"\b(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)\b")


def india_today() -> date:
    return india_now().date()


def india_now() -> datetime:
    return datetime.now(INDIA_TIME_ZONE)


def next_sensible_slot(value: datetime, *, minutes: int = 30) -> datetime:
    """Return the next strict clock slot in Asia/Kolkata."""

    localized = as_india_time(value).replace(second=0, microsecond=0)
    remainder = localized.minute % minutes
    advance = minutes - remainder if remainder else minutes
    return localized + timedelta(minutes=advance)


def _clean_human_datetime(value: str) -> str:
    cleaned = re.sub(r"(?i)(\d)(st|nd|rd|th)\b", r"\1", value.strip())
    cleaned = re.sub(r"(?i)\s+IST$", "", cleaned)
    return " ".join(cleaned.replace(",", " ").split())


def _roll_forward_year(value: date, *, not_before: date) -> date:
    candidate = value
    while candidate < not_before:
        candidate = candidate.replace(year=candidate.year + 1)
    return candidate


def parse_lenient_date(
    value: str,
    *,
    current_date: date,
    not_before: date | None = None,
) -> date:
    """Parse common model date strings and infer a missing future year."""

    cleaned = _clean_human_datetime(value)
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        pass
    for date_format in _DATE_WITH_YEAR_FORMATS:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    threshold = not_before or current_date
    for date_format in _DATE_WITHOUT_YEAR_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
        candidate = parsed.replace(year=current_date.year)
        return _roll_forward_year(candidate, not_before=threshold)
    raise ValueError("Unsupported date format")


def parse_lenient_india_datetime(
    value: str,
    *,
    current_date: date,
    not_before: date | None = None,
) -> datetime:
    """Parse common model deadlines and normalize them to Asia/Kolkata."""

    cleaned = _clean_human_datetime(value)
    try:
        return as_india_time(datetime.fromisoformat(cleaned.replace("Z", "+00:00")))
    except ValueError:
        pass
    for datetime_format in _DATETIME_WITH_YEAR_FORMATS:
        try:
            return as_india_time(datetime.strptime(cleaned, datetime_format))
        except ValueError:
            continue
    threshold = not_before or current_date
    for datetime_format in _DATETIME_WITHOUT_YEAR_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, datetime_format)
        except ValueError:
            continue
        candidate = parsed.replace(year=current_date.year)
        candidate_date = _roll_forward_year(candidate.date(), not_before=threshold)
        return as_india_time(candidate.replace(year=candidate_date.year))
    raise ValueError("Unsupported datetime format")


def extract_explicit_time(value: str) -> time | None:
    """Extract a user-written clock time, including common Hinglish dayparts."""

    matches = [
        match
        for pattern in (
            _TIME_WITH_PREFIX_RE,
            _TIME_WITH_SUFFIX_RE,
            _TIME_WITH_MERIDIEM_RE,
            _TIME_24_HOUR_RE,
        )
        for match in pattern.finditer(value)
    ]
    if not matches:
        return None
    match = max(matches, key=lambda item: item.start())
    hour = int(match.group("hour"))
    minute = int(match.groupdict().get("minute") or 0)
    daypart = (match.groupdict().get("daypart") or "").casefold()
    if hour > 23 or minute > 59:
        return None
    if daypart in {"subah", "morning", "am"}:
        hour = 0 if hour == 12 else hour
    elif daypart in {"dopahar", "afternoon", "shaam", "evening", "pm"}:
        if hour < 12:
            hour += 12
    elif daypart in {"raat", "night"}:
        if hour == 12:
            hour = 0
        elif hour < 12:
            hour += 12
    if hour > 23:
        return None
    return time(hour=hour, minute=minute)


def as_india_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=INDIA_TIME_ZONE)
    return value.astimezone(INDIA_TIME_ZONE)


def at_india_time(value: date, *, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(
        value,
        time(hour=hour, minute=minute),
        tzinfo=INDIA_TIME_ZONE,
    )
