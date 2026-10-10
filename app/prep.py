"""Turn a new slide PDF into a filed PDF plus a saved brief and flashcards."""
from __future__ import annotations

import hashlib
import json
import plistlib
import re
import shutil
import subprocess
import time
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import config, model
from .timetable import Lecture, modules, next_lecture

# Recent events shown on the Today page, newest last.
activity: list[dict] = []
# Lectures being worked on right now, as "<module>/<date>".
in_progress: set[str] = set()
# Files that could not be read because the free model requests ran out. Tried again later.
waiting: set[Path] = set()

OUT_OF_REQUESTS = ("Out of free AI requests for now. New slides stay in Downloads "
                   "and are prepared automatically when requests are available again.")


def notice() -> str | None:
    """Message for the top of the Today page, or None when all is well."""
    return OUT_OF_REQUESTS if waiting else None


def retry_waiting(lectures: list[Lecture], now: datetime) -> None:
    """Have another go at files that hit the request limit."""
    for path in sorted(waiting):
        waiting.discard(path)
        if path.exists():
            process_new(path, lectures, now)


def log(text: str, now: datetime | None = None) -> None:
    stamp = (now or datetime.now(config.TZ)).strftime("%H:%M:%S")
    activity.append({"time": stamp, "text": text})
    del activity[:-30]
    print(f"[{stamp}] {text}")


# Files downloaded from QMplus come from one of these hosts.
QMPLUS_HOSTS = ("qmplus.qmul.ac.uk", "qmul-moodle")


def from_qmplus(pdf_path: Path) -> bool:
    """True if macOS recorded that this file was downloaded from QMplus."""
    try:
        raw = subprocess.run(
            ["xattr", "-px", "com.apple.metadata:kMDItemWhereFroms", str(pdf_path)],
            capture_output=True, text=True, timeout=5,
        ).stdout
        sources = plistlib.loads(bytes.fromhex("".join(raw.split())))
    except Exception:
        return False
    return any(host in str(url) for url in sources for host in QMPLUS_HOSTS)


def detect_module(pdf_path: Path, lectures: list[Lecture]) -> str | None:
    """Work out which module a PDF belongs to, on this laptop, before anything is sent anywhere.

    Looks for a module code or module title in the file name and the first pages.
    A PDF that matches nothing is left alone and never sent to the model.
    """
    pages = model.extract_text(pdf_path)[:3]
    haystack = _squash(pdf_path.stem + " " + " ".join(pages))
    for code, title in modules(lectures).items():
        if _squash(code) in haystack:
            return code
    # Titles such as "Project" are too common to trust; only match longer ones.
    for code, title in modules(lectures).items():
        if len(title) > 10 and _squash(title) in haystack:
            return code
    return None


def detect_week(pdf_path: Path) -> int | None:
    """Teaching week named in the file name or first page, e.g. "Week 5" or "Lecture 05".

    Some modules post the whole term's slides at once, so "the next lecture" is not always right.
    """
    # A bare "W4" is only trusted in a file name.
    found = re.search(r"(?<![a-z])(?:week|wk|lecture|lec|w)[\s_.#-]*0?(\d{1,2})(?!\d)", pdf_path.stem, re.IGNORECASE)
    if not found:
        first_page = (model.extract_text(pdf_path)[:1] or [""])[0]
        found = re.search(r"(?:week|lecture)\s*0?(\d{1,2})(?!\d)", first_page[:300], re.IGNORECASE)
    if found:
        return int(found.group(1))
    return None


def pick_lecture(module: str, week: int | None, lectures: list[Lecture], now: datetime) -> Lecture | None:
    """The lecture some slides are for: the named week if there is one, else the next lecture."""
    for lec in lectures:
        if lec.module == module and lec.week == week:
            return lec
    return next_lecture(lectures, module, now)


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def out_dir(lecture: Lecture) -> Path:
    return config.OUTPUT_DIR / lecture.module / lecture.date


def load_prep(lecture: Lecture) -> dict | None:
    path = out_dir(lecture) / "prep.json"
    return json.loads(path.read_text()) if path.exists() else None


def _find_cached(sha: str) -> dict | None:
    """Earlier output for the very same PDF, wherever it was saved."""
    for path in config.OUTPUT_DIR.glob("*/*/prep.json"):
        saved = json.loads(path.read_text())
        if saved.get("pdf_sha256") == sha:
            return saved
    return None


