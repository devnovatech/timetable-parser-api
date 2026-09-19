"""Time extraction and normalization helpers."""

import re

EXPLICIT_TIME_RE = re.compile(
    r"(?<!\d)(\d{1,2}):([0-5]\d)\s*[-–—]\s*(\d{1,2}):([0-5]\d)(?!\d)"
)


def normalize_time(value: str) -> str:
    """Normalize a valid 12/24-hour-like time to HH:MM."""
    match = re.fullmatch(r"\s*(\d{1,2}):([0-5]\d)\s*", value)
    if not match:
        raise ValueError(f"Invalid time: {value!r}")
    hour = int(match.group(1))
    if hour > 23:
        raise ValueError(f"Invalid hour: {hour}")
    return f"{hour:02d}:{int(match.group(2)):02d}"


def extract_explicit_time(text: str) -> tuple[str, str] | None:
    match = EXPLICIT_TIME_RE.search(text)
    if not match:
        return None
    return normalize_time(f"{match[1]}:{match[2]}"), normalize_time(f"{match[3]}:{match[4]}")


def normalize_time_range(text: str) -> tuple[str, str] | None:
    return extract_explicit_time(text)

