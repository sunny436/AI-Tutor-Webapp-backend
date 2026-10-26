"""The first words of a voice reply, spoken by the server as soon as they are written (VOICE_SERVER_SPEECH).

The web app reads a reply aloud chunk by chunk (features/voice/speech-text.ts), each chunk a request of its own
once its words have reached the browser. The first is the one the student waits for, so the server makes it
from the tokens as they arrive and sends the audio with the reply, a round trip sooner. Only where that is safe
without the web app's Markdown reader: the reply's first line, plain prose (letters, digits, ordinary
punctuation), up to its first pause. Citation markers ([1], [F2]) are left out, as the web app leaves them out.
Anything else (maths, code, a table, a list, a heading, a link, a card, Hindi, a symbol it would read in words)
is left to the web app, as before.

The same rule as the web app's first chunk: at a comma, semicolon, colon or dash at least FIRST_COMMA characters
in, with at least MIN_CHUNK characters of the sentence after it; else at the end of the first sentence (at least
MIN_CHUNK long, never at an abbreviation, an initial or a decimal). The web app then reads on from that point.
"""

from __future__ import annotations

import re

FIRST_COMMA = 24  # speech-text.ts FIRST_COMMA
MIN_CHUNK = 25  # speech-text.ts MIN_CHUNK
MAX_CHUNK = 220  # speech-text.ts MAX_CHUNK

CITATION = re.compile(r"\s*\[F?\d{1,3}\]")
PLAIN = re.compile(r"[A-Za-z0-9 ,.;:!?'\"()\-–—‘’“”]*")
CLAUSE = re.compile(r"[,;:](?= \S)| [–—](?= \S)")
SENTENCE_END = re.compile(r"[.!?](?= \S)")
ABBREVIATION = re.compile(r"(?:\b(?:Mr|Mrs|Ms|Dr|St|vs|etc|No|Fig|approx|e\.g|i\.e)|\b[A-Z]|\d)\.$")


def spoken(raw: str) -> str:
    """What the web app would say for this plain prefix: no citation markers, single spaces."""
    text = re.sub(r"\s+", " ", CITATION.sub("", raw))
    return re.sub(r"\s+([.,!?;:])", r"\1", text).strip()


def first_speakable(text: str) -> tuple[int, str] | None:
    """(characters of the reply covered, words to say) for its first chunk, or None (not yet, or not here).

    `text` is the reply so far. Callers stop asking once `settled(text)` is true without an answer."""
    line_end = text.find("\n")
    line = text if line_end == -1 else text[:line_end]
    if not line or line.lstrip() != line:
        return None
    for mark in CLAUSE.finditer(line):
        at = mark.end()
        if at < FIRST_COMMA:
            continue
        if at > MAX_CHUNK:
            return None
        rest = SENTENCE_END.search(line, at)
        after = (rest.end() if rest is not None else len(line)) - at
        if after < MIN_CHUNK:
            if rest is None and line_end == -1:
                return None  # not enough after it yet to know: ask again with more
            break  # the sentence ends too soon after the pause: keep it whole
        return _safe(text[:at])
    for end in SENTENCE_END.finditer(line):
        at = end.end()
        if at > MAX_CHUNK:
            return None
        if at < MIN_CHUNK or ABBREVIATION.search(line[:at]):
            continue
        return _safe(text[:at])
    return None


def _safe(raw: str) -> tuple[int, str] | None:
    words = spoken(raw)
    if not words or not PLAIN.fullmatch(CITATION.sub("", raw)):
        return None
    return len(raw), words


def settled(text: str) -> bool:
    """Whether the first chunk's place is decided whatever comes next: the first line has ended, has gone past
    MAX_CHUNK, or holds something the web app reads differently."""
    line_end = text.find("\n")
    line = text if line_end == -1 else text[:line_end]
    return line_end != -1 or len(line) > MAX_CHUNK or not PLAIN.fullmatch(CITATION.sub("", line))