def _earlier_overviews(module: str) -> list[str]:
    """Overviews of the module's lectures that already have a brief, oldest first."""
    found = []
    for path in sorted((config.OUTPUT_DIR / module).glob("*/prep.json")):
        saved = json.loads(path.read_text())
        found.append(f"week {saved.get('lecture_week', '?')} ({saved['topic']}): {saved['overview']}")
    return found[-3:]


def _brief_markdown(lecture: Lecture, prep: dict) -> str:
    lines = [
        f"# {lecture.module} {lecture.title}: {prep['topic']}",
        f"{lecture.start.strftime('%A %d %B %Y, %H:%M')}, {lecture.room}",
        "",
        prep["overview"],
        "",
        "## What it covers",
        *[f"- {item}" for item in prep["covers"]],
        "",
        "## Key terms",
        *[f"- **{t['term']}**: {t['definition']}" for t in prep["key_terms"]],
        "",
        "## Link to last week",
        prep["link_to_last_week"],
        "",
        "## Questions to think about",
        *[f"{i}. {q}" for i, q in enumerate(prep["questions"], 1)],
    ]
    return "\n".join(lines) + "\n"


def _file_slides(pdf_path: Path, lecture: Lecture, topic: str) -> Path:
    """Move the PDF to <library>/<code> <title>/Week NN - <topic>.pdf."""
    folder = config.LIBRARY_DIR / f"{lecture.module} {lecture.title}"
    folder.mkdir(parents=True, exist_ok=True)
    safe_topic = re.sub(r'[\\/:*?"<>|]', "", topic).strip() or pdf_path.stem
    target = folder / f"Week {lecture.week:02d} - {safe_topic}.pdf"
    n = 2
    while target.exists():
        target = folder / f"Week {lecture.week:02d} - {safe_topic} ({n}).pdf"
        n += 1
    shutil.move(str(pdf_path), str(target))
    return target


def _notify(title: str, text: str) -> None:
    """macOS notification. Does nothing on other systems."""
    try:
        script = f"display notification {json.dumps(text)} with title {json.dumps(title)}"
        subprocess.run(["osascript", "-e", script], timeout=5, capture_output=True)
    except Exception:
        pass


def process_pdf(
    pdf_path: Path, lectures: list[Lecture], now: datetime,
    module: str | None = None, lecture: Lecture | None = None,
) -> None:
    """Handle one new PDF: recognise it, make the brief and cards, save them, file the PDF.

    module and lecture are given when they are already known (decks from a folder).
    """
    known = module or detect_module(pdf_path, lectures)
    if known is None and not from_qmplus(pdf_path):
        return  # not from QMplus and no module name in it: leave it alone, send it nowhere

    titles = modules(lectures)
    candidates = [known] if known else list(titles)
    log(f"New file: {pdf_path.name}. Reading it.", now)
    guess = next_lecture(lectures, known, now) if known else None
    if guess:
        in_progress.add(f"{guess.module}/{guess.date}")
    started = time.time()
    try:
        sha = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
        prep = _find_cached(sha)
        if prep is None:
            prep = model.generate_prep(pdf_path, [
                {
                    "code": code,
                    "title": titles[code],
                    "next_lecture": (next_lecture(lectures, code, now) or lectures[-1]).start,
                    "earlier": _earlier_overviews(code),
                }
                for code in candidates
            ])
            prep["pdf_sha256"] = sha
        # The model sometimes answers "ECS640U Big Data Processing"; keep only the code.
        prep["module"] = known or next((code for code in titles if code in prep["module"]), "")
        if not prep["is_lecture_slides"] or not prep["module"]:
            log(f"{pdf_path.name} is not lecture slides. Left where it is.", now)
            return

        if lecture is None:
            week = detect_week(pdf_path) or prep["week"] or None
            lecture = pick_lecture(prep["module"], week, lectures, now)
        if lecture is None:
            log(f"{pdf_path.name}: {prep['module']} has no lectures left in the timetable.", now)
            return
        log(f"It is {lecture.module} {lecture.title}, week {lecture.week}: {prep['topic']}. "
            f"Lecture on {lecture.start.strftime('%a %d %b %H:%M')}.", now)

        filed = _file_slides(pdf_path, lecture, prep["topic"])
        prep["slides_file"] = str(filed).replace(str(Path.home()), "~")
        prep["lecture_week"] = lecture.week

        folder = out_dir(lecture)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prep.json").write_text(json.dumps(prep, indent=2))
        (folder / "brief.md").write_text(_brief_markdown(lecture, prep))
        (folder / "cards.json").write_text(json.dumps(prep["cards"], indent=2))

        log(f"Filed as {prep['slides_file']}.", now)
        log(f"Brief and {len(prep['cards'])} flashcards ready ({time.time() - started:.0f}s).", now)
        _notify(f"{lecture.module} brief is ready",
                f"{prep['topic']}. {lecture.start.strftime('%a %H:%M')}, {lecture.room}.")
    except model.QuotaError:
        waiting.add(pdf_path)
        log(f"Out of free AI requests. {pdf_path.name} will be prepared later.", now)
    except Exception as error:
        log(f"Could not prepare {pdf_path.name}: {str(error)[:160]}", now)
    finally:
        in_progress.clear()



