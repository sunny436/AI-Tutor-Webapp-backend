"""The question bank (app/qbank, docs/question_bank.md): files are checked before anything is
written, an import changes only what changed, serving never relaxes a filter, an answer belongs to
a served question and counts once, and a chapter's limit holds under concurrent writes. Every bank
here is synthetic (book() writes one); nothing calls a model."""

import asyncio
import json
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import User
from app.errors import Conflict, NotFound, ValidationFailed
from app.qbank import selection
from app.qbank.importer import import_bank
from app.qbank.validate import AR_OPTIONS, content_hash

VERSION = {
    "code": "cbse-2026-27",
    "curriculum": "cbse",
    "academic_session": "2026_27",
    "title": "CBSE Curriculum for the Academic Year 2026-27",
    "source_url": "https://cbseacademic.nic.in/curriculum_2027.html",
}
FILTERS = {"language": "english", "class_level": 10, "subject_code": "science", "syllabus_version": "cbse-2026-27"}
DEVANAGARI = "कखगघचछजझटठ"
LEVELS = ("easy", "medium", "hard")


def _token(language: str, *parts: int) -> str:
    digits = "".join(f"{part:03d}" for part in parts)
    return "".join(DEVANAGARI[int(d)] for d in digits) if language == "hindi" else f"w{digits}"


def book(language="english", chapters=((1, 1000),), topics=1, per_level=4, concepts=("alpha", "beta")) -> dict:
    """A book with its chapters, topics and per_level approved questions per difficulty per topic.
    Every stem and option is made of tokens no other question shares."""
    code = "EN" if language == "english" else "HI"
    book_id = f"science-c10-{code.lower()}"
    manifest = {
        "syllabus_version": VERSION,
        "book": {
            "book_id": book_id,
            "curriculum": "cbse",
            "class_level": 10,
            "subject_code": "science",
            "language": language,
            "title": f"Science {code}",
            "edition": "test",
        },
        "chapters": [],
    }
    questions: dict[str, list[dict]] = {}
    for number, limit in chapters:
        chapter_id = f"C10-SCI-{code}-CH{number:02d}"
        chapter = {
            "chapter_id": chapter_id,
            "chapter_number": number,
            "title": f"Chapter {number}",
            "max_questions": limit,
            "topics": [],
        }
        for t in range(1, topics + 1):
            topic_id = f"{chapter_id}-T{t}"
            chapter["topics"].append(
                {
                    "topic_id": topic_id,
                    "topic_number": t,
                    "title": f"Topic {t}",
                    "concepts": [{"concept_tag": tag, "learning_objective": f"Objective {tag}"} for tag in concepts],
                }
            )
            for level, difficulty in enumerate(LEVELS):
                for k in range(per_level):
                    n = level * per_level + k + 1
                    words = [_token(language, number, t, n, i) for i in range(6)]
                    record = {
                        "question_id": f"{topic_id}-{n:03d}",
                        "chapter_id": chapter_id,
                        "topic_id": topic_id,
                        "concept_tag": concepts[k % len(concepts)],
                        "difficulty": difficulty,
                        "format": "mcq",
                        "competency": "application",
                        "case_id": None,
                        "stem": " ".join(words),
                        "options": [_token(language, number, t, n, 10 + i) for i in range(4)],
                        "answer": "ABCD"[n % 4],
                        "explanation": " ".join(words[:3]),
                        "marks": 1,
                        "source": {"kind": "original", "ref": "synthetic", "url": None},
                    }
                    questions.setdefault(chapter_id, []).append(approve(record, language))
        manifest["chapters"].append(chapter)
    return {"manifest": manifest, "questions": questions}


def approve(record: dict, language: str) -> dict:
    hashed = content_hash(record, language=language, syllabus_version=VERSION["code"], case=None)
    return {
        **record,
        "review": {"status": "approved", "by": "Test Reviewer", "at": "2026-10-15T10:00:00+00:00", "hash": hashed},
    }


