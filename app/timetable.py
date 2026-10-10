"""Read the QMUL timetable (.ics) and list lectures."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config

LECTURE_TYPES = ("Lecture", "Lecture - Live Online")


@dataclass
class Lecture:
    uid: str
    module: str  # e.g. ECS640U
    title: str  # e.g. Big Data Processing
    lecturer: str
    room: str
    start: datetime
    end: datetime

    @property
    def date(self) -> str:
        return self.start.strftime("%Y-%m-%d")

    @property
    def week(self) -> int:
        return (self.start.date() - config.TERM_START).days // 7 + 1


def read_events(path: Path) -> list[dict]:
    """Return each VEVENT as a dict of its fields, with folded lines joined."""
    lines: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)

    events, current = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            events.append(current)
            current = None
        elif current is not None and ":" in line:
            key, value = line.split(":", 1)
            current[key.split(";")[0]] = value.replace("\\,", ",").replace("\\n", " ").strip()
    return events


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=config.TZ)


def _split_summary(summary: str, description: str) -> tuple[str, str, str, str]:
    """Split a summary into module code, title, activity type and lecturer.

    Summary is "<code>-<run> <title> <activity code> <type>" and the description is
    "<activity code> <lecturer>", so the activity code is the part they share.
    """
    module = summary.split("-", 1)[0]
    words = description.split(" ")
    activity = ""
    for i in range(len(words), 0, -1):
        candidate = " ".join(words[:i])
        if f" {candidate} " in summary:
            activity = candidate
            break
    if not activity:
        return module, summary, "", ""
    before, after = summary.split(f" {activity} ", 1)
    title = before.split(" ", 1)[1] if " " in before else before
    lecturer = description[len(activity):].strip()
    return module, title, after.strip(), lecturer


def load_lectures(path: Path | None = None) -> list[Lecture]:
    """All lectures in the timetable, earliest first, one per UID."""
    lectures: dict[str, Lecture] = {}
    for event in read_events(path or config.TIMETABLE):
        module, title, kind, lecturer = _split_summary(
            event.get("SUMMARY", ""), event.get("DESCRIPTION", "")
        )
        if kind not in LECTURE_TYPES:
            continue
        location = event.get("LOCATION", "None")
        room = "Online" if location in ("", "None") else location.split(":")[-1]
        lectures[event["UID"]] = Lecture(
            uid=event["UID"],
            module=module,
            title=title,
            lecturer=lecturer,
            room=room,
            start=_parse_time(event["DTSTART"]),
            end=_parse_time(event["DTEND"]),
        )
    return sorted(lectures.values(), key=lambda lec: lec.start)


def modules(lectures: list[Lecture]) -> dict[str, str]:
    """Module code to title."""
    return {lec.module: lec.title for lec in lectures}


def next_lecture(lectures: list[Lecture], module: str, now: datetime) -> Lecture | None:
    """The module's next lecture that has not finished yet."""
    for lec in lectures:
        if lec.module == module and lec.end > now:
            return lec
    return None