def process_folder(folder: Path, lectures: list[Lecture], now: datetime) -> None:
    """Handle a folder of decks downloaded at once (QMplus "download folder").

    Such decks often have topic names and no week numbers. Their order is worked out from
    the weeks that are stated and from any syllabus slide, then each is handled in turn.
    """
    pdfs = sorted(folder.glob("*.pdf"))
    found = Counter(m for m in (detect_module(p, lectures) for p in pdfs) if m)
    if not found:
        return  # no module named anywhere in the folder: leave it alone
    module = found.most_common(1)[0][0]
    title = modules(lectures)[module]
    module_lectures = [lec for lec in lectures if lec.module == module]
    log(f"New folder: {folder.name}, {len(pdfs)} decks for {module} {title}. Working out the weeks.", now)

    decks, syllabus = [], []
    for pdf in pdfs:
        pages = model.extract_text(pdf)
        decks.append({
            "file": pdf.name,
            "first_slide": " ".join((pages[0] if pages else "").split())[:150],
            "week": detect_week(pdf),
        })
        syllabus += [" ".join(t.split())[:600] for t in pages[:8] if re.search(r"syllabus|schedule", t, re.I)]
    try:
        placed = [
            f"- lecture {n}: {saved['topic']}"
            for n, lec in enumerate(module_lectures, 1) if (saved := load_prep(lec))
        ]
        order = model.plan_order(title, decks, "\n".join(syllabus[:3]), len(module_lectures), placed)
    except model.QuotaError:
        waiting.add(folder)
        log(f"Out of free AI requests. {folder.name} will be prepared later.", now)
        return
    except Exception as error:
        log(f"Could not work out the weeks for {folder.name}: {str(error)[:160]}", now)
        return

    by_name = {pdf.name: pdf for pdf in pdfs}
    order = sorted((d for d in order if d["file"] in by_name), key=lambda d: (d["lecture_number"], not d["main"]))
    done_main: set[int] = set()
    for deck in order:
        number = deck["lecture_number"]
        if not 1 <= number <= len(module_lectures):
            continue
        lecture = module_lectures[number - 1]
        pdf = by_name[deck["file"]]
        # Never replace a brief that is already there with a different deck from a batch.
        if deck["main"] and number not in done_main and load_prep(lecture) is None:
            done_main.add(number)
            process_pdf(pdf, lectures, now, module=module, lecture=lecture)
        else:
            # Extra deck for the same lecture: file it next to the main one, no second brief.
            filed = _file_slides(pdf, lecture, re.sub(r"^week\s*\d+\s*", "", pdf.stem, flags=re.I))
            log(f"Extra slides for week {lecture.week} filed as {str(filed).replace(str(Path.home()), '~')}.", now)
    if not any(folder.iterdir()):
        folder.rmdir()


def process_new(path: Path, lectures: list[Lecture], now: datetime) -> None:
    """Entry point for anything new in the watched folder: a PDF, a folder, or a QMplus zip."""
    if path.is_dir():
        process_folder(path, lectures, now)
    elif path.suffix.lower() == ".zip":
        if from_qmplus(path) and not path.with_suffix("").exists():
            with zipfile.ZipFile(path) as archive:
                archive.extractall(path.with_suffix(""))
            process_folder(path.with_suffix(""), lectures, now)
    else:
        process_pdf(path, lectures, now)


if __name__ == "__main__":
    # Prepare PDFs or folders by hand, in the order given:  python -m app.prep ~/Downloads/a.pdf
    import sys
    from .timetable import load_lectures

    all_lectures = load_lectures()
    for name in sys.argv[1:]:
        process_new(Path(name).expanduser(), all_lectures, datetime.now(config.TZ))
