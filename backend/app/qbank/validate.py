"""Reading and checking the bank's text files (qbank/: manifests and JSONL content) before import.

No database and no model. What is wrong is reported with where it is, never guessed or repaired:
an error stops the whole import (importer.py). Checks that need a subject expert's judgment
(is the key right? is it in the syllabus?) are not claimed here; they are the reviewer's, recorded
as review.status "approved" with the hash of exactly what was approved.

Layout (qbank/README.md):
    manifest/<syllabus version>/<book_id>.json      the syllabus version, one book, its chapters,
                                                    topics and concepts
    content/<book_id>/<chapter_id>/cases.jsonl      shared passages
    content/<book_id>/<chapter_id>/questions.jsonl  one question per line
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.db.models import (
    QB_COMPETENCIES,
    QB_DIFFICULTIES,
    QB_FORMATS,
    QB_LANGUAGES,
    QB_REVIEW_STATUSES,
    QB_SOURCE_KINDS,
)
from app.learning.context import subject_name

LETTERS = "ABCD"
TARGET_PER_TOPIC = 5  # approved questions a topic needs (owner, 2026-10-15); fewer: underfilled
NEAR_DUPLICATE = 0.8  # token-set Jaccard of two stems in one topic: sent to review, not refused
CASE_FORMATS = ("case_based", "source_based")
# CBSE's standard assertion-reason options, verbatim (English).
AR_OPTIONS = (
    "Both Assertion (A) and Reason (R) are true and Reason (R) is the correct explanation of Assertion (A).",
    "Both Assertion (A) and Reason (R) are true, but Reason (R) is not the correct explanation of Assertion (A).",
    "Assertion (A) is true, but Reason (R) is false.",
    "Assertion (A) is false, but Reason (R) is true.",
)
QUESTION_FIELDS = (
    "question_id",
    "chapter_id",
    "topic_id",
    "concept_tag",
    "difficulty",
    "format",
    "competency",
    "case_id",
    "stem",
    "options",
    "answer",
    "explanation",
    "marks",
    "source",
)
_ID = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SESSION = re.compile(r"^\d{4}_\d{2}$")
_KEY_IN_EXPLANATION = re.compile(r"(?:Correct option|सही विकल्प|उचितः विकल्पः)\s*:\s*\(([A-D])\)")
_WORD = re.compile(r"\w+")


def normalise(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _sha256(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint(language: str, stem: str, options: list[str]) -> str:
    """The same question with other spacing, letter case or option order has the same fingerprint."""
    return _sha256([language, normalise(stem), sorted(normalise(option) for option in options)])


def content_hash(question: dict[str, Any], *, language: str, syllabus_version: str, case: dict | None) -> str:
    """Everything a reviewer approves: the question as written, its place, and its case passage."""
    return _sha256(
        {
            "question": {name: question.get(name) for name in QUESTION_FIELDS},
            "language": language,
            "syllabus_version": syllabus_version,
            "case": {"title": case["title"], "body": case["body"]} if case else None,
        }
    )


def language_matches(language: str, texts: list[str]) -> bool:
    """Every field on its own (the stem, each option, the explanation): English text has no Devanagari;
    Hindi and Sanskrit text is mostly Devanagari once it has more than a unit or a symbol's worth of
    Latin letters (an option such as "20 cm" or "+2 D" is fine). Digits and symbols don't count."""
    for text in texts:
        devanagari = sum("ऀ" <= ch <= "ॿ" for ch in text)
        latin = sum(ch.isascii() and ch.isalpha() for ch in text)
        if language == "english" and devanagari:
            return False
        if language != "english" and latin > 8 and devanagari < latin:
            return False
    return True


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(normalise(text)))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def _text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and "\x00" not in value


def _when(value: Any) -> bool:
    try:
        return isinstance(value, str) and datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


@dataclass
class Bank:
    """Everything read from qbank/, checked, and ready to import (rows)."""

    syllabus_versions: dict[str, dict] = field(default_factory=dict)
    books: dict[str, dict] = field(default_factory=dict)
    chapters: dict[str, dict] = field(default_factory=dict)
    topics: dict[str, dict] = field(default_factory=dict)
    concepts: dict[tuple[str, str], dict] = field(default_factory=dict)
    cases: dict[str, dict] = field(default_factory=dict)
    questions: list[dict] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)  # qb_questions rows, once checked
    errors: list[str] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)  # question_id -> why it goes to review


