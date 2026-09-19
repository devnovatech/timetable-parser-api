"""High-level fault-tolerant parser for teacher-wise aSc PDF exports."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

import pymupdf

from models import TimetableSlot
from .grid_detector import DayRow, GridDetector, GridGeometry, PeriodColumn
from .lesson_parser import parse_class_lesson, parse_lesson

ProgressCallback = Callable[[int, int, str], None]


@dataclass(slots=True, frozen=True)
class PageIdentity:
    kind: Literal["teacher", "class", "unknown"]
    name: str


@dataclass(slots=True)
class DebugWord:
    page_number: int
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(slots=True)
class ParseResult:
    source_file: str
    page_count: int = 0
    slots: list[TimetableSlot] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    debug_words: dict[int, list[DebugWord]] = field(default_factory=dict)

    @property
    def teachers(self) -> list[str]:
        return sorted({slot.teacher for slot in self.slots if slot.teacher})

    def to_dict(self) -> dict[str, object]:
        return {
            "sourceFile": self.source_file,
            "teachersDetected": len(self.teachers),
            "slotsDetected": len(self.slots),
            "warnings": self.warnings,
            "slots": [slot.to_dict(camel_case=True) for slot in self.slots],
        }


class AscTimetableParser:
    """Parse a PDF with vector cells and coordinate-positioned text."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.grid_detector = GridDetector()
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def extract_teacher(page: pymupdf.Page) -> str:
        """Extract `Teacher <name>` from top-positioned words."""
        words = page.get_text("words", sort=True)
        top = [w for w in words if float(w[1]) < page.rect.height * 0.15]
        top.sort(key=lambda w: (int(w[5]), int(w[6]), int(w[7])))
        lines: dict[tuple[int, int], list[str]] = {}
        for word in top:
            lines.setdefault((int(word[5]), int(word[6])), []).append(str(word[4]))
        for values in lines.values():
            text = " ".join(values).strip()
            match = re.search(r"\bTeacher\s+(.+)$", text, re.IGNORECASE)
            if match:
                return match.group(1).strip(" :-")
        return ""

    @staticmethod
    def extract_class(page: pymupdf.Page) -> str:
        """Extract the large class title used by class-wise aSc pages."""
        words = page.get_text("words", sort=True)
        top = [word for word in words if float(word[3]) <= page.rect.height * 0.11]
        lines: dict[tuple[int, int], list[tuple[object, ...]]] = {}
        for word in top:
            lines.setdefault((int(word[5]), int(word[6])), []).append(word)
        candidates: list[tuple[float, str]] = []
        for line_words in lines.values():
            line_words.sort(key=lambda word: float(word[0]))
            text = " ".join(str(word[4]) for word in line_words).strip()
            height = max(float(word[3]) - float(word[1]) for word in line_words)
            if text and not re.match(r"^Teacher\b", text, re.IGNORECASE):
                candidates.append((height, text))
        if not candidates:
            return ""
        _, title = max(candidates, key=lambda candidate: candidate[0])
        return re.sub(r"^Class(?:es)?\s*[:\-]?\s*", "", title, flags=re.IGNORECASE).strip()

    @classmethod
    def detect_page_identity(cls, page: pymupdf.Page) -> PageIdentity:
        teacher = cls.extract_teacher(page)
        if teacher:
            return PageIdentity("teacher", teacher)
        class_name = cls.extract_class(page)
        if class_name:
            return PageIdentity("class", class_name)
        return PageIdentity("unknown", "")

    def parse(self, pdf_path: str | Path, progress: ProgressCallback | None = None) -> ParseResult:
        path = Path(pdf_path).expanduser().resolve()
        result = ParseResult(str(path))
        self.logger.info("Uploaded file: %s", path)
        try:
            document = pymupdf.open(path)
        except Exception as exc:
            self.logger.exception("Unable to open PDF")
            raise ValueError(f"Unable to open PDF: {exc}") from exc
        try:
            if document.needs_pass:
                raise ValueError("The PDF is password-protected")
            if document.page_count == 0:
                raise ValueError("The PDF contains no pages")
            result.page_count = document.page_count
            seen: set[tuple[object, ...]] = set()
            for index in range(document.page_count):
                page_number = index + 1
                try:
                    page = document[index]
                    self._capture_debug(page, page_number, result)
                    identity = self.detect_page_identity(page)
                    if identity.kind == "unknown":
                        result.warnings.append(f"Page {page_number}: Teacher/class page title not detected")
                    geometry = self.grid_detector.detect(page)
                    if not geometry.days or not geometry.periods:
                        result.warnings.append(f"Page {page_number}: Timetable grid could not be determined")
                        continue
                    if not geometry.lesson_rects:
                        result.warnings.append(f"Page {page_number}: No occupied lesson cells detected")
                        continue
                    self._parse_page(page, page_number, identity, geometry, result, seen)
                    self.logger.info("Processed page %s (%s %s): %s lesson blocks", page_number, identity.kind, identity.name, len(geometry.lesson_rects))
                except Exception as exc:
                    message = f"Page {page_number}: {type(exc).__name__}: {exc}"
                    result.warnings.append(message)
                    self.logger.exception(message)
                finally:
                    if progress:
                        progress(page_number, document.page_count, f"Processed page {page_number}")
        finally:
            document.close()
        self.logger.info("Pages processed=%s teachers=%s slots=%s warnings=%s", result.page_count, len(result.teachers), len(result.slots), len(result.warnings))
        return result

    def _parse_page(self, page: pymupdf.Page, page_number: int, identity: PageIdentity, geometry: GridGeometry, result: ParseResult, seen: set[tuple[object, ...]]) -> None:
        words = page.get_text("words", sort=True)
        missing_rooms = 0
        for rect in geometry.lesson_rects:
            day = self._day_for(rect, geometry.days)
            start_col, end_col = self._period_span(rect, geometry.periods)
            if identity.kind == "class":
                class_content = parse_class_lesson(words, rect)
                teacher = class_content.teacher
                class_name = identity.name
                subject = class_content.subject
                room = class_content.room
                lesson_type = class_content.lesson_type
                explicit_time = class_content.explicit_time
            else:
                teacher_content = parse_lesson(words, rect)
                teacher = identity.name
                class_name = teacher_content.class_name
                subject = teacher_content.subject
                room = teacher_content.room
                lesson_type = teacher_content.lesson_type
                explicit_time = teacher_content.explicit_time
            start_time = start_col.start_time if start_col else ""
            end_time = end_col.end_time if end_col else ""
            if explicit_time:
                start_time, end_time = explicit_time
            confidence = sum((
                0.20 if teacher else 0,
                0.15 if day else 0,
                0.20 if start_time and end_time and start_col and end_col else 0,
                0.15 if class_name else 0,
                0.15 if subject else 0,
                0.15 if room else 0,
            ))
            confidence = min(1.0, round(confidence, 2))
            slot = TimetableSlot(
                teacher=teacher or "Unknown", day=day.name if day else "Unknown",
                start_time=start_time, end_time=end_time,
                start_period=start_col.number if start_col else None,
                end_period=end_col.number if end_col else None,
                class_name=class_name, subject=subject, room=room,
                lesson_type=lesson_type, page_number=page_number,
                confidence=confidence, status="OK" if confidence >= 0.80 else "REVIEW",
            )
            key = (slot.teacher, slot.day, slot.start_period, slot.end_period, slot.class_name, slot.subject, slot.room)
            if key in seen:
                result.warnings.append(f"Page {page_number}: Duplicate lesson skipped ({slot.day}, period {slot.start_period})")
                continue
            seen.add(key)
            result.slots.append(slot)
            if not class_name:
                result.warnings.append(f"Page {page_number}: Class not detected ({slot.day}, period {slot.start_period})")
            if not room:
                missing_rooms += 1
                if identity.kind != "class":
                    result.warnings.append(f"Page {page_number}: Room not detected ({slot.day}, period {slot.start_period})")
            if not teacher:
                result.warnings.append(f"Page {page_number}: Teacher not detected ({slot.day}, period {slot.start_period})")
            if not end_time:
                result.warnings.append(f"Page {page_number}: Could not confidently determine end time")
        if identity.kind == "class" and missing_rooms:
            result.warnings.append(
                f"Page {page_number}: Room is not printed for {missing_rooms} lesson(s) in this class-wise layout"
            )

    @staticmethod
    def _day_for(rect: pymupdf.Rect, days: list[DayRow]) -> DayRow | None:
        center = (rect.y0 + rect.y1) / 2
        return next((row for row in days if row.top <= center <= row.bottom), None)

    @staticmethod
    def _period_span(rect: pymupdf.Rect, periods: list[PeriodColumn]) -> tuple[PeriodColumn | None, PeriodColumn | None]:
        covered = [col for col in periods if rect.x0 < col.center < rect.x1]
        if covered:
            return covered[0], covered[-1]
        return None, None

    @staticmethod
    def _capture_debug(page: pymupdf.Page, page_number: int, result: ParseResult) -> None:
        result.debug_words[page_number] = [
            DebugWord(page_number, str(w[4]), float(w[0]), float(w[1]), float(w[2]), float(w[3]))
            for w in page.get_text("words", sort=True)
        ]
