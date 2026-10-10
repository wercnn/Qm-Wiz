# QM Wiz

A study companion that prepares you for lectures without being asked.

Built for an "invisible AI" hackathon: there is no prompt box and nothing to upload.

## What it does

1. Reads your university timetable (`.ics`).
2. Watches your Downloads folder. When you download a PDF from the university course site, it reads it and works out which module and week it is for. File names do not matter.
3. Files the PDF in a tidy folder: `~/Documents/QMUL/ECS640U Big Data Processing/Week 04 - <topic>.pdf`.
4. Writes a one-page pre-lecture brief and 8 to 10 flashcards, each with the slide it came from.
5. Shows them on a Today page next to your next lecture, and sends a desktop notification.
6. Keeps every earlier week's brief and flashcards, per module.

If a lecturer posts the whole term at once, download the folder: it works out which deck belongs to which week from the syllabus slide.

You download slides as you always do. Everything else happens on its own.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then add your Gemini API key
.venv/bin/uvicorn app.main:app
```

Open http://localhost:8000. Download a slide PDF for one of the modules in the timetable and watch the page.

The repo includes a two-week sample timetable (`data/timetable.sample.ics`). To use your own, save it as `data/timetable.ics`.

The "Demo clock" menu runs the app as if it is 8am on a lecture day.

## How it works

| File | Job |
| --- | --- |
| `app/timetable.py` | Reads the timetable and finds each module's next lecture |
| `app/watcher.py` | Notices new PDFs in the watched folder |
| `app/prep.py` | Recognises the module, calls the model, caches the result, files the PDF |
| `app/model.py` | The only place that calls a model (`generate_prep`) |
| `app/main.py` | FastAPI server and API for the page |
| `static/` | The Today page |

Output is saved to `output/<module>/<lecture date>/` as `brief.md`, `cards.json` and `prep.json`. The same PDF is never sent to the model twice.

## Privacy

- Only PDFs that were downloaded from the university course site (macOS records where a file came from), or that name one of your modules, are looked at. Any other PDF is never sent anywhere and never moved.
- Lab sheets and coursework briefs are recognised and left where they are.
- PDFs that were already in Downloads when the app started are ignored.
- No university password is asked for or stored.
- This demo sends matched slides to the Gemini API. All model calls go through one function so it can be swapped for a local model, which is the plan for a real version.

## Not done yet

- Downloading slides from QMplus automatically (needs an approved, read-only integration with the university).
- Coursework deadlines on the Today page.
- A local model option.
