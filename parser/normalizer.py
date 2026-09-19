"""Text normalization and timetable value recognition."""

import re

SPACE_RE = re.compile(r"\s+")
CLASS_RE = re.compile(
    r"\b(?:BS|ADP|MS|MPhil|PhD)[A-Za-z]*(?:[-_ ][A-Za-z0-9]+)+\b", re.IGNORECASE
)
ROOM_RE = re.compile(
    r"\b(?:Room[ \t]*[- ]?[ \t]*\w+|(?:[A-Za-z]+[ \t]+)?Lab[ \t]*[- ]?[ \t]*\w*)\b",
    re.IGNORECASE,
)


def clean_text(value: str) -> str:
    return SPACE_RE.sub(" ", value).strip()


def normalize_class_name(lines: list[str] | str) -> str:
    """Combine wrapped class designations without damaging their spelling."""
    values = [lines] if isinstance(lines, str) else lines
    text = clean_text(" ".join(value.strip() for value in values if value.strip()))
    return text.replace("_", "_")


def normalize_multiline_subject(lines: list[str]) -> str:
    """Join wrapped subject lines using single spaces."""
    return clean_text(" ".join(lines))


def find_room(text: str) -> str:
    matches = list(ROOM_RE.finditer(text))
    if not matches:
        return ""
    # Locations are conventionally the last matching line; this also avoids
    # mistaking a subject suffix such as "Database-Lab" for the location.
    return clean_text(matches[-1].group(0))


def looks_like_class(text: str) -> bool:
    value = clean_text(text)
    return bool(CLASS_RE.search(value) or re.match(r"^(?:BS|ADP|MS|PhD)", value, re.I))


def classify_lesson(subject: str, room: str) -> str:
    if re.search(r"(?:\bLab\b|-Lab\b)", f"{subject} {room}", re.IGNORECASE):
        return "LAB"
    if subject:
        return "THEORY"
    return "UNKNOWN"