def read_bank(root: Path) -> Bank:
    """Read every manifest and content file under root; parse errors are collected, not raised."""
    bank = Bank()
    for path in sorted(root.glob("manifest/*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            bank.errors.append(f"{path.name}: unreadable JSON ({error})")
            continue
        _read_manifest(bank, data, f"{path.parent.name}/{path.name}")
    for name in ("cases", "questions"):
        for path in sorted(root.glob(f"content/*/*/{name}.jsonl")):
            where = "/".join(path.parts[-3:])
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError as error:
                    bank.errors.append(f"{where}:{number}: unreadable JSON ({error})")
                    continue
                if not isinstance(record, dict):
                    bank.errors.append(f"{where}:{number}: not an object")
                    continue
                record["_where"] = f"{where}:{number}"
                if name == "cases":
                    _read_case(bank, record)
                else:
                    bank.questions.append(record)
    _check_questions(bank)
    return bank


def _read_manifest(bank: Bank, data: Any, where: str) -> None:
    errors = bank.errors
    if not isinstance(data, dict):
        errors.append(f"{where}: not an object")
        return
    version, book = data.get("syllabus_version"), data.get("book")
    if not isinstance(version, dict) or not _SLUG.match(str(version.get("code", ""))):
        errors.append(f"{where}: syllabus_version needs a code")
        return
    if version.get("curriculum") != "cbse" or not _SESSION.match(str(version.get("academic_session", ""))):
        errors.append(f"{where}: syllabus_version needs curriculum 'cbse' and an academic_session like 2026_27")
    if not _text(version.get("title"), 200) or not _text(version.get("source_url"), 500):
        errors.append(f"{where}: syllabus_version needs a title and its source_url")
    known = bank.syllabus_versions.setdefault(version["code"], version)
    if known != version:
        errors.append(f"{where}: syllabus version {version['code']} differs from another manifest's")
    if not isinstance(book, dict) or not _SLUG.match(str(book.get("book_id", ""))):
        errors.append(f"{where}: book needs a book_id like science-c10-en")
        return
    book_id = book["book_id"]
    if book_id in bank.books:
        errors.append(f"{where}: book {book_id} is in two manifests")
        return
    if book.get("curriculum") != "cbse" or book.get("class_level") not in range(6, 13):
        errors.append(f"{where}: book {book_id} needs curriculum 'cbse' and a class_level from 6 to 12")
    if subject_name(book.get("subject_code")) is None:
        errors.append(f"{where}: book {book_id} has subject_code {book.get('subject_code')!r}, not a catalog subject")
    if book.get("language") not in QB_LANGUAGES:
        errors.append(f"{where}: book {book_id} needs a language: {', '.join(QB_LANGUAGES)}")
    if not _text(book.get("title"), 200) or not _text(book.get("edition"), 200):
        errors.append(f"{where}: book {book_id} needs a title and an edition")
    bank.books[book_id] = {**book, "syllabus_version": version["code"]}
    numbers: set[int] = set()
    for chapter in data.get("chapters") or []:
        chapter_id = chapter.get("chapter_id") if isinstance(chapter, dict) else None
        if not isinstance(chapter_id, str) or not _ID.match(chapter_id) or chapter_id in bank.chapters:
            errors.append(f"{where}: a chapter needs a new chapter_id like JESC1-CH09 ({chapter_id!r})")
            continue
        number = chapter.get("chapter_number")
        if not isinstance(number, int) or number < 1 or number in numbers:
            errors.append(f"{where}: chapter {chapter_id} needs its own chapter_number")
        numbers.add(number)
        if not _text(chapter.get("title"), 200):
            errors.append(f"{where}: chapter {chapter_id} needs a title")
        cap = chapter.get("max_questions", 1000)
        if not isinstance(cap, int) or not 1 <= cap <= 1000:
            errors.append(f"{where}: chapter {chapter_id} max_questions must be 1-1000")
        bank.chapters[chapter_id] = {**chapter, "book_id": book_id, "max_questions": cap}
        topic_numbers: set[int] = set()
        for topic in chapter.get("topics") or []:
            topic_id = topic.get("topic_id") if isinstance(topic, dict) else None
            if not isinstance(topic_id, str) or not topic_id.startswith(chapter_id + "-") or topic_id in bank.topics:
                errors.append(f"{where}: a topic of {chapter_id} needs a new topic_id starting {chapter_id}-")
                continue
            if topic.get("topic_number") in topic_numbers or not isinstance(topic.get("topic_number"), int):
                errors.append(f"{where}: topic {topic_id} needs its own topic_number")
            topic_numbers.add(topic.get("topic_number"))
            if not _text(topic.get("title"), 200):
                errors.append(f"{where}: topic {topic_id} needs a title")
            bank.topics[topic_id] = {**topic, "chapter_id": chapter_id}
            for concept in topic.get("concepts") or []:
                tag = concept.get("concept_tag") if isinstance(concept, dict) else None
                if not isinstance(tag, str) or not _SLUG.match(tag) or (topic_id, tag) in bank.concepts:
                    errors.append(f"{where}: a concept of {topic_id} needs a new concept_tag like mirror-formula")
                    continue
                if not _text(concept.get("learning_objective"), 500):
                    errors.append(f"{where}: concept {topic_id}/{tag} needs a learning_objective")
                bank.concepts[(topic_id, tag)] = concept


def _read_case(bank: Bank, case: dict) -> None:
    where, case_id = case["_where"], case.get("case_id")
    if not isinstance(case_id, str) or not _ID.match(case_id) or case_id in bank.cases:
        bank.errors.append(f"{where}: a case needs a new case_id ({case_id!r})")
        return
    if case.get("topic_id") not in bank.topics:
        bank.errors.append(f"{where}: case {case_id} names topic {case.get('topic_id')!r}, not in a manifest")
    if not _text(case.get("title"), 200) or not _text(case.get("body"), 4000) or len(case["body"]) < 100:
        bank.errors.append(f"{where}: case {case_id} needs a title and a body of 100-4000 characters")
    bank.cases[case_id] = case


def _check_questions(bank: Bank) -> None:
    errors = bank.errors
    seen_ids: set[str] = set()
    fingerprints: dict[str, str] = {}
    per_chapter: dict[str, int] = {}
    stems: dict[str, list[tuple[str, set[str]]]] = {}
    for question in bank.questions:
        where, question_id = question["_where"], question.get("question_id")
        if not isinstance(question_id, str) or not _ID.match(question_id) or question_id in seen_ids:
            errors.append(f"{where}: a question needs a new question_id ({question_id!r})")
            continue
        seen_ids.add(question_id)
        prefix = f"{where}: {question_id}"
        unknown = set(question) - {*QUESTION_FIELDS, "review", "active", "_where"}
        if unknown:
            errors.append(f"{prefix}: unknown fields {sorted(unknown)}")
        chapter, topic = bank.chapters.get(question.get("chapter_id")), bank.topics.get(question.get("topic_id"))
        if chapter is None or topic is None or topic["chapter_id"] != question.get("chapter_id"):
            errors.append(f"{prefix}: chapter and topic must be in a manifest, the topic in that chapter")
            continue
        book = bank.books[chapter["book_id"]]
        if (question["topic_id"], question.get("concept_tag")) not in bank.concepts:
            errors.append(f"{prefix}: concept {question.get('concept_tag')!r} is not one of its topic's")
        if question.get("difficulty") not in QB_DIFFICULTIES:
            errors.append(f"{prefix}: difficulty must be one of {', '.join(QB_DIFFICULTIES)}")
        if question.get("format") not in QB_FORMATS:
            errors.append(f"{prefix}: format must be one of {', '.join(QB_FORMATS)}")
        if question.get("competency") not in QB_COMPETENCIES:
            errors.append(f"{prefix}: competency must be one of {', '.join(QB_COMPETENCIES)}")
        case_id, case = question.get("case_id"), bank.cases.get(question.get("case_id") or "")
        if (question.get("format") in CASE_FORMATS) != (case_id is not None):
            errors.append(f"{prefix}: case- and source-based questions, and only they, name a case_id")
        elif case_id is not None and (case is None or case.get("topic_id") != question["topic_id"]):
            errors.append(f"{prefix}: case {case_id!r} is not a case of its topic")
        options, answer, explanation = question.get("options"), question.get("answer"), question.get("explanation")
        if not isinstance(options, list) or len(options) != 4 or not all(_text(o, 500) for o in options):
            errors.append(f"{prefix}: four options (A-D), each 1-500 characters")
            continue
        if len({normalise(o) for o in options}) != 4:
            errors.append(f"{prefix}: two options are the same")
        if answer not in tuple(LETTERS):
            errors.append(f"{prefix}: answer must be one of A, B, C, D")
        if not _text(question.get("stem"), 2000) or not _text(explanation, 3000):
            errors.append(f"{prefix}: a stem (up to 2000 characters) and an explanation (up to 3000)")
            continue
        named = set(_KEY_IN_EXPLANATION.findall(explanation))
        if named and named != {answer}:
            errors.append(f"{prefix}: the explanation names option {sorted(named)}, the key is {answer}")
        if question.get("format") == "assertion_reason" and book["language"] == "english":
            if tuple(options) != AR_OPTIONS:
                errors.append(f"{prefix}: assertion-reason options must be CBSE's four, verbatim")
        marks = question.get("marks", 1)
        if not isinstance(marks, int) or not 1 <= marks <= 5:
            errors.append(f"{prefix}: marks must be 1-5")
        source = question.get("source")
        if (
            not isinstance(source, dict)
            or source.get("kind") not in QB_SOURCE_KINDS
            or not _text(source.get("ref"), 500)
            or (source.get("kind") == "cbse_official" and not _text(source.get("url"), 500))
        ):
            errors.append(f"{prefix}: source needs a kind ({', '.join(QB_SOURCE_KINDS)}), a ref, and a url if official")
            continue
        texts = [question["stem"], *options, explanation]
        if not language_matches(book["language"], texts):
            errors.append(f"{prefix}: its text is not in {book['language']}, the language of {book['book_id']}")
        version = book["syllabus_version"]
        hashed = content_hash(question, language=book["language"], syllabus_version=version, case=case)
        review = question.get("review") or {}
        status = review.get("status", "needs_review")
        if status not in QB_REVIEW_STATUSES:
            errors.append(f"{prefix}: review.status must be one of {', '.join(QB_REVIEW_STATUSES)}")
        if status == "approved" and (
            not _text(review.get("by"), 200) or not _when(review.get("at")) or review.get("hash") != hashed
        ):
            errors.append(f"{prefix}: approved needs review.by, review.at and review.hash of exactly this content")
        active = question.get("active", True)
        if not isinstance(active, bool):
            errors.append(f"{prefix}: active must be true or false")
        printed = fingerprint(book["language"], question["stem"], options)
        if printed in fingerprints:
            errors.append(f"{prefix}: the same question as {fingerprints[printed]}")
        fingerprints[printed] = question_id
        per_chapter[question["chapter_id"]] = per_chapter.get(question["chapter_id"], 0) + 1
        tokens = _tokens(question["stem"])
        for other_id, other in stems.setdefault(question["topic_id"], []):
            if _jaccard(tokens, other) >= NEAR_DUPLICATE:
                bank.notes[question_id] = f"near-duplicate of {other_id}: check before approving"
                break
        stems[question["topic_id"]].append((question_id, tokens))
        if question_id in bank.notes and status not in ("approved", "rejected"):
            status = "needs_review"
        bank.rows.append(
            {
                "question_id": question_id,
                "book_id": book["book_id"],
                "class_level": book["class_level"],
                "subject_code": book["subject_code"],
                "language": book["language"],
                "chapter_id": question["chapter_id"],
                "topic_id": question["topic_id"],
                "concept_tag": question["concept_tag"],
                "syllabus_version": version,
                "difficulty": question["difficulty"],
                "question_format": question["format"],
                "competency": question["competency"],
                "case_id": case_id,
                "stem": question["stem"],
                "option_a": options[0],
                "option_b": options[1],
                "option_c": options[2],
                "option_d": options[3],
                "correct_option": answer,
                "explanation": explanation,
                "marks": marks,
                "source_kind": source["kind"],
                "source_ref": source["ref"],
                "source_url": source.get("url"),
                "review_status": status,
                "reviewed_by": review.get("by") if status == "approved" else None,
                "reviewed_at": datetime.fromisoformat(review["at"]) if status == "approved" else None,
                "reviewed_hash": review.get("hash") if status == "approved" else None,
                "review_note": bank.notes.get(question_id) or review.get("note"),
                "is_active": active,
                "fingerprint": printed,
                "content_hash": hashed,
            }
        )
    for chapter_id, count in per_chapter.items():
        limit = bank.chapters[chapter_id]["max_questions"]
        if count > limit:
            errors.append(f"{chapter_id}: {count} questions, over its limit of {limit}")
