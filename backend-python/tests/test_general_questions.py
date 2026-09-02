"""
General informational questions get an ANSWER, not an intake form.

"What is Ayurveda?" was answered correctly and then closed with "please
describe any specific concerns... I would be happy to build you a
personalized plan" — KNOWLEDGE_ANSWER_PROMPT ended by inviting a consultation
on EVERY answer, so somebody asking what Ayurveda IS was handed an intake
prompt. These tests pin the fix, and pin that the health-complaint flow is
NOT affected by it.

Live (Ollima + GraphRAG), same convention as test_intake.py/test_evidence.py.

    python tests/test_general_questions.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

# Windows redirects stdout as cp1252, and several test NAMES below are
# Devanagari — so `print`ing a PASS raised UnicodeEncodeError and killed the
# run partway through. The suite could not be run to completion on the
# platform its own docstring tells you to run it on. Same reconfigure
# `server.py` applies, for the same reason.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


from src.consult import run_turn  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# The phrasings that mean "stop answering and start an intake". These are what
# the prompt used to mandate at the end of every knowledge answer.
INTAKE_PUSH = (
    "describe any specific",
    "describe any health",
    "describe your health",
    "describe your problem",
    "describe them",
    "what's troubling you",
    "what is troubling you",
    "how are you feeling",
    "personalized plan",
    "personalised plan",
    "build you a",
    "apni problem",
    "apni samasya",
    "kya takleef",
)


def intake_push(answer: str) -> list[str]:
    lowered = (answer or "").lower()
    return [phrase for phrase in INTAKE_PUSH if phrase in lowered]


async def ask(question: str):
    """A general question, asked cold — no prior conversation."""
    return await run_turn(
        problem=question, raw_context=None, answers=None, free_text=None, profile=""
    )


# ===========================================================================
# 1. The three reported questions get a real informational answer, and none
#    of them ends by steering the reader into a consultation.
# ===========================================================================
GENERAL_QUESTIONS = (
    "Tell me something about Ayurveda",
    "What is Ayurveda?",
    "What are the principles of Ayurveda?",
)


async def _test_general_question(question: str):
    result = await ask(question)
    answer = result.answer or ""
    lowered = answer.lower()

    check(
        f"{question!r} is answered conversationally, not turned into an intake",
        result.kind == "chat" and result.context.phase != "gathering",
        f"kind={result.kind} phase={result.context.phase}",
    )
    check(
        f"{question!r} gets a substantial answer about Ayurveda",
        len(answer) > 200 and "ayurved" in lowered,
        f"{len(answer)} chars",
    )
    pushes = intake_push(answer)
    check(
        f"{question!r} does NOT ask the reader to describe a health problem",
        not pushes,
        f"found {pushes}" if pushes else "",
    )


for _question in GENERAL_QUESTIONS:
    asyncio.run(_test_general_question(_question))


# ===========================================================================
# 2. It answers the QUESTION — a principles question should actually talk
#    about principles, not just say the word "Ayurveda" a lot.
# ===========================================================================
async def _test_answer_is_on_topic():
    result = await ask("What are the principles of Ayurveda?")
    lowered = (result.answer or "").lower()
    # Any of the real concepts an answer about Ayurvedic principles would use.
    concepts = ("dosha", "vata", "pitta", "kapha", "agni", "dinacharya",
                "balance", "constitution", "element")
    hits = [c for c in concepts if c in lowered]
    check(
        "the principles question is answered with actual Ayurveda concepts",
        len(hits) >= 2,
        f"concepts mentioned: {hits}",
    )


asyncio.run(_test_answer_is_on_topic())


# ===========================================================================
# 3. Hinglish/Devanagari general questions behave the same way.
# ===========================================================================
async def _test_language(question: str, label: str):
    result = await ask(question)
    answer = result.answer or ""
    check(
        f"{label} general question gets a real answer",
        result.kind == "chat" and len(answer) > 150,
        f"kind={result.kind} {len(answer)} chars",
    )
    pushes = intake_push(answer)
    check(
        f"{label} general question does not push a consultation",
        not pushes,
        f"found {pushes}" if pushes else "",
    )


asyncio.run(_test_language("Ayurveda ke baare mein kuch bataiye", "Hinglish"))
asyncio.run(_test_language("आयुर्वेद क्या है?", "Devanagari"))


# ===========================================================================
# 4. THE FLOW THAT MUST NOT CHANGE. A health COMPLAINT still opens the
#    consultation — this fix narrows how a general ANSWER ends, and must not
#    have made the assistant stop starting consultations when it should.
# ===========================================================================
async def _test_health_complaint_still_gathers():
    result = await run_turn(
        problem="mujhe acidity ho rahi hai",
        raw_context=None, answers=None, free_text=None, profile="",
    )
    check(
        "a health COMPLAINT still opens gathering (flow unchanged)",
        result.kind == "chat" and result.context.phase == "gathering",
        f"kind={result.kind} phase={result.context.phase}",
    )
    check(
        "the gathering turn still asks the user something",
        len((result.answer or "").strip()) > 20,
        (result.answer or "")[:120],
    )


asyncio.run(_test_health_complaint_still_gathers())


# ===========================================================================
# 5. The documented exception: a question that ALREADY carries a personal
#    complaint may still offer to look at it properly. This is not required
#    to fire (the model may simply answer), so it is asserted only that the
#    reply is a real answer rather than a deflection.
# ===========================================================================
async def _test_question_carrying_a_complaint():
    result = await ask("mujhe acidity hai, aise me kya khana chahiye?")
    answer = result.answer or ""
    check(
        "a question carrying a complaint still gets real guidance",
        len(answer) > 150,
        f"kind={result.kind} {len(answer)} chars",
    )


asyncio.run(_test_question_carrying_a_complaint())


# ===========================================================================
# A QUESTION ABOUT A CONDITION IS NOT A REPORT OF HAVING IT
#
# Reported from production. The full sentence worked and the way people
# actually type it did not:
#
#   "What are the symptoms of acidity?"  -> knowledge, answered directly
#   "symptoms of acidity"                -> HEALTH, and a health verdict opens
#                                           an intake, so the reply was
#                                           "could you tell me how long you
#                                           have had this?"
#
# A bare noun phrase reads like somebody naming their problem, so the model
# hesitated and guessed wrong. The decision is made in code now.
# ===========================================================================
from src.consult.router import asks_for_information  # noqa: E402

INFORMATIONAL = [
    "symptoms of acidity",
    "migraine ke symptoms",
    "acidity ke lakshan",
    "causes of migraine",
    "benefits of yoga",
    "ashwagandha ke fayde",
    "side effects of triphala",
    "types of pranayama",
    "meaning of dinacharya",
]
for text in INFORMATIONAL:
    check(f"a question about a condition is informational: {text!r}",
          asks_for_information(text), "")

# THE OTHER HALF, and the one that must never break: somebody describing
# their own problem is a complaint, even when they use the same nouns.
COMPLAINTS = [
    "mujhe acidity hai",
    "mujhe acidity ke lakshan ho rahe hain",
    "I have symptoms of acidity",
    "my symptoms are getting worse",
    "mera sar dard hota hai",
    "मुझे माइग्रेन है",
    "main pareshan hoon",
    "I have migraine",
]
for text in COMPLAINTS:
    check(f"...but describing your own problem is NOT: {text!r}",
          not asks_for_information(text), "")


# ===========================================================================
# "CAN I TAKE THIS?" USES WHAT THEY ARE ALREADY TAKING
#
# Both "what is ashwagandha" and "can I take ashwagandha" are knowledge
# questions, and the knowledge path had no interaction check at all. Measured:
# a profile holding hypothyroidism and thyronorm answered "it depends on your
# individual health profile" — a true sentence that used none of the profile
# it was talking about.
#
# The detector below is what separates the two. It must stay narrow: turning
# "what are the benefits of ashwagandha" into a personal safety consultation
# is the over-personalisation this whole change is against.
# ===========================================================================
from src.consult.router import asks_if_safe_for_me  # noqa: E402

PERMISSION = [
    "Can I take Ashwagandha?",
    "can i take triphala with my medicines",
    "kya main ashwagandha le sakta hoon",
    "mere liye ye safe hai kya",
    "mere liye surakshit hai?",
    "should I take this herb",
    "क्या मैं अश्वगंधा ले सकता हूँ",
]
for text in PERMISSION:
    check(f"a permission question is recognised: {text[:38]!r}",
          asks_if_safe_for_me(text), "")

NOT_PERMISSION = [
    "What are the benefits of Ashwagandha?",
    "what is ashwagandha",
    "ashwagandha ke fayde",
    "symptoms of acidity",
    "mujhe acidity hai",
    "what is Ayurveda?",
]
for text in NOT_PERMISSION:
    check(f"...and a plain question is NOT: {text[:38]!r}",
          not asks_if_safe_for_me(text), "")

# The interaction table is what makes the answer personal, and it must still
# say the same thing it says everywhere else in the product.
from src.clinical import interactions as _ix  # noqa: E402

_v = _ix.check("ashwagandha", medications=["thyronorm"])
check("the thyroid clash is still caught for a permission question",
      _v.blocked and _v.reasons, _v.as_dict())
_safe = _ix.check("shatavari", medications=["metformin"])
check("...and a herb with no clash is not blocked on a guess",
      _safe.status == "safe", _safe.as_dict())


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== general questions: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, _ in results:
        if not ok:
            print(f"  - {name}")
sys.exit(0 if passed == len(results) else 1)
