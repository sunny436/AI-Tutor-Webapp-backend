"""
The current turn must reach the gathering prompt in the SAME turn.

The bug this pins: `gather()` ran before the user's message was recorded, so
the prompt read a transcript that stopped at the assistant's previous
question. The model saw its own question with no reply and asked it again —
verbatim. Measured in production on 2026-08-31, turns 1 and 2 of the
serious-condition deep-dive came back byte-for-byte identical:

    User: "mujhe cancer ho gaya hai"
    You:  "Kis type ka cancer hai aur kahan diagnose hua?"
    User: "blood cancer hai"
    You:  "Kis type ka cancer hai aur kahan diagnose hua?"     <-- identical

Sections 1-3 are DETERMINISTIC: they intercept `gather` and assert on the
exact history string it is handed, so they pin the mechanism rather than the
model's mood. Sections 4+ are live, and check the behaviour that mechanism
exists to produce.

    python tests/test_turn_visibility.py
"""

from __future__ import annotations

import asyncio
import re
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


from src import safety  # noqa: E402
from src.consult import graph, run_turn  # noqa: E402
from src.consult.gathering import Gathered  # noqa: E402
from src.consult.schema import ConsultContext  # noqa: E402
from src.consult.state import remember_user_message  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# ===========================================================================
# 0. remember_user_message on its own — pure, no model.
# ===========================================================================
ctx = ConsultContext(problem="acidity", phase="gathering")
ctx = remember_user_message(ctx, "2 din se hai")
check("the message is recorded", [t.text for t in ctx.chat_history] == ["2 din se hai"],
      [t.text for t in ctx.chat_history])

ctx = remember_user_message(ctx, "2 din se hai")
check("recording the SAME message twice stores it once",
      [t.text for t in ctx.chat_history] == ["2 din se hai"],
      [t.text for t in ctx.chat_history])

ctx = remember_user_message(ctx, "khaane ke baad zyada")
check("a different message is appended",
      [t.text for t in ctx.chat_history] == ["2 din se hai", "khaane ke baad zyada"],
      [t.text for t in ctx.chat_history])

ctx = remember_user_message(ctx, "   ")
check("blank text is ignored", len(ctx.chat_history) == 2, len(ctx.chat_history))

# The guard compares against the same [:400] truncation remember_chat applies,
# so a long message must match itself rather than slipping past.
long_msg = "x" * 500
ctx2 = remember_user_message(ConsultContext(problem="p", phase="gathering"), long_msg)
ctx2 = remember_user_message(ctx2, long_msg)
check("a >400-char message is not stored twice by the guard",
      len(ctx2.chat_history) == 1, len(ctx2.chat_history))

# Only an ADJACENT repeat is suppressed; saying the same thing again later is real.
ctx3 = ConsultContext(problem="p", phase="gathering")
ctx3 = remember_user_message(ctx3, "haan")
ctx3 = remember_user_message(ctx3, "aur kuch nahi")
ctx3 = remember_user_message(ctx3, "haan")
check("the same word said again LATER is kept (not an adjacent repeat)",
      len(ctx3.chat_history) == 3, [t.text for t in ctx3.chat_history])


# ===========================================================================
# 1-3. What `gather` actually receives. Deterministic: the model is replaced.
# ===========================================================================
CAPTURED: list[dict] = []


def _install_spy(ready: bool = False, reply: str = "Aur bataiye?",
                 profile_facts: dict | None = None):
    """Replace `gather` with one that records its arguments."""
    async def spy(**kwargs):
        CAPTURED.append(kwargs)
        return Gathered(reply=reply, condition="Acidity", symptoms=["jalan"],
                        ready=ready, profile_facts=profile_facts or {})
    graph.gather = spy


_real_gather = graph.gather


async def _test_visible_immediately():
    CAPTURED.clear()
    _install_spy()

    # Turn 0: the opening complaint arrives as `problem`.
    r = await run_turn(problem="mujhe pet me jalan hoti hai", raw_context=None,
                       answers=None, free_text=None, profile="")
    hist0 = CAPTURED[-1]["history"]
    check("A: the opening complaint is visible to gather in turn 0",
          "mujhe pet me jalan hoti hai" in hist0, hist0[:120])

    # Turn 1: the answer arrives as `free_text`. THIS is what used to be lost.
    ctx = r.context.model_dump()
    await run_turn(problem="", raw_context=ctx, answers=None,
                   free_text="blood cancer hai", profile="")
    hist1 = CAPTURED[-1]["history"]
    check("A: the CURRENT answer is visible to gather in the same turn",
          "blood cancer hai" in hist1, hist1[-200:])
    check("D: the current answer appears exactly once in that history",
          hist1.count("blood cancer hai") == 1,
          f"count={hist1.count('blood cancer hai')}\n{hist1}")
    check("D: the previous assistant question is still there exactly once",
          hist1.count("Aur bataiye?") == 1, f"count={hist1.count('Aur bataiye?')}")
    check("the opening complaint survives too",
          "mujhe pet me jalan hoti hai" in hist1, hist1[:150])


