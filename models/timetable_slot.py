"""Structured timetable records independent of the GUI and PDF library."""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(slots=True)
class TimetableSlot:
    teacher: str
    day: str
    start_time: str
    end_time: str
    start_period: int | None
    end_period: int | None
    class_name: str
    subject: str
    room: str
    lesson_type: str
    page_number: int
    confidence: float
    status: str

    def to_dict(self, camel_case: bool = False) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        data = asdict(self)
        if not camel_case:
            return data
        names = {
            "start_time": "startTime", "end_time": "endTime",
            "start_period": "startPeriod", "end_period": "endPeriod",
            "class_name": "className", "lesson_type": "lessonType",
            "page_number": "pageNumber",
        }
        return {names.get(key, key): value for key, value in data.items()}

