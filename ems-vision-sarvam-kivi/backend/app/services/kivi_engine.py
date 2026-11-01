"""Kivi space: dictionary, shortcuts and styles stored as JSON, plus the text pipeline.

raw transcript -> dictionary replacer -> shortcut expander -> style formatter
"""
from __future__ import annotations

import difflib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, Field

from ..config.languages import MAX_KEYTERM_CHARS, MAX_KEYTERMS
from .sarvam_service import SarvamError, SarvamService

UNITS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
TEENS = {"ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
LETTER_NAMES = {"ay": "a", "bee": "b", "see": "c", "cee": "c", "dee": "d", "ee": "e", "eff": "f", "gee": "g", "jay": "j",
                "kay": "k", "el": "l", "em": "m", "en": "n", "pee": "p", "cue": "q", "queue": "q", "are": "r", "ar": "r",
                "ess": "s", "tee": "t", "you": "u", "vee": "v", "ex": "x", "why": "y", "zee": "z", "zed": "z"}
EDGE_PUNCT = ".,;:!?\"'()[]।"
COMMON_WORDS = {"a", "an", "the", "and", "or", "of", "on", "in", "at", "to", "is", "are", "was", "has", "had", "have", "then",
                "use", "used", "with", "for", "from", "this", "that", "it", "check", "near", "not", "no"}
MAX_WINDOW = 6
FUZZY_CUTOFF = 0.84


class DictionaryEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    spoken_variants: list[str] = Field(default_factory=list)
    canonical_term: str = Field(min_length=1)
    description: str = ""
    add_to_keyterms: bool = True


class Shortcut(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    trigger: str = Field(min_length=1)
    expansion: str = Field(min_length=1)


class Style(BaseModel):
    id: str
    name: str
    persona: str
    instructions: str
    template: str


def spoken_key(phrase: str) -> str:
    """Canonical form: 'cue eff en forty eight', 'q f n 48' and 'QFN-48' all give 'qfn48'."""
    out: list[str] = []
    tokens = re.split(r"[\s\-_/]+", phrase.lower().strip(EDGE_PUNCT))
    i = 0
    while i < len(tokens):
        t = tokens[i].strip(EDGE_PUNCT)
        if t in TENS:
            value = TENS[t]
            if i + 1 < len(tokens) and tokens[i + 1].strip(EDGE_PUNCT) in UNITS and UNITS[tokens[i + 1].strip(EDGE_PUNCT)] > 0:
                value += UNITS[tokens[i + 1].strip(EDGE_PUNCT)]
                i += 1
            out.append(str(value))
        elif t in TEENS:
            out.append(str(TEENS[t]))
        elif t in UNITS:
            out.append(str(UNITS[t]))
        elif t in LETTER_NAMES:
            out.append(LETTER_NAMES[t])
        else:
            out.append(t)
        i += 1
    return "".join(out)


def phonetic_key(key: str) -> str:
    """Collapse sounds Indian English speech-to-text often swaps, keeping consonant shape."""
    key = re.sub(r"(ph)", "f", key)
    key = re.sub(r"(cks|ck|x|q)", "k", key)
    key = re.sub(r"(th)", "t", key)
    key = re.sub(r"(z)", "s", key)
    key = re.sub(r"(v|w)", "b", key)
    key = re.sub(r"(.)\1+", r"\1", key)
    return key[0] + re.sub(r"[aeiou]", "", key[1:]) if key else key


def _digits(key: str) -> str:
    return "".join(c for c in key if c.isdigit())


@dataclass
class Replacement:
    heard: str
    wrote: str
    match: str  # "exact" or "fuzzy"


class KiviSpace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def _path(self, name: str) -> Path:
        return self.root / f"{name}.json"

    def _read(self, name: str) -> list[dict]:
        path = self._path(name)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def _write(self, name: str, rows: list[dict]) -> None:
        temp = self._path(name).with_suffix(".tmp")
        temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self._path(name))

    def dictionary(self) -> list[DictionaryEntry]:
        return [DictionaryEntry.model_validate(r) for r in self._read("dictionary")]

    def shortcuts(self) -> list[Shortcut]:
        return [Shortcut.model_validate(r) for r in self._read("shortcuts")]

    def styles(self) -> list[Style]:
        return [Style.model_validate(r) for r in self._read("styles")]

    def upsert(self, name: str, item: BaseModel) -> None:
        with self._lock:
            rows = [r for r in self._read(name) if r["id"] != item.id]  # type: ignore[attr-defined]
            self._write(name, rows + [item.model_dump()])

    def delete(self, name: str, item_id: str) -> bool:
        with self._lock:
            rows = self._read(name)
            kept = [r for r in rows if r["id"] != item_id]
            self._write(name, kept)
            return len(kept) != len(rows)

    def keyterms(self) -> list[str]:
        terms = [e.canonical_term.split(" (")[0] for e in self.dictionary() if e.add_to_keyterms]
        return list(dict.fromkeys(t for t in terms if len(t) <= MAX_KEYTERM_CHARS))[:MAX_KEYTERMS]


def apply_dictionary(text: str, entries: list[DictionaryEntry]) -> tuple[str, list[Replacement]]:
    exact: dict[str, str] = {}
    for entry in entries:
        for phrase in [entry.canonical_term.split(" (")[0], *entry.spoken_variants]:
            exact[spoken_key(phrase)] = entry.canonical_term
    fuzzy = {phonetic_key(k): (k, v) for k, v in exact.items() if len(k) >= 5}

    tokens = text.split()
    out: list[str] = []
    done: list[Replacement] = []
    i = 0
    while i < len(tokens):
        for size in range(min(MAX_WINDOW, len(tokens) - i), 0, -1):
            window = " ".join(tokens[i:i + size])
            key = spoken_key(window)
            term, how = exact.get(key), "exact"
            edges = (tokens[i].strip(EDGE_PUNCT).lower(), tokens[i + size - 1].strip(EDGE_PUNCT).lower())
            if term is None and len(key) >= 6 and not set(edges) & COMMON_WORDS:
                near = difflib.get_close_matches(phonetic_key(key), list(fuzzy), n=1, cutoff=FUZZY_CUTOFF)
                # Equal length too, so that a match cannot swallow neighbouring words.
                if near and _digits(fuzzy[near[0]][0]) == _digits(key) and abs(len(fuzzy[near[0]][0]) - len(key)) <= 2:
                    term, how = fuzzy[near[0]][1], "fuzzy"
            if term:
                tail = window[len(window.rstrip(EDGE_PUNCT)):]
                out.append(term + tail)
                if window.rstrip(EDGE_PUNCT) != term:
                    done.append(Replacement(window, term, how))
                i += size
                break
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out), done


