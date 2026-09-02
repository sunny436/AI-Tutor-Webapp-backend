"""
A serious condition must be answered once, then moved forward — not repeated.

THE BUG THIS PINS, reported from production
A patient on chemotherapy asked for yoga:

    "mujha yoga bta sakta ho kuch isko sahi karna k liya"
    "koi yoga techniques btao mujha"

and got the same reply both times — measured at 98% identical. Two independent
faults, and the first one hid the second:

  1. `asks_for_guidance_now` matched "batao" but not "btao" or "bta". Hinglish
     drops that vowel constantly, so neither message was recognised as a
     request. The intake never ended and the same question came back forever.

  2. Once it DID end, `context.serious_condition` sent every later turn through
     `write_supportive_care` — a FIRST-CONTACT prompt that re-acknowledges the
     diagnosis and restates that the doctor's treatment is the treatment. Right
     the first time, a loop every time after.

And fixing (1) exposed a third, worse one: with the request finally
recognised, `phase` became "completed" and the next turn fell through to the
PLAN path, which had no serious-condition guard at all. A blood-cancer patient
was handed a "**Yoga & Breathing**" plan section.

WHAT MUST REMAIN TRUE
Asking to STOP or SWAP treatment still gets the displacement warning, every
time, however often it is asked. Red flags are untouched. The plan path stays
impossible for a diagnosed serious condition.

    python tests/test_supportive_care.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from src import safety  # noqa: E402
from src.consult import graph, run_turn  # noqa: E402
from src.consult.gathering import Gathered  # noqa: E402
from src.consult.router import Route, asks_for_guidance_now  # noqa: E402

results: list[tuple[str, bool, str]] = []
CALLS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, str(detail)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# 1. THE REQUEST IS RECOGNISED, however the vowels fall
# ===========================================================================
ASKED = [
    "mujha yoga bta sakta ho kuch isko sahi karna k liya",   # the reported one
    "koi yoga techniques btao mujha",                        # and the second
    "yoga bta do",
    "diet btaiye",
    "kuch upay btana",
    "yoga bata do",                                          # already worked
]
for text in ASKED:
    check(f"1. a request is recognised however it is spelled: {text[:38]!r}",
          asks_for_guidance_now(text), "")

NOT_ASKED = [
    "mujhe acidity hai",
    "haan theek hai",
    "main btana chahta tha ki mujhe diabetes hai",   # a disclosure, not a request
    "subah khali pet jyada hoti hai",
]
for text in NOT_ASKED:
    check(f"2. ...and ordinary talk still is not one: {text[:38]!r}",
          not asks_for_guidance_now(text), "")


# ===========================================================================
# 2. SUPPORT ALONGSIDE TREATMENT vs REPLACING IT
#
# The whole fix rests on this line. Everything on the left needs a gentle
# answer; everything on the right needs the displacement warning.
# ===========================================================================
SUPPORTIVE = [
    "mujha yoga bta sakta ho kuch isko sahi karna k liya",
    "koi yoga techniques btao mujha",
    "I have chemotherapy, can you suggest some yoga?",
    "kya yoga kar sakta hoon chemo ke saath",
    "chemotherapy chal rahi hai",
    "thakan ke liye kuch bata dijiye",
]
for text in SUPPORTIVE:
    check(f"3. asking for support is NOT a replacement request: {text[:36]!r}",
          not safety.asks_to_replace_treatment(text), "")

REPLACEMENT = [
    "chemo band karke ayurveda le sakte hain",
    "chemotherapy band kar dun kya",
    "can I stop my chemotherapy and do yoga",
    "ayurveda ki jagah yoga kar lun",
    "instead of chemo can I take herbs",
    "only yoga se theek ho jayega",
    "main dawa chhod dun",
]
for text in REPLACEMENT:
    check(f"4. REPLACING TREATMENT IS ALWAYS CAUGHT: {text[:36]!r}",
          safety.asks_to_replace_treatment(text), "")


# ===========================================================================
# 3. THE WIRING — open once, then move; never a plan
# ===========================================================================
def install(*, ready: bool = True):
    """Every model-backed step replaced, so the ROUTING is what is measured."""
    CALLS.clear()

    async def _gather(**kw):
        CALLS.append("gather")
        return Gathered(reply="Aur bataiye?", condition="Blood cancer",
                        symptoms=["thakan"], ready=ready, profile_facts={})

    async def _focus(reply, language=""):
        CALLS.append("classify_focus")
        return ["yoga"]

    async def _route(message, history="", greeted=False, language="", documents=""):
        return Route(intent="health", problem=message)

    async def _supportive(problem, language=""):
        CALLS.append("write_supportive_care")
        return ("Sunkar dukh hua. Aapka medical treatment hi mukhya chikitsa hai, "
                "use band nahi karna. Main saath me madad kar sakta hoon.")

    async def _continue(context, request, language=""):
        CALLS.append("write_supportive_continue")
        return ("Bahut gentle rakhte hain. Apni oncology team se confirm kar "
                "lijiye ki halki activity abhi safe hai.")

    async def _plan(**kw):
        CALLS.append("write_plan")
        return "**Root Cause**\nx\n\n**Yoga & Breathing**\nAsanas: Vajrasana."

    async def _retrieve(context, principal, conversation_id):
        CALLS.append("retrieve")
        return None, []

    graph.gather = _gather
    graph.classify_focus = _focus
    graph.route_message = _route
    graph.write_supportive_care = _supportive
    graph.write_supportive_continue = _continue
    graph.write_plan = _plan
    graph._retrieve = _retrieve


BASE = {
    "phase": "gathering", "round": 2, "problem": "blood cancer",
    "condition": "Blood cancer", "language": "hinglish", "greeted": True,
    "profile_loaded": True, "serious_condition": "blood cancer, on chemotherapy",
    "chat_history": [{"role": "user", "text": "mujhe blood cancer hai"}],
}


async def turn(text, ctx):
    return await run_turn(problem="", raw_context=ctx, answers=None,
                          free_text=text, profile="")


async def test_opens_once_then_moves():
    install()
    ctx = dict(BASE)

    r1 = await turn("mujha yoga bta sakta ho kuch isko sahi karna k liya", ctx)
    check("5. the first supportive turn OPENS with the standing position",
          "write_supportive_care" in CALLS, CALLS)
    check("6. ...and records that it has been said",
          r1.context.supportive_opened is True, r1.context.supportive_opened)
    check("7. ...and never writes a plan", "write_plan" not in CALLS, CALLS)

    install()
    r2 = await turn("koi yoga techniques btao mujha", r1.context.model_dump())
    check("8. THE SECOND TURN MOVES FORWARD INSTEAD OF REPEATING",
          "write_supportive_continue" in CALLS, CALLS)
    check("9. ...and does NOT re-issue the opening paragraph",
          "write_supportive_care" not in CALLS, CALLS)
    check("10. ...and still never writes a plan", "write_plan" not in CALLS, CALLS)

    install()
    r3 = await turn("aur kuch bata dijiye", r2.context.model_dump())
    check("11. a third clarification also moves",
          "write_supportive_continue" in CALLS and "write_supportive_care" not in CALLS,
          CALLS)
    check("12. THE SAFETY STATE IS STICKY ACROSS EVERY TURN",
          r3.context.serious_condition == BASE["serious_condition"],
          r3.context.serious_condition)
    check("13. ...and the replies are not the same text",
          r2.answer.strip() != r1.answer.strip(), "")


asyncio.run(test_opens_once_then_moves())


async def test_replacement_always_warns():
    install()
    ctx = dict(BASE)
    r1 = await turn("koi yoga techniques btao mujha", ctx)
    install()
    r2 = await turn("chemo band karke sirf ayurveda le lun?", r1.context.model_dump())
    check("14. ASKING TO STOP TREATMENT RE-ISSUES THE DISPLACEMENT WARNING",
          "write_supportive_care" in CALLS, CALLS)
    check("15. ...and does not quietly continue as if it were a support request",
          "write_supportive_continue" not in CALLS, CALLS)
    check("16. ...and still never writes a plan", "write_plan" not in CALLS, CALLS)
    check("17. ...and it says not to stop", "band nahi karna" in r2.answer,
          r2.answer[:60])


asyncio.run(test_replacement_always_warns())


async def test_plan_path_is_closed():
    """The P0 the fix exposed: `phase=completed` used to bypass the guard."""
    # Real Phase literals only. "plan_ready" is not one, and passing it made
    # `load_context` discard the whole context — serious_condition included —
    # so the guard was never reached and the test blamed the guard.
    for phase in ("completed", "asking_focus", "collecting", "choosing", "gathering"):
        install()
        ctx = dict(BASE)
        ctx["phase"] = phase
        ctx["help_types"] = ["yoga"]
        r = await turn("yoga bata do", ctx)
        check(f"18. NO PLAN FOR A SERIOUS CONDITION AT phase={phase!r}",
              "write_plan" not in CALLS, CALLS)
        check(f"19. ...and no plan section reaches the reader at {phase!r}",
              "**Root Cause**" not in r.answer and "**Yoga & Breathing**" not in r.answer,
              r.answer[:60])


asyncio.run(test_plan_path_is_closed())


async def test_hindi_and_devanagari():
    for text in ["मुझे योग बता सकते हो क्या",
                 "kuch yoga btao na",
                 "please suggest gentle yoga"]:
        install()
        ctx = dict(BASE)
        ctx["supportive_opened"] = True
        r = await turn(text, ctx)
        check(f"20. a clarification in any script moves forward: {text[:30]!r}",
              "write_supportive_continue" in CALLS and "write_plan" not in CALLS,
              CALLS)
        check(f"21. ...and produces a reply: {text[:24]!r}", bool(r.answer.strip()))


asyncio.run(test_hindi_and_devanagari())


# ===========================================================================
# 4. RED FLAGS ARE UNTOUCHED. The fix must not have bought conversation flow
#    with anybody's safety.
# ===========================================================================
for text in ["ulti me khoon aa raha hai", "seene me tez dard aur saans nahi aa rahi",
             "ulti me खून aa raha hai"]:
    check(f"22. a red flag still escalates: {text[:34]!r}", bool(safety.scan(text)))
check("23. a serious condition is still recognised",
      safety.is_serious_condition("mujhe blood cancer hai"))
check("24. ...and a FEAR of one still is not",
      not safety.is_serious_condition("darr lagta hai kahin cancer to nahi"))


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== supportive care: {passed}/{len(results)} passed =====")
if passed != len(results):
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name} :: {detail}")
    sys.exit(1)