asyncio.run(_test_visible_immediately())


async def _test_no_duplicate_on_restart():
    """The new-complaint restart records the message and FALLS THROUGH.

    That branch is why `remember_user_message` has to be idempotent: without
    the guard the restarted complaint reaches the prompt twice.
    """
    CAPTURED.clear()
    _install_spy()
    r = await run_turn(problem="mujhe pet me jalan hoti hai", raw_context=None,
                       answers=None, free_text=None, profile="")
    ctx = r.context.model_dump()
    # A genuinely different complaint, which restarts the consultation.
    await run_turn(problem="", raw_context=ctx, answers=None,
                   free_text="ab mujhe baal jhadne ki problem ho rahi hai", profile="")
    hist = CAPTURED[-1]["history"]
    check("D: a restarting complaint appears exactly once, not twice",
          hist.count("baal jhadne") <= 1, f"count={hist.count('baal jhadne')}\n{hist}")


asyncio.run(_test_no_duplicate_on_restart())


async def _test_persisted_history_not_doubled():
    """The stored transcript must not gain two copies of the same message."""
    CAPTURED.clear()
    _install_spy()
    r = await run_turn(problem="mujhe pet me jalan hoti hai", raw_context=None,
                       answers=None, free_text=None, profile="")
    ctx = r.context.model_dump()
    r2 = await run_turn(problem="", raw_context=ctx, answers=None,
                        free_text="2 din se hai", profile="")
    texts = [t["text"] for t in r2.context.model_dump()["chat_history"]]
    check("D: the persisted transcript holds the answer exactly once",
          texts.count("2 din se hai") == 1, texts)
    check("the persisted transcript keeps the assistant's question",
          "Aur bataiye?" in texts, texts)
    check("user turn is stored BEFORE the reply it prompted",
          texts.index("2 din se hai") < len(texts) - 1
          or texts[-1] != "2 din se hai", texts)


asyncio.run(_test_persisted_history_not_doubled())


async def _test_final_gathering_answer_reaches_the_end():
    """The turn that ENDS the intake used to be dropped entirely.

    When `gather` returns ready, the code records only the assistant's side —
    so the user's most informative message never reached the transcript that
    the supportive-care reply and the final plan are written from.
    """
    CAPTURED.clear()
    _install_spy(ready=True)
    r = await run_turn(problem="mujhe pet me jalan hoti hai", raw_context=None,
                       answers=None, free_text=None, profile="")
    ctx = r.context.model_dump()
    r2 = await run_turn(problem="", raw_context=ctx, answers=None,
                        free_text="khaane ke baad zyada hoti hai", profile="")
    texts = [t["text"] for t in r2.context.model_dump()["chat_history"]]
    check("the intake-ending answer is not dropped from the transcript",
          "khaane ke baad zyada hoti hai" in texts, texts)


asyncio.run(_test_final_gathering_answer_reaches_the_end())

graph.gather = _real_gather  # live tests below use the real model


# ===========================================================================
# 4. LIVE: the cancer example must not repeat its question.
# ===========================================================================
async def _turn(msg, ctx=None, as_problem=False):
    if ctx is None or as_problem:
        return await run_turn(problem=msg, raw_context=ctx, answers=None,
                              free_text=None, profile="")
    return await run_turn(problem="", raw_context=ctx, answers=None,
                          free_text=msg, profile="")


def _norm(text: str) -> str:
    r"""Compare meaning, not punctuation — a reworded repeat is still a repeat.

    UNICODE-AWARE, and it was not. `[^a-z0-9 ]+` deletes every character that
    is not ASCII, so a Devanagari reply normalised to the EMPTY STRING — and
    `_norm(first) != _norm(second)` became `"" != ""`, which is False. The
    Devanagari repeat check could therefore never pass, and, far worse, could
    never have caught a real repeat either. It reported a defect in the
    product on every run while testing nothing at all.

    `\W` with the default Unicode semantics keeps letters in any script and
    drops only punctuation, so Hinglish behaves exactly as before and
    Devanagari is now actually compared.
    """
    return re.sub(r"[\W_]+", " ", (text or "").casefold(), flags=re.UNICODE).strip()