def save(root: Path, *books: dict) -> Path:
    for written in books:
        book_id = written["manifest"]["book"]["book_id"]
        manifest = root / "manifest" / VERSION["code"] / f"{book_id}.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps(written["manifest"]), encoding="utf-8")
        for chapter_id, records in written["questions"].items():
            folder = root / "content" / book_id / chapter_id
            folder.mkdir(parents=True, exist_ok=True)
            lines = [json.dumps(record, ensure_ascii=False) for record in records]
            (folder / "questions.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


@pytest.fixture
async def sessions(database):
    engine = create_async_engine(database)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def load(sessions, root: Path, **options):
    async with sessions() as db:
        return await import_bank(db, root, apply=True, **options)


async def scalar(sessions, sql: str, **params):
    async with sessions() as db:
        return await db.scalar(text(sql), params)


async def new_user(sessions) -> uuid.UUID:
    async with sessions() as db:
        user = User(email=f"qb-{uuid.uuid4().hex[:10]}@example.com", email_verified=True)
        db.add(user)
        await db.commit()
        return user.id


async def served(sessions, set_id, position) -> dict:
    """The key, concept and level of a served question (what a test may look up; a client never can)."""
    async with sessions() as db:
        row = await db.execute(
            text(
                "SELECT q.correct_option, q.concept_tag, q.level FROM qb_set_items i "
                "JOIN qb_questions q ON q.question_id = i.question_id WHERE i.set_id = :s AND i.position = :p"
            ),
            {"s": set_id, "p": position},
        )
        return dict(row.mappings().one())


def wrong(option: str) -> str:
    return "ABCD"[("ABCD".index(option) + 1) % 4]


async def call(sessions, function, *args, **kwargs):
    async with sessions() as db:
        return await function(db, *args, **kwargs)


# ------------------------------------------------------------------ import
async def test_an_import_checks_first_writes_once_and_an_edit_goes_back_to_review(sessions, tmp_path):
    bank = book()
    save(tmp_path, bank)
    async with sessions() as db:
        dry = await import_bank(db, tmp_path, apply=False)
    assert dry.errors == [] and not dry.applied and dry.counts["qb_questions"]["inserted"] == 12
    assert await scalar(sessions, "SELECT count(*) FROM qb_questions") == 0  # a dry run writes nothing

    first = await load(sessions, tmp_path)
    assert first.applied and first.counts["qb_questions"] == {"inserted": 12, "updated": 0, "unchanged": 0}
    assert await scalar(sessions, "SELECT question_count FROM qb_chapters") == 12
    again = await load(sessions, tmp_path)
    assert again.counts["qb_questions"] == {"inserted": 0, "updated": 0, "unchanged": 12}

    edited = bank["questions"]["C10-SCI-EN-CH01"][0]
    edited["explanation"] = "w999 corrected"  # the approval was for the old text
    save(tmp_path, bank)
    refused = await load(sessions, tmp_path)
    assert not refused.applied and any("approved needs" in error for error in refused.errors)
    edited["review"] = {"status": "needs_review", "note": "edited"}
    save(tmp_path, bank)
    report = await load(sessions, tmp_path)
    assert report.counts["qb_questions"] == {"inserted": 0, "updated": 1, "unchanged": 11}
    status = await scalar(
        sessions, "SELECT review_status FROM qb_questions WHERE question_id = :q", q=edited["question_id"]
    )
    assert status == "needs_review"

    del bank["questions"]["C10-SCI-EN-CH01"][1]
    save(tmp_path, bank)
    retired = await load(sessions, tmp_path, retire_missing=True)
    assert retired.missing == ["C10-SCI-EN-CH01-T1-002"] and retired.retired == 1
    assert await scalar(sessions, "SELECT count(*) FROM qb_questions") == 12  # retired, never deleted


async def test_wrong_files_are_refused_whole(sessions, tmp_path):
    english, hindi = book(per_level=2), book("hindi", per_level=2)
    records = english["questions"]["C10-SCI-EN-CH01"]
    records[1] = approve({**records[1], "stem": records[0]["stem"], "options": records[0]["options"][::-1]}, "english")
    records[2] = approve(
        {**records[2], "explanation": "Correct option: (A). " + records[2]["explanation"], "answer": "B"}, "english"
    )
    records[3] = approve({**records[3], "format": "assertion_reason", "options": list(AR_OPTIONS[::-1])}, "english")
    records[4] = approve({**records[4], "format": "case_based"}, "english")
    hindi_records = hindi["questions"]["C10-SCI-HI-CH01"]
    hindi_records[0] = approve({**hindi_records[0], "stem": "What is the focal length of this lens?"}, "hindi")
    report = await load(sessions, save(tmp_path, english, hindi))
    joined = "\n".join(report.errors)
    assert not report.applied
    for expected in (
        "the same question as",
        "the explanation names option",
        "assertion-reason options",
        "case- and source-based",
        "is not in hindi",
    ):
        assert expected in joined, expected
    assert await scalar(sessions, "SELECT count(*) FROM qb_books") == 0  # all or nothing


async def test_english_and_hindi_books_keep_their_own_chapters_and_questions(sessions, tmp_path):
    report = await load(sessions, save(tmp_path, book(), book("hindi")))
    assert report.applied, report.errors
    numbers = await scalar(sessions, "SELECT count(DISTINCT chapter_id) FROM qb_chapters WHERE chapter_number = 1")
    assert numbers == 2  # the same chapter number in two books
    user = await new_user(sessions)
    created = await call(
        sessions,
        selection.create_test,
        user,
        uuid.uuid4(),
        {**FILTERS, "language": "hindi"},
        {"easy": 2, "medium": 2, "hard": 2},
    )
    languages = await scalar(
        sessions,
        "SELECT string_agg(DISTINCT q.language, ',') FROM qb_set_items i "
        "JOIN qb_questions q ON q.question_id = i.question_id WHERE i.set_id = :s",
        s=created["set_id"],
    )
    assert created["status"] == "created" and languages == "hindi"
    with pytest.raises(DBAPIError):  # a question cannot claim another language than its book's
        async with sessions() as db:
            await db.execute(text("UPDATE qb_questions SET language = 'english' WHERE book_id = 'science-c10-hi'"))


# ------------------------------------------------------------------ selection
async def test_a_test_serves_only_servable_active_questions_and_never_relaxes(sessions, tmp_path):
    bank = book(per_level=6)
    records = bank["questions"]["C10-SCI-EN-CH01"]
    for record in records[6:8]:  # two medium questions a reviewer rejected
        record["review"] = {"status": "rejected", "note": "wrong key"}
    records[8] = {**records[8], "active": False}  # one medium question retired
    assert (await load(sessions, save(tmp_path, bank))).applied
    user = await new_user(sessions)

    created = await call(sessions, selection.create_test, user, uuid.uuid4(), FILTERS, {"medium": 3, "easy": 1})
    assert created["status"] == "created" and created["served"] == 4
    servable = await scalar(
        sessions,
        "SELECT bool_and(q.review_status IN ('approved', 'needs_review') AND q.is_active) FROM qb_set_items i "
        "JOIN qb_questions q ON q.question_id = i.question_id WHERE i.set_id = :s",
        s=created["set_id"],
    )
    assert servable

    sets_before = await scalar(sessions, "SELECT count(*) FROM qb_sets")
    short = await call(sessions, selection.create_test, user, uuid.uuid4(), FILTERS, {"medium": 4})
    assert short == {"status": "shortage", "buckets": {"medium": {"requested": 4, "available": 3}}}
    assert await scalar(sessions, "SELECT count(*) FROM qb_sets") == sets_before  # nothing created
    partial = await call(
        sessions, selection.create_test, user, uuid.uuid4(), FILTERS, {"medium": 4}, allow_partial=True
    )
    assert partial["status"] == "partial" and partial["served"] == 3

    with pytest.raises(ValidationFailed):  # a chapter outside the requested subject is an error, not "anything"
        await call(
            sessions,
            selection.create_test,
            user,
            uuid.uuid4(),
            {**FILTERS, "subject_code": "mathematics", "chapter_id": "C10-SCI-EN-CH01"},
            {"easy": 1},
        )
    other_language = await call(
        sessions, selection.create_test, user, uuid.uuid4(), {**FILTERS, "language": "hindi"}, {"easy": 1}
    )
    assert other_language["status"] == "shortage"  # nothing substituted from the English book

    request = uuid.uuid4()
    first = await call(sessions, selection.create_test, user, request, FILTERS, {"easy": 2})
    replay = await call(sessions, selection.create_test, user, request, FILTERS, {"easy": 2})
    assert replay["set_id"] == first["set_id"] and replay["replayed"]
    with pytest.raises(Conflict):
        await call(sessions, selection.create_test, user, request, FILTERS, {"easy": 3})


async def test_unseen_questions_come_first_and_unseen_only_excludes_the_rest(sessions, tmp_path):
    assert (await load(sessions, save(tmp_path, book()))).applied
    user = await new_user(sessions)
    first = await call(sessions, selection.create_test, user, uuid.uuid4(), FILTERS, {"easy": 2})
    second = await call(sessions, selection.create_test, user, uuid.uuid4(), FILTERS, {"easy": 2})
    overlap = await scalar(
        sessions,
        "SELECT count(*) FROM qb_set_items a JOIN qb_set_items b USING (question_id) "
        "WHERE a.set_id = :a AND b.set_id = :b",
        a=first["set_id"],
        b=second["set_id"],
    )
    assert overlap == 0
    exhausted = await call(
        sessions, selection.create_test, user, uuid.uuid4(), {**FILTERS, "unseen_only": True}, {"easy": 1}
    )
    assert exhausted["status"] == "shortage"
    async with sessions() as db:
        listed = await selection.items(db, user, first["set_id"])
    assert len(listed) == 2 and all("correct_option" not in item and "explanation" not in item for item in listed)


async def test_adaptive_practice_follows_the_previous_answer(sessions, tmp_path):
    assert (await load(sessions, save(tmp_path, book()))).applied
    user = await new_user(sessions)
    created = await call(
        sessions, selection.create_adaptive, user, uuid.uuid4(), {**FILTERS, "topic_id": "C10-SCI-EN-CH01-T1"}, 8
    )
    set_id = created["set_id"]

    async def step():
        reply = await call(sessions, selection.next_item, user, set_id)
        assert reply["status"] == "served", reply
        position = reply["item"]["position"]
        return position, await served(sessions, set_id, position)

    position, first = await step()
    assert first["level"] == 2  # no history: medium
    again = await call(sessions, selection.next_item, user, set_id)
    assert again == {"status": "open", "item": again["item"]} and again["item"]["position"] == position

    await call(sessions, selection.answer, user, set_id, position, wrong(first["correct_option"]))
    position, second = await step()
    assert (second["level"], second["concept_tag"]) == (1, first["concept_tag"])  # wrong: easier, same concept

    await call(sessions, selection.answer, user, set_id, position, second["correct_option"], hinted=True)
    position, third = await step()
    assert (third["level"], third["concept_tag"]) == (1, second["concept_tag"])  # hinted: same level and concept

    await call(sessions, selection.answer, user, set_id, position, third["correct_option"])
    position, fourth = await step()
    assert fourth["level"] == 2 and fourth["concept_tag"] != third["concept_tag"]  # right: harder, other concept

    await call(sessions, selection.answer, user, set_id, position, fourth["correct_option"])
    _, fifth = await step()
    assert fifth["level"] == 3 and fifth["concept_tag"] != fourth["concept_tag"]


# ------------------------------------------------------------------ answers
async def test_an_answer_belongs_to_a_served_question_and_counts_once(sessions, tmp_path):
    assert (await load(sessions, save(tmp_path, book()))).applied
    user, stranger = await new_user(sessions), await new_user(sessions)
    test = await call(sessions, selection.create_test, user, uuid.uuid4(), FILTERS, {"easy": 2})
    set_id = test["set_id"]
    key = (await served(sessions, set_id, 1))["correct_option"]

    with pytest.raises(NotFound):  # someone else's set
        await call(sessions, selection.answer, stranger, set_id, 1, key)
    with pytest.raises(NotFound):  # a position never served
        await call(sessions, selection.answer, user, set_id, 9, key)
    first = await call(sessions, selection.answer, user, set_id, 1, key)
    assert first == {"set_id": set_id, "position": 1, "replayed": False}  # a test reveals nothing yet
    assert (await call(sessions, selection.answer, user, set_id, 1, key))["replayed"]
    with pytest.raises(Conflict):
        await call(sessions, selection.answer, user, set_id, 1, wrong(key))
    with pytest.raises(Conflict):
        await call(sessions, selection.results, user, set_id)  # not finished
    await call(sessions, selection.close_set, user, set_id)
    await call(sessions, selection.close_set, user, set_id)  # closing again changes nothing
    with pytest.raises(Conflict):
        await call(sessions, selection.answer, user, set_id, 2, key)  # closed
    outcome = await call(sessions, selection.results, user, set_id)
    assert (outcome["answered"], outcome["correct"]) == (1, 1) and outcome["items"][0]["correct_option"] == key

    for sql in (  # the database itself: answers are graded there and final
        "UPDATE qb_set_items SET is_correct = false WHERE set_id = :s AND position = 1",
        "UPDATE qb_set_items SET chosen = 'A' WHERE set_id = :s AND position = 1",
        "INSERT INTO qb_set_items (set_id, position, user_id, question_id, topic_id, chosen) "
        "SELECT set_id, 7, user_id, question_id, topic_id, 'A' FROM qb_set_items WHERE set_id = :s AND position = 2",
    ):
        with pytest.raises(DBAPIError):
            async with sessions() as db:
                await db.execute(text(sql), {"s": set_id})


async def test_concurrent_requests_record_one_answer_and_serve_one_question(sessions, tmp_path):
    assert (await load(sessions, save(tmp_path, book()))).applied
    user = await new_user(sessions)
    test = await call(sessions, selection.create_test, user, uuid.uuid4(), FILTERS, {"easy": 1})
    key = (await served(sessions, test["set_id"], 1))["correct_option"]
    both = await asyncio.gather(*(call(sessions, selection.answer, user, test["set_id"], 1, key) for _ in range(2)))
    assert sorted(reply["replayed"] for reply in both) == [False, True]

    adaptive = await call(
        sessions, selection.create_adaptive, user, uuid.uuid4(), {**FILTERS, "topic_id": "C10-SCI-EN-CH01-T1"}, 5
    )
    nexts = await asyncio.gather(*(call(sessions, selection.next_item, user, adaptive["set_id"]) for _ in range(2)))
    assert sorted(reply["status"] for reply in nexts) == ["open", "served"]
    assert nexts[0]["item"]["question_id"] == nexts[1]["item"]["question_id"]
    assert await scalar(sessions, "SELECT served FROM qb_sets WHERE id = :s", s=adaptive["set_id"]) == 1


# ------------------------------------------------------------------ the chapter limit
COPY = text(
    """
    INSERT INTO qb_questions (question_id, book_id, class_level, subject_code, language, chapter_id, topic_id,
        concept_tag, syllabus_version, difficulty, question_format, competency, stem, option_a, option_b, option_c,
        option_d, correct_option, explanation, source_kind, source_ref, fingerprint, content_hash)
    SELECT CAST(:new AS text), book_id, class_level, subject_code, language, chapter_id, topic_id, concept_tag,
        syllabus_version, difficulty, question_format, competency, CAST(:new AS text) || stem, option_a, option_b,
        option_c, option_d, correct_option, explanation, source_kind, source_ref,
        md5(CAST(:new AS text)) || md5(CAST(:new AS text) || 'f'),
        md5(CAST(:new AS text)) || md5(CAST(:new AS text) || 'c')
    FROM qb_questions WHERE question_id = 'C10-SCI-EN-CH01-T1-001'
    """
)


async def test_the_chapter_limit_holds_for_inserts_moves_and_lowered_limits(sessions, tmp_path):
    bank = book(chapters=((1, 3), (2, 1000)), per_level=1)
    assert (await load(sessions, save(tmp_path, bank))).applied
    async with sessions() as db:
        report = await import_bank(db, tmp_path, apply=True)
    assert report.counts["qb_questions"]["unchanged"] == 6

    bank["questions"]["C10-SCI-EN-CH01"].append(
        approve(
            {
                **bank["questions"]["C10-SCI-EN-CH01"][0],
                "question_id": "C10-SCI-EN-CH01-T1-099",
                "stem": "w9 extra question",
            },
            "english",
        )
    )
    over = await load(sessions, save(tmp_path, bank))
    assert not over.applied and any("over its limit" in error for error in over.errors)

    for sql in (
        "UPDATE qb_questions SET chapter_id = 'C10-SCI-EN-CH01', topic_id = 'C10-SCI-EN-CH01-T1' "
        "WHERE question_id = 'C10-SCI-EN-CH02-T1-001'",  # a move into a full chapter
        "UPDATE qb_chapters SET max_questions = 2 WHERE chapter_id = 'C10-SCI-EN-CH01'",  # below what it holds
        "UPDATE qb_chapters SET question_count = 0",  # the counter is the database's
        "INSERT INTO qb_chapters (chapter_id, book_id, chapter_number, title, question_count) "
        "VALUES ('C10-SCI-EN-CH03', 'science-c10-en', 3, 'Three', 5)",
    ):
        with pytest.raises(DBAPIError):
            async with sessions() as db:
                await db.execute(text(sql))
    with pytest.raises(DBAPIError):
        async with sessions() as db:
            await db.execute(COPY, {"new": "C10-SCI-EN-CH01-T1-050"})
    async with sessions() as db:
        assert (await selection.coverage(db))["counter_drift"] == []
    assert await scalar(sessions, "SELECT question_count FROM qb_chapters WHERE chapter_id = 'C10-SCI-EN-CH01'") == 3


async def test_the_chapter_limit_holds_under_concurrent_inserts(sessions, tmp_path, database):
    bank = book(chapters=((1, 4),), per_level=1)  # 3 questions, room for one more
    assert (await load(sessions, save(tmp_path, bank))).applied
    engine = create_async_engine(database)
    try:
        async with engine.connect() as first, engine.connect() as second:
            await first.begin()
            await first.execute(COPY, {"new": "C10-SCI-EN-CH01-T1-051"})  # holds the chapter row
            await second.begin()
            racing = asyncio.create_task(second.execute(COPY, {"new": "C10-SCI-EN-CH01-T1-052"}))
            await asyncio.sleep(0.5)
            assert not racing.done()  # waiting for the first writer, not counting on its own
            await first.commit()
            with pytest.raises(DBAPIError):
                await racing
            await second.rollback()
    finally:
        await engine.dispose()
    assert await scalar(sessions, "SELECT question_count FROM qb_chapters") == 4
    assert await scalar(sessions, "SELECT count(*) FROM qb_questions") == 4


# ------------------------------------------------------------------ speed
async def test_choosing_and_answering_are_fast_on_a_full_chapter(sessions, tmp_path):
    report = await load(sessions, save(tmp_path, book(topics=10, per_level=33)))  # 990 questions
    assert report.applied and report.counts["qb_questions"]["inserted"] == 990
    user = await new_user(sessions)
    created = await call(
        sessions, selection.create_adaptive, user, uuid.uuid4(), {**FILTERS, "topic_id": "C10-SCI-EN-CH01-T5"}, 20
    )
    set_id, timings = created["set_id"], []
    for _ in range(10):
        started = time.perf_counter()
        reply = await call(sessions, selection.next_item, user, set_id)
        await call(sessions, selection.answer, user, set_id, reply["item"]["position"], "A")
        timings.append(time.perf_counter() - started)
    params = {"user_id": user, "set_id": set_id, "seed": str(set_id), "topic_ids": ["C10-SCI-EN-CH01-T5"], **FILTERS}
    params |= {"previous_position": None, "difficulty": None, "card": False}  # next_item's pick (pick_next)
    async with sessions() as db:  # TIMING OFF: per-row clock reads would dominate on a slow virtual clock
        plan = await db.scalar(
            text("EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) " + selection.ADAPTIVE_PICK.text), params
        )
    plan = json.loads(plan) if isinstance(plan, str) else plan
    # Index scans and hash joins over one topic. A wrong plan (nested loops without statistics) took
    # 159 ms on the test machine, where this one takes about 10 ms and a plain scan of the topic 1.6 ms.
    assert plan[0]["Execution Time"] < 25
    assert sorted(timings)[len(timings) // 2] < 0.25  # next + answer, round trips included
