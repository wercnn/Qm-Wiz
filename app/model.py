"""The only place that talks to a language model.

generate_prep() writes the brief and flashcards for one deck. plan_order() puts a batch of
unnumbered decks in lecture order. To use a local model later, replace these two and keep
the same return shapes.
"""
from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel
from pypdf import PdfReader

from . import config


logging.getLogger("pypdf").setLevel(logging.ERROR)  # slide PDFs are often slightly broken


class Term(BaseModel):
    term: str
    definition: str


class Card(BaseModel):
    question: str
    answer: str
    slide: int


class Prep(BaseModel):
    is_lecture_slides: bool
    module: str
    week: int
    topic: str
    overview: str
    covers: list[str]
    key_terms: list[Term]
    link_to_last_week: str
    questions: list[str]
    cards: list[Card]


PROMPT = """You are preparing a university student for a lecture they have not attended yet.
The attached PDF was downloaded from the university's course site.

The student takes these modules:
{modules}

First decide what the PDF is:
- is_lecture_slides: true only if it is a lecturer's slide deck or lecture notes for one of
  the modules above. A lab sheet, coursework brief, paper or anything else is false; then
  fill the other fields with empty values.
- module: the module code it belongs to, exactly as written above.
- week: the week or lecture number if the slides state one (for example "Week 5" or
  "Lecture 5"), otherwise 0. Do not guess.

Then write for a final-year computer science student who has 3 minutes before the lecture
starts. Use plain, direct English. Use only what is in the slides; do not add outside
material. If the slides are unclear about something, leave it out.

- topic: the lecture's topic in 2 to 6 words, as it would appear in a file name. No week number, no module code.
- overview: 2 or 3 sentences saying what this lecture is about and why it matters in the module.
- covers: 3 to 5 bullet points, in slide order. Each is one full sentence saying what is explained, not a copied slide heading.
- key_terms: the 5 to 8 terms the student most needs to recognise, each with a one-line definition in your own simple words.
- link_to_last_week: 1 or 2 sentences on how this builds on the module's previous lecture, using the earlier-lecture summaries listed under the module. If none are listed, say what earlier knowledge the slides assume instead.
- questions: 2 or 3 questions to keep in mind during the lecture. They should need understanding to answer, not recall.
- cards: 8 to 10 flashcards. Each question tests one idea and has a short answer (under 30 words). Spread them across the whole deck. Ask about the subject itself, never about module admin (aims, assessment, staff, tools used). "slide" is the PDF page number (first page is 1) where the answer is shown.
"""


def extract_text(pdf_path: Path) -> list[str]:
    """Text of each page. Used to recognise the module and as a fallback input."""
    try:
        return [page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages]
    except Exception:
        return []


# Models that ran out of quota or were unavailable since the app started.
_skip: set[str] = set()


def _generate(contents: list, schema: type[BaseModel], temperature: float, client=None) -> str:
    """One Gemini request. Moves to the next model when one is out of quota or unavailable."""
    from google import genai
    from google.genai import errors, types

    client = client or genai.Client(api_key=config.GEMINI_API_KEY)
    settings = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema, temperature=temperature
    )
    names = [config.GEMINI_MODEL, *config.GEMINI_FALLBACK_MODELS]
    last_error: Exception | None = None
    for name in [n for n in dict.fromkeys(names) if n not in _skip]:
        try:
            return client.models.generate_content(model=name, contents=contents, config=settings).text
        except errors.APIError as error:
            if error.code not in (404, 429, 500, 503):
                raise
            _skip.add(name)
            last_error = error
    raise RuntimeError(f"No Gemini model is available right now ({last_error}).")


def _ask_gemini(prompt: str, pdf_path: Path) -> Prep:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    try:
        if pdf_path.stat().st_size > 12_000_000:
            pdf = client.files.upload(file=pdf_path)  # too big to send inline
        else:
            pdf = types.Part.from_bytes(data=pdf_path.read_bytes(), mime_type="application/pdf")
        reply = _generate([pdf, prompt], Prep, 0.3, client)
    except RuntimeError:
        raise
    except Exception:
        # Fallback: send the extracted text, page by page, instead of the PDF itself.
        pages = extract_text(pdf_path)
        if not any(pages):
            raise
        text = "\n\n".join(f"[Slide {i}]\n{page}" for i, page in enumerate(pages, 1))
        reply = _generate([prompt, text], Prep, 0.3, client)
    return Prep.model_validate_json(reply)


def generate_prep(pdf_path: Path, modules: list[dict]) -> dict:
    """Make the brief and flashcards for one slide deck. One model call per deck.

    modules is the list the deck could belong to (one entry if the module is already known).
    Each entry has "code", "title", "next_lecture" (datetime) and "earlier" (a list of
    "Week N: overview" strings for lectures that already have a brief).
    The reply says which module and week the deck is for, so file names do not matter.
    """
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and add a key.")
    lines = []
    for m in modules:
        lines.append(f"- {m['code']} {m['title']}. Next lecture: {m['next_lecture']:%A %d %B %Y, %H:%M}.")
        lines += [f"    Earlier lecture, {text}" for text in m["earlier"]]
    return _ask_gemini(PROMPT.format(modules="\n".join(lines)), Path(pdf_path)).model_dump()


class DeckPlace(BaseModel):
    file: str
    lecture_number: int
    main: bool


class DeckOrder(BaseModel):
    decks: list[DeckPlace]


ORDER_PROMPT = """A student downloaded all the slide decks for the module "{title}" at once.
The file names carry no dates. Work out which lecture of the term each deck belongs to.

Decks (file name, first slide, and the lecture number if the deck states one):
{decks}

What the slides say about the order of topics:
{syllabus}

Lectures that already have slides filed (do not reuse these numbers for a main deck):
{placed}

The module has {count} lectures. For each deck return:
- file: the file name exactly as given.
- lecture_number: 1 for the first lecture of term, 2 for the second, and so on. Follow the
  stated numbers and the order of topics above. Several decks can share a lecture.
- main: true for the one main deck of each lecture; false for extra decks taught in the
  same lecture (recaps, discussion or exercise slides, deeper dives).
"""


def plan_order(title: str, decks: list[dict], syllabus: str, count: int, placed: list[str]) -> list[dict]:
    """Put a batch of unnumbered decks in lecture order. Sends only titles, not the PDFs."""
    lines = "\n".join(
        f"- {d['file']} | {d['first_slide']} | {d['week'] or 'not stated'}" for d in decks
    )
    prompt = ORDER_PROMPT.format(title=title, decks=lines, syllabus=syllabus or "Nothing.", count=count,
        placed="\n".join(placed) or "None.",
    )
    reply = _generate([prompt], DeckOrder, 0)
    return DeckOrder.model_validate_json(reply).model_dump()["decks"]
