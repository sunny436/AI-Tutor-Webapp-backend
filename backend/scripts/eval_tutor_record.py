"""Does the tutor use what the app records for it? Ask the configured model about practice tests and
exercises, the way students ask, and score its replies.

    python scripts/eval_tutor_record.py [--runs 5] [--min 0.95]

On the server, where the model and its key are (nothing is written anywhere):

    systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env \\
        -p WorkingDirectory=/opt/aichat/app/backend \\
        /opt/aichat/app/backend/.venv/bin/python scripts/eval_tutor_record.py

The app records the student's answers and tells the tutor in its system prompt
(app/assessments/state.py). A reply passes when it gives the recorded score or progress (or says
nothing is answered yet, when nothing is), and fails when it claims it can't see the answers, or that
a finished test isn't done. Records are synthetic and built with the app's own code: no database, no
student data. Each run is one model call. Run it after any change to what the tutor is told: on
2026-10-01 a finished test was told in words this model read as "not answered yet" (4 of 30 replies
right), although the record was in the prompt. Exits 1 when a case passes less often than --min.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

AT = "2026-10-01T10:00:00+00:00"
QUIZ = {
    "title": "Plant cells",
    "questions": [
        {
            "question": "Which organelle makes food in a plant cell?",
            "options": ["Mitochondrion", "Chloroplast", "Nucleus", "Vacuole"],
            "answer": "B",
            "explanation": "Photosynthesis happens in chloroplasts.",
        },
        {
            "question": "What is a plant cell wall mainly made of?",
            "options": ["Cellulose", "Protein", "Fat", "Starch"],
            "answer": "A",
            "explanation": "Cellulose fibres make the wall rigid.",
        },
        {
            "question": "Which part controls the cell's activities?",
            "options": ["Cell wall", "Vacuole", "Nucleus", "Cytoplasm"],
            "answer": "C",
        },
        {
            "question": "Which gas do plants take in for photosynthesis?",
            "options": ["Oxygen", "Nitrogen", "Carbon dioxide", "Hydrogen"],
            "answer": "C",
        },
        {
            "question": "Where is chlorophyll found?",
            "options": ["Chloroplast", "Nucleus", "Ribosome", "Cell wall"],
            "answer": "A",
        },
    ],
}
# Q1 right, Q2 wrong, Q3 right, Q4 wrong, Q5 skipped: 2 of 5.
QUIZ_ANSWERS = [("answer", 1), ("answer", 2), ("answer", 2), ("answer", 0), ("skip", None)]
EXERCISE = {
    "text": "Plants make food by [[photosynthesis]] in their [[chloroplasts|chloroplast]], using "
    "[[carbon dioxide|CO2]] and water.",
    "explanation": "Chloroplasts hold chlorophyll, which captures light.",
}
EXERCISE_ANSWERS = ["photosynthesis", "mitochondria", "CO2"]  # 2 of 3

WORD = {0: "zero", 1: "one", 2: "two", 3: "three", 5: "five"}
# Claims a reply must never make about answers the app recorded and gave it.
BLIND = (
    r"can'?t see|cannot see|can'?t access|unable to see|do(?:n'?t| not) have access|"
    r"don'?t (?:yet )?have (?:your|the) (?:results|score)"
)
NOT_DONE = (
    r"haven'?t (?:yet )?(?:completed|finished|taken)|not (?:yet )?(?:completed|finished)|"
    r"once you (?:finish|complete)|just started"
)
# Nothing answered (or checked) yet, said any way. Where nothing was recorded, "I can't see your
# answers until you press Check answers" is true, so those cases forbid only a claimed score.
NOT_YET = (
    r"haven'?t (?:yet )?(?:answered|started|attempted|filled|checked|submitted|done|completed|finished)|"
    r"not (?:yet )?(?:been )?(?:answered|started|attempted|filled|checked|submitted|completed|finished)|"
    r"no (?:answers|questions|blanks) (?:yet|answered|filled)|question\s*\**1\**\s*(?:/|of)|check answers|"
    r"abhi tak|nahi (?:diya|kiya|bhara)|अभी तक|नहीं|0\s*(?:/|out of|of)"
)


def claimed_score(total: int) -> str:
    """A reply that reports a score when there is none: "you scored 3 out of 5"."""
    return rf"(?:scored?|got|correct|right)\D{{0,12}}\b[1-{total}]\s*(?:/|out of|of)\s*{total}\b"


def number(value: int) -> str:
    return rf"\**(?:{value}|{WORD.get(value, value)})\**"


def score(right: int, total: int) -> str:
    """ "2 out of 5", "2/5", "**2** of the 5", "5 mein se 2"."""
    return (
        rf"\b{number(right)}\s*(?:/|out of|of)\s*(?:the\s+)?{number(total)}\b|"
        rf"\b{number(total)}\s*(?:[^\W\d]+\s+)?(?:mein|me|में)\s*(?:se|से)\s*{number(right)}\b"
    )


def build_cases() -> list[dict]:
    from app.assessments import state

    def reply(language: str, spec: dict) -> str:
        return f"Here you go.\n\n```{language}\n{json.dumps(spec, indent=2)}\n```"

    def record(content: str, request: str, answers: list) -> dict:
        records, error = state.build(content, request)
        assert records and error is None, error
        current = records[0]
        for index, (action, value) in enumerate(answers):
            current, _ = state.respond(
                current,
                status="complete",
                client_hash=current["hash"],
                question=index,
                action=action,
                value=value,
                at=AT,
            )
        return current

    quiz = reply("quiz", QUIZ)
    quiz_request = "Quiz me with 5 MCQs on plant cells."
    exercise = reply("fill-blank", EXERCISE)
    exercise_request = "Give me a fill in the blanks exercise on photosynthesis."
    return [
        {
            "name": "test finished",
            "chat": (quiz_request, quiz),
            "record": record(quiz, quiz_request, QUIZ_ANSWERS),
            "questions": [
                "how was my performance?",
                "how did I do?",
                "what was my score?",
                "which questions did I get wrong?",
                "mera test kaisa gaya?",
            ],
            "expect": score(2, 5),
            "forbid": f"{BLIND}|{NOT_DONE}",
        },
        {
            # A long chat: the test itself has left the transcript the tutor sees; the record's
            # wording of what was missed must still let it say what the mistakes were about.
            "name": "test out of view",
            "chat": (
                "Explain how plants make their food.",
                "Plants make food by photosynthesis: light, water and carbon dioxide become sugar.",
            ),
            "record": record(quiz, quiz_request, QUIZ_ANSWERS),
            "questions": ["which questions did I get wrong in my test, and what were they about?"],
            "expect": r"cellulose|cell wall|chlorophyll|chloroplast|carbon dioxide",
            "forbid": rf"{BLIND}|don'?t have (?:the|your) (?:questions|test)",
        },
        {
            "name": "test in progress",
            "chat": (quiz_request, quiz),
            "record": record(quiz, quiz_request, QUIZ_ANSWERS[:2]),
            "questions": ["how am I doing so far?", "what's my score till now?", "abhi tak kitne sahi hue?"],
            "expect": rf"{score(2, 5)}|{score(1, 2)}|question\s*\**3\b|"
            rf"\b{number(2)}\s*(?:questions|sawal|sawaal|answered|सवाल)|\b{number(1)}\s*(?:correct|right|sahi|सही)",
            "forbid": BLIND,
        },
        {
            "name": "test not started",
            "chat": (quiz_request, quiz),
            "record": record(quiz, quiz_request, []),
            "questions": ["how did I do?", "what's my score?"],
            "expect": NOT_YET,
            "forbid": claimed_score(5),
        },
        {
            "name": "exercise checked",
            "chat": (exercise_request, exercise),
            "record": record(exercise, exercise_request, [("answer", EXERCISE_ANSWERS)]),
            "questions": ["did I get the blanks right?", "how did I do on the exercise?", "kitne blanks sahi the?"],
            "expect": score(2, 3),
            "forbid": f"{BLIND}|{NOT_DONE}",
        },
        {
            "name": "exercise not answered",
            "chat": (exercise_request, exercise),
            "record": record(exercise, exercise_request, []),
            "questions": ["did I get the blanks right?", "how did I do on the exercise?"],
            "expect": NOT_YET,
            "forbid": claimed_score(3),
        },
    ]


async def run(args: argparse.Namespace) -> int:
    from app.assessments import state
    from app.chat.assistant import system_prompt_for
    from app.llm.base import ChatMessage, GenerationOptions, LLMRateLimited
    from app.llm.factory import build_llm
    from app.rag.context import build_llm_messages
    from app.settings import get_settings

    settings = get_settings()
    llm = build_llm(settings)
    options = GenerationOptions(temperature=settings.llm_temperature, max_output_tokens=500)
    # One call at a time: the gateway allows 50 requests a minute per key, and on the server that key
    # also answers the students.
    gate = asyncio.Semaphore(1)

    async def ask(messages: list[ChatMessage]) -> str:
        for attempt in range(4):
            async with gate:
                try:
                    stream = await llm.stream(messages, options)
                    return "".join([part.text async for part in stream.parts])
                except LLMRateLimited:
                    if attempt == 3:
                        raise
            await asyncio.sleep(15 * 2**attempt)
        raise AssertionError("unreachable")

    model = f"{settings.llm_primary_model} (temperature {settings.llm_temperature})"
    policy = "on" if settings.tutor_teaching_policy else "off"
    print(
        f"model: {model}, {args.runs} runs per question, teaching policy {policy}, "
        f"question bank {'on' if settings.question_bank_tests else 'off'}, study scope {settings.study_scope}"
    )
    failed_cases = []
    for case in build_cases():
        system = system_prompt_for(  # the prompt as production builds it: its bank blocks and scope policy
            None,
            True,
            state.tutor_summary([case["record"]]),
            teaching=settings.tutor_teaching_policy,
            bank="" if settings.question_bank_tests else None,
            scoped=settings.study_scope == "on",
        )
        request, reply = case["chat"]
        passed = total = 0
        for question in case["questions"]:
            # The reply as the chat shows it to the model (its own exercise answers blanked).
            chat = [
                ChatMessage("user", request),
                ChatMessage("assistant", state.for_model(reply)),
                ChatMessage("user", question),
            ]
            messages = build_llm_messages(
                system,
                chat,
                [],
                max_input_chars=settings.llm_max_input_chars,
                max_context_chars=settings.rag_max_context_chars,
            ).messages
            replies = await asyncio.gather(*(ask(messages) for _ in range(args.runs)))
            good = [
                bool(re.search(case["expect"], text, re.I)) and not re.search(case["forbid"], text, re.I)
                for text in replies
            ]
            passed, total = passed + sum(good), total + len(good)
            print(f"{sum(good):3d}/{len(good)}  {case['name']:22s} {question}")
            for ok, text in zip(good, replies, strict=True):
                if not ok:
                    print(f"           missed: {' '.join(text.split())[:180]}")
        rate = passed / total
        print(f"      {case['name']}: {passed}/{total} ({rate:.0%})")
        if rate < args.min:
            failed_cases.append(case["name"])
    if failed_cases:
        print(f"FAIL: below {args.min:.0%}: {', '.join(failed_cases)}")
        return 1
    print(f"PASS: every case at {args.min:.0%} or better")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", type=int, default=5, help="model calls per question (default 5)")
    parser.add_argument("--min", type=float, default=0.95, help="lowest pass rate per case (default 0.95)")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
