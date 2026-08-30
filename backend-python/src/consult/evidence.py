"""
consult/evidence.py
--------------------
Section-level evidence evaluation — the stage between retrieval and the
context builder.

WHY THIS EXISTS
`consult/graph.py::knowledge_for_prompt` used to answer one question for the
WHOLE plan: "was anything grounded?" But retrieval is already partial per
note — `retrieval/knowledge.py` caps at `config.VECTOR_TOP_K` (4) chunks,
while an average note in `data/knowledge/` is ~7 chunks (204 chunks / 29
notes). So a "complete" plan, needing all six sections, routinely has real
evidence for SOME sections and none for others even when the note is
correctly matched — the old whole-plan check couldn't see that, and its
fallback ("say plainly your reference notes don't cover this") leaked
retrieval internals into a user-facing wellness answer regardless of which
part actually lacked evidence.

This module answers the question per section instead, so the prompt can
tell the model exactly which sections it may write from real evidence and
which it must keep general — without the model ever needing to explain why.

EVIDENCE HIERARCHY
    priority 1  curated internal knowledge base (`knowledge:` chunks)
    priority 2  GraphRAG passages that already cleared the coverage gate
                (`graphrag:<filename>` chunks — NOT `graphrag:graph`, the
                relationship-edge chunk, which is extracted structure, not
                prose that maps to a section)
    priority 3  no approved fallback SOURCE exists in this codebase, so none
                is introduced here. It is a WRITING constraint instead,
                applied in the prompt: general, safe, well-known wellness
                guidance only, never a specific claim.

`report:` (uploaded documents) and `memory:` (earlier consultations) chunks
are deliberately excluded. They are personal-fact context, not Ayurveda
content — a lab report is not evidence that a specific Ayurveda claim is
sourced. They keep reaching the prompt exactly as before (SYSTEM_RULES
rules 11/12), independent of section evidence.

DETERMINISTIC, NOT AN LLM CALL. Every note in data/knowledge/*.md uses the
exact same six `## Heading` strings as sections.SECTION_LIBRARY's bold
headings (verified against data/knowledge/acidity.md), so a heading match is
an exact substring check against text drawn from the same markdown source —
cheap, instant, and testable without a live model. Same "deterministic
where the signal is reliable" pattern as knowledge.py::match_topics and
router.py::has_health_signal.
"""

from __future__ import annotations

import re

from src.retrieval.base import Chunk, RetrievalResult

# Section key -> the exact "## Heading" string used in data/knowledge/*.md.
# Deliberately the same wording as sections.SECTION_LIBRARY's bold headings,
# minus the markdown difference (## in the source notes, ** in the prompt
# contract) — both come from the same six-section product decision.
SECTION_MARKERS: dict[str, str] = {
    "root_cause": "## Root Cause",
    "changes": "## Changes To Make",
    "yoga": "## Yoga & Breathing",
    "food": "## Food Chart",
    "routine": "## Daily Routine",
    "doctor": "## When To See A Doctor",
}

# Fallback signal for when a chunk boundary splits a heading from its body
# (ingestion chunks at 800 chars with 100 overlap, so this does happen).
# Small and bilingual, same style as router.py::_HEALTH_SIGNALS.
SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "root_cause": ("root cause", "karan", "kaaran", "kaarann", "wajah", "vajah", "cause"),
    "changes": ("changes to make", "avoid:", "do:", "badlav", "parhez"),
    "yoga": ("yoga", "asana", "pranayama", "breathing", "saans", "shwas", "योग"),
    "food": ("food chart", "eat:", "khayein", "khana", "khaana", "diet", "aahar", "आहार"),
    "routine": ("daily routine", "dincharya", "din charya", "subah", "morning", "raat ko", "दिनचर्या"),
    "doctor": ("see a doctor", "doctor", "emergency", "hospital", "chikitsak", "डॉक्टर"),
}


def chunk_supports_section(chunk: Chunk, section_key: str) -> bool:
    """Does this one chunk provide evidence for this one section?

    Only `knowledge:` and `graphrag:<filename>` chunks are ever considered —
    `graphrag:graph` (relationship edges), `report:` and `memory:` chunks
    never count, whatever their text says. See the module docstring for why.
    """
    if not (chunk.source.startswith("knowledge:") or chunk.source.startswith("graphrag:")):
        return False
    if chunk.source == "graphrag:graph":
        return False

    text = chunk.text or ""
    marker = SECTION_MARKERS.get(section_key)
    if marker and marker in text:
        return True

    lowered = text.lower()
    return any(keyword in lowered for keyword in SECTION_KEYWORDS.get(section_key, ()))


def evaluate_sections(
    sections: list[str], results: list[RetrievalResult]
) -> dict[str, bool]:
    """Which of the requested sections have real (priority 1 or 2) evidence.

    Reads the SAME retrieval results `_retrieve()` already produced — no new
    retrieval call, no added latency. Returns a plain bool per section: the
    prompt only needs "supported" vs "not supported", not which priority
    tier carried it.
    """
    chunks: list[Chunk] = [
        chunk for result in results for chunk in result.chunks
    ]
    return {
        section: any(chunk_supports_section(chunk, section) for chunk in chunks)
        for section in sections
    }


# ---------------------------------------------------------------------------
# Leak backstop. Same "report, never silently rewrite" pattern as
# responder.py::_warn_if_medicine / safety.py::names_medicine — a regex
# quietly deleting part of a health answer is a worse failure than the one
# it would be preventing, so this only ever informs a log line.
# ---------------------------------------------------------------------------
LEAKED_TERMS: tuple[str, ...] = (
    "reference notes",
    "trusted notes",
    "my notes",
    "knowledge base",
    "graphrag",
    "retrieval",
    "no_knowledge",
    "source chunk",
    "not covered",
    "not in my notes",
    "internal score",
    "missing internal document",
    "vector store",
    "vector database",
)

_LEAK_PATTERN = re.compile(
    "|".join(re.escape(term) for term in LEAKED_TERMS), re.IGNORECASE
)


def find_leaked_terms(text: str) -> list[str]:
    """Which forbidden internal-system terms appear in this text, if any."""
    return [match.group(0) for match in _LEAK_PATTERN.finditer(text or "")]
