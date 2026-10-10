"""FastAPI app: serves the Today page and starts the folder watcher.

Run with:  uvicorn app.main:app
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, prep, watcher
from .timetable import Lecture, load_lectures

app = FastAPI(title="QM Wiz")
lectures = load_lectures()

# Demo clock: how far the app's clock is shifted from the real one.
clock_shift = timedelta(0)


def now() -> datetime:
    return datetime.now(config.TZ) + clock_shift


@app.on_event("startup")
def start_watching() -> None:
    watcher.start(lambda path: prep.process_new(path, lectures, now()))
    prep.log(f"Watching {str(config.WATCH_DIR).replace(str(Path.home()), '~')} for new slides.")


def _describe(lecture: Lecture, with_prep: bool) -> dict:
    saved = prep.load_prep(lecture)
    key = f"{lecture.module}/{lecture.date}"
    status = "ready" if saved else "preparing" if key in prep.in_progress else "waiting"
    return {
        "id": key,
        "module": lecture.module,
        "title": lecture.title,
        "lecturer": lecture.lecturer,
        "room": lecture.room,
        "start": lecture.start.isoformat(),
        "end": lecture.end.isoformat(),
        "week": lecture.week,
        "past": lecture.end <= now(),
        "topic": saved["topic"] if saved else None,
        "status": status,
        "prep": saved if with_prep else None,
    }


@app.get("/api/today")
def today(show: str | None = None) -> dict:
    """Everything the Today page needs.

    "next" is the next lecture (or the one asked for with ?show=<module>/<date>).
    "next_24h" is F1: lectures starting in the next 24 hours. "upcoming" is the next 7 days.
    "history" is every lecture that has a brief, past weeks included, earliest first.
    """
    current = now()
    coming = [lec for lec in lectures if lec.end > current]
    week = [lec for lec in coming if lec.start < current + timedelta(days=7)]
    prepared = [lec for lec in lectures if prep.load_prep(lec)]
    chosen = next((lec for lec in lectures if f"{lec.module}/{lec.date}" == show), None)
    chosen = chosen or (coming[0] if coming else None)
    return {
        "now": current.isoformat(),
        "demo_clock": clock_shift != timedelta(0),
        "next": _describe(chosen, with_prep=True) if chosen else None,
        "next_24h": [
            f"{lec.module}/{lec.date}" for lec in week if lec.start < current + timedelta(hours=24)
        ],
        "upcoming": [_describe(lec, with_prep=False) for lec in week],
        "history": [_describe(lec, with_prep=False) for lec in prepared],
        "activity": prep.activity[-8:],
    }


class ClockRequest(BaseModel):
    at: str | None = None  # ISO time to jump to, or null to go back to the real time


@app.post("/api/clock")
def set_clock(request: ClockRequest) -> dict:
    """Demo control: run the app as if it is another time, e.g. 8am on lecture day."""
    global clock_shift
    if request.at:
        target = datetime.fromisoformat(request.at)
        if target.tzinfo is None:
            target = target.replace(tzinfo=config.TZ)
        clock_shift = target - datetime.now(config.TZ)
    else:
        clock_shift = timedelta(0)
    return {"now": now().isoformat()}


@app.get("/")
def page() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
