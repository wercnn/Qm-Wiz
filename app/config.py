"""Paths and settings. Everything that might change between laptops lives here."""
import os
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

TZ = ZoneInfo("Europe/London")

# The full timetable is personal and git-ignored. The sample is committed so the repo runs for anyone.
_full = ROOT / "data" / "timetable.ics"
TIMETABLE = _full if _full.exists() else ROOT / "data" / "timetable.sample.ics"

# Monday of teaching week 1, used to work out "Week 04" when filing slides.
TERM_START = date(2026, 9, 21)

# Where new slide PDFs show up, and where they are filed.
WATCH_DIR = Path(os.getenv("QMWIZ_WATCH_DIR", "~/Downloads")).expanduser()
LIBRARY_DIR = Path(os.getenv("QMWIZ_LIBRARY_DIR", "~/Documents/QMUL")).expanduser()

OUTPUT_DIR = ROOT / "output"
STATIC_DIR = ROOT / "static"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
# Tried in order when the first model is out of free quota (20 requests a day per model) or busy.
GEMINI_FALLBACK_MODELS = [
    name.strip()
    for name in os.getenv(
        "GEMINI_FALLBACK_MODELS", "gemini-3.8-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite"
    ).split(",")
    if name.strip()
]
