"""Parse positioned text inside one detected lesson rectangle."""

from dataclasses import dataclass
from typing import Any

import pymupdf

from .normalizer import classify_lesson, clean_text, find_room, looks_like_class, normalize_class_name, normalize_multiline_subject
from .time_parser import extract_explicit_time


@dataclass(slots=True)
class LessonContent:
    class_name: str
    subject: str
    room: str
    lesson_type: str
    explicit_time: tuple[str, str] | None


@dataclass(slots=True)
class ClassLessonContent:
    teacher: str
    subject: str
    room: str
    lesson_type: str
    explicit_time: tuple[str, str] | None


def _lines_in_rect(words: list[tuple[Any, ...]], rect: pymupdf.Rect) -> list[str]:
    inside = [w for w in words if rect.contains(pymupdf.Point((float(w[0])+float(w[2]))/2, (float(w[1])+float(w[3]))/2))]
    inside.sort(key=lambda w: (int(w[5]), int(w[6]), int(w[7])))
    groups: dict[tuple[int, int], list[str]] = {}
    for word in inside:
        groups.setdefault((int(word[5]), int(word[6])), []).append(str(word[4]))
    return [" ".join(values).strip() for values in groups.values() if values]


def parse_lesson(words: list[tuple[Any, ...]], rect: pymupdf.Rect) -> LessonContent:
    lines = _lines_in_rect(words, rect)
    full_text = "\n".join(lines)
    explicit = extract_explicit_time(full_text.replace("\n", " "))
    room = find_room(full_text)
    class_lines: list[str] = []
    subject_lines: list[str] = []
    room_lower = room.lower()
    for line in lines:
        compact = line.strip()
        if not compact or extract_explicit_time(compact):
            continue
        if room and (compact.lower() in room_lower or room_lower in compact.lower()):
            continue
        if looks_like_class(compact) or (class_lines and compact.startswith("(")):
            class_lines.append(compact)
        else:
            subject_lines.append(compact)
    class_name = normalize_class_name(class_lines)
    subject = normalize_multiline_subject(subject_lines)
    return LessonContent(class_name, subject, room, classify_lesson(subject, room), explicit)


def parse_class_lesson(words: list[tuple[Any, ...]], rect: pymupdf.Rect) -> ClassLessonContent:
    """Parse the observed aSc class-page layout.

    In the supplied class-wise design the subject occupies the upper portion of
    each cell and the teacher is the final text line. A horizontal vector line
    splits simultaneous group lessons before this function is called.
    """
    lines = _lines_in_rect(words, rect)
    full_text = "\n".join(lines)
    explicit = extract_explicit_time(full_text.replace("\n", " "))
    room = find_room(full_text)
    content_lines: list[str] = []
    room_lower = room.lower()
    for line in lines:
        compact = clean_text(line)
        if not compact or extract_explicit_time(compact):
            continue
        if room and (compact.lower() in room_lower or room_lower in compact.lower()):
            continue
        content_lines.append(compact)
    teacher = content_lines[-1] if len(content_lines) >= 2 else ""
    subject_lines = content_lines[:-1] if teacher else content_lines
    subject = normalize_multiline_subject(subject_lines)
    return ClassLessonContent(teacher, subject, room, classify_lesson(subject, room), explicit)