async def _test_cancer_no_repeat():
    replies = []
    ctx = None
    for i, msg in enumerate(["mujhe cancer ho gaya hai", "blood cancer hai",
                             "AML hai, chemotherapy chal rahi hai"]):
        r = await _turn(msg, ctx, as_problem=(i == 0))
        ctx = r.context.model_dump()
        replies.append(r.answer or "")

    check("B: no two deep-dive replies are identical",
          len(set(replies)) == len(replies),
          f"{len(set(replies))} distinct of {len(replies)}")
    check("B: no two deep-dive replies are identical after normalisation",
          len({_norm(x) for x in replies}) == len(replies),
          [x[:70] for x in replies])
    # The specific regression: still asking for the type after being told twice.
    check("B: the type is not asked again once AML has been given",
          not re.search(r"kis type ka cancer|kaunse type ka cancer|what type of cancer",
                        replies[-1], re.I),
          replies[-1][:160])
    check("B: the deep-dive still withholds a six-section plan",
          not any(h in r for r in replies for h in
                  ("Root Cause", "Ayurveda Remedies", "When To See A Doctor")))
    check("B: no medicine is offered during the deep-dive",
          not any(safety.names_medicine(r) for r in replies),
          [safety.names_medicine(r) for r in replies if safety.names_medicine(r)])


asyncio.run(_test_cancer_no_repeat())


# ===========================================================================
# 5. LIVE: ordinary gathering must not repeat either.
# ===========================================================================
async def _test_normal_gathering_no_repeat():
    replies = []
    ctx = None
    msgs = ["mujhe khaane ke baad pet me jalan hoti hai", "2 hafte se hai",
            "spicy khaane par zyada", "koi dawa nahi leta"]
    for i, msg in enumerate(msgs):
        r = await _turn(msg, ctx, as_problem=(i == 0))
        ctx = r.context.model_dump()
        replies.append(r.answer or "")
        if ctx.get("phase") == "asking_focus":
            break
    check("C: ordinary gathering never repeats a question verbatim",
          len(set(replies)) == len(replies),
          f"{len(set(replies))} distinct of {len(replies)}")
    check("C: ordinary gathering never repeats after normalisation",
          len({_norm(x) for x in replies}) == len(replies),
          [x[:70] for x in replies])
    check("C: the duration answer is not asked for again",
          sum(1 for r in replies[1:]
              if re.search(r"kab se|kitne (samay|din)|how long", r, re.I)) <= 1,
          [x[:70] for x in replies])


asyncio.run(_test_normal_gathering_no_repeat())


# ===========================================================================
# 6. LIVE: Hindi / Hinglish / Devanagari still work.
# ===========================================================================
async def _test_languages():
    for label, msgs in [
        ("English", ["I have burning in my stomach after meals", "for two weeks now"]),
        ("Devanagari", ["मुझे खाने के बाद पेट में जलन होती है", "दो हफ्ते से है"]),
    ]:
        ctx = None
        replies = []
        for i, m in enumerate(msgs):
            r = await _turn(m, ctx, as_problem=(i == 0))
            ctx = r.context.model_dump()
            replies.append(r.answer or "")
        check(f"{label}: replies substantively across two turns",
              all(len(x) > 30 for x in replies), [len(x) for x in replies])
        check(f"{label}: the second reply is not a repeat of the first",
              _norm(replies[0]) != _norm(replies[1]), replies[1][:80])


asyncio.run(_test_languages())


# ===========================================================================
# 7. LIVE: safety and profile collection are unchanged.
# ===========================================================================
async def _test_safety_and_profile():
    # E — a red flag still escalates, and still sticks.
    r = await _turn("mujhe seene me tez dard ho raha hai aur saans nahi aa rahi")
    check("E: a red flag still escalates", r.kind == "escalation", r.kind)
    ctx = r.context.model_dump()
    check("E: risk_level is still recorded", ctx.get("risk_level") == "urgent",
          ctx.get("risk_level"))
    r2 = await _turn("koi gharelu nuskha bata do", dict(ctx))
    check("E: a later turn still cannot answer past the red flag",
          r2.kind == "escalation" or r2.context.model_dump().get("risk_level") == "urgent",
          r2.kind)

    # F — facts volunteered in passing still reach the profile.
    r = await _turn("mujhe diabetes hai aur metformin leta hoon, ab acidity ho rahi hai")
    prof = r.context.model_dump()["patient_profile"]
    check("F: a volunteered condition still reaches the profile",
          any("diabet" in c.lower() for c in prof["conditions"]), prof["conditions"])
    check("F: a volunteered medicine still reaches the profile",
          any("metformin" in m.lower() for m in prof["medications"]), prof["medications"])

    # F — and a fact given on a LATER turn is captured in that same turn,
    # which is the part the lag made unreliable.
    ctx = r.context.model_dump()
    r2 = await _turn("mujhe penicillin se allergy bhi hai", dict(ctx))
    prof2 = r2.context.model_dump()["patient_profile"]
    check("F: a fact stated mid-consultation is captured in that turn",
          any("penicillin" in a.lower() for a in prof2["allergies"])
          or any("penicillin" in c.lower() for c in prof2["conditions"]),
          prof2["allergies"])


asyncio.run(_test_safety_and_profile())


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== turn visibility: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}  [{str(detail)[:200]}]")
sys.exit(0 if passed == len(results) else 1)