def expand_shortcuts(text: str, shortcuts: list[Shortcut], entries: list[DictionaryEntry]) -> tuple[str, list[str]]:
    used = []
    for shortcut in sorted(shortcuts, key=lambda s: -len(s.trigger)):
        trigger, _ = apply_dictionary(shortcut.trigger, entries)
        pattern = r"(?<!\w)" + r"[\s,]+".join(re.escape(w) for w in trigger.split()) + r"(?!\w)[.!?]?"
        text, count = re.subn(pattern, lambda _: shortcut.expansion, text, flags=re.IGNORECASE)
        if count:
            used.append(shortcut.id)
    return text, used


async def apply_style(text: str, style: Style, sarvam: SarvamService, context: dict | None = None) -> tuple[str, bool]:
    """Return (text, used_llm). The template is the offline path and the failure fallback."""
    context = context or {}
    fallback = style.template.format(text=text, serial=context.get("serial") or "UNASSIGNED")
    schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"], "additionalProperties": False}
    system = (f"You format speech from a {style.persona} in an EMS factory. {style.instructions} "
              "Keep every designator, number, temperature and standard exactly as given. Do not add facts.")
    try:
        reply = await sarvam.chat_json(system, json.dumps({"speech": text, **context}, ensure_ascii=False), schema, "styled_text")
        return reply["text"], True
    except (SarvamError, KeyError):
        return fallback, False
