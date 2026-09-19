"""Detect timetable rows, period columns, and vector lesson rectangles."""

from dataclasses import dataclass
from typing import Any

import pymupdf

DAY_NAMES = {"Mo": "Monday", "Tu": "Tuesday", "We": "Wednesday", "Th": "Thursday", "Fr": "Friday"}


@dataclass(slots=True)
class PeriodColumn:
    number: int
    center: float
    left: float
    right: float
    start_time: str = ""
    end_time: str = ""


@dataclass(slots=True)
class DayRow:
    abbreviation: str
    name: str
    top: float
    bottom: float


@dataclass(slots=True)
class GridGeometry:
    periods: list[PeriodColumn]
    days: list[DayRow]
    lesson_rects: list[pymupdf.Rect]


def _word_text(word: tuple[Any, ...]) -> str:
    return str(word[4]).strip()


class GridDetector:
    """Infer the grid from positioned headings and filled vector rectangles."""

    def detect(self, page: pymupdf.Page) -> GridGeometry:
        words = page.get_text("words", sort=True)
        periods = self._periods(words, page.rect.height)
        days = self._days(words, periods)
        rects = self._lesson_rectangles(page, periods, days)
        if not rects:
            rects = self._occupied_grid_rectangles(page, words, periods, days)
        return GridGeometry(periods, days, rects)

    def _periods(self, words: list[tuple[Any, ...]], page_height: float) -> list[PeriodColumn]:
        candidates: list[tuple[int, float, float]] = []
        for word in words:
            text = _word_text(word)
            if text.isdigit() and 1 <= int(text) <= 20 and float(word[1]) < 0.25 * page_height:
                candidates.append((int(text), (float(word[0]) + float(word[2])) / 2, float(word[3])))
        # Select the longest monotonic run of consecutive period numbers.
        candidates.sort(key=lambda item: item[1])
        run: list[tuple[int, float, float]] = []
        for item in candidates:
            if not run or item[0] == run[-1][0] + 1:
                run.append(item)
            elif item[0] == 1:
                run = [item]
        if len(run) < 2:
            return []
        gaps = [run[i + 1][1] - run[i][1] for i in range(len(run) - 1)]
        gap = sorted(gaps)[len(gaps) // 2]
        columns = [
            PeriodColumn(number, center, center - gap / 2, center + gap / 2)
            for number, center, _ in run
        ]
        header_bottom = max(item[2] for item in run)
        header_words = [w for w in words if header_bottom <= float(w[1]) <= header_bottom + 30]
        for column in columns:
            text = " ".join(_word_text(w) for w in header_words if column.left <= (float(w[0]) + float(w[2])) / 2 <= column.right)
            from .time_parser import extract_explicit_time
            parsed = extract_explicit_time(text)
            if parsed:
                column.start_time, column.end_time = parsed
        return columns

    def _days(self, words: list[tuple[Any, ...]], periods: list[PeriodColumn]) -> list[DayRow]:
        labels = []
        for word in words:
            text = _word_text(word)
            if text in DAY_NAMES:
                labels.append((text, (float(word[1]) + float(word[3])) / 2))
        labels.sort(key=lambda item: item[1])
        if not labels:
            return []
        gaps = [labels[i + 1][1] - labels[i][1] for i in range(len(labels) - 1)]
        gap = sorted(gaps)[len(gaps) // 2] if gaps else 80.0
        return [DayRow(abbr, DAY_NAMES[abbr], center - gap / 2, center + gap / 2) for abbr, center in labels]

    def _lesson_rectangles(self, page: pymupdf.Page, periods: list[PeriodColumn], days: list[DayRow]) -> list[pymupdf.Rect]:
        if not periods or not days:
            return []
        period_width = periods[0].right - periods[0].left
        grid_left, grid_right = periods[0].left - period_width * 0.05, periods[-1].right + period_width * 0.05
        rects: list[pymupdf.Rect] = []
        for drawing in page.get_drawings():
            rect = pymupdf.Rect(drawing["rect"])
            center_y = (rect.y0 + rect.y1) / 2
            in_day = any(row.top <= center_y <= row.bottom for row in days)
            if drawing.get("fill") is not None and in_day and rect.x0 >= grid_left and rect.x1 <= grid_right and rect.width >= period_width * 0.75 and rect.height > 20:
                if not any(self._near(rect, old) for old in rects):
                    rects.append(rect)
        return sorted(rects, key=lambda rect: (rect.y0, rect.x0))

    def _occupied_grid_rectangles(
        self,
        page: pymupdf.Page,
        words: list[tuple[Any, ...]],
        periods: list[PeriodColumn],
        days: list[DayRow],
    ) -> list[pymupdf.Rect]:
        """Find text-bearing cells when aSc emits only grid strokes.

        Some class-wise designs do not paint lesson backgrounds. They do draw a
        full cell grid and use an internal horizontal stroke when one period is
        split between groups. Each text-bearing (sub-)cell is a lesson block.
        """
        drawings = page.get_drawings()
        rects: list[pymupdf.Rect] = []
        for row in days:
            for column in periods:
                cell = pymupdf.Rect(column.left, row.top, column.right, row.bottom)
                split_positions: list[float] = []
                for drawing in drawings:
                    line = pymupdf.Rect(drawing["rect"])
                    if drawing.get("type") != "s" or line.height > 1.0:
                        continue
                    overlap = max(0.0, min(cell.x1, line.x1) - max(cell.x0, line.x0))
                    if (
                        overlap >= cell.width * 0.75
                        and row.top + 3.0 < line.y0 < row.bottom - 3.0
                        and not any(abs(line.y0 - old) <= 1.0 for old in split_positions)
                    ):
                        split_positions.append(line.y0)
                boundaries = [row.top, *sorted(split_positions), row.bottom]
                for top, bottom in zip(boundaries, boundaries[1:]):
                    candidate = pymupdf.Rect(cell.x0, top, cell.x1, bottom)
                    if self._contains_text(candidate, words):
                        rects.append(candidate)
        return sorted(rects, key=lambda rect: (rect.y0, rect.x0))

    @staticmethod
    def _contains_text(rect: pymupdf.Rect, words: list[tuple[Any, ...]]) -> bool:
        return any(
            rect.contains(pymupdf.Point(
                (float(word[0]) + float(word[2])) / 2,
                (float(word[1]) + float(word[3])) / 2,
            ))
            for word in words
        )

    @staticmethod
    def _near(a: pymupdf.Rect, b: pymupdf.Rect, tolerance: float = 1.0) -> bool:
        return max(abs(a.x0-b.x0), abs(a.y0-b.y0), abs(a.x1-b.x1), abs(a.y1-b.y1)) <= tolerance
