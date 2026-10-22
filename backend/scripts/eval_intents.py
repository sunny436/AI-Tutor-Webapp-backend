"""How well does the intent router read what students ask? Classify synthetic messages with Ollalink's
model exactly as the app does (app/intents/classifier.py: text_for, request_body, score and
explicit_hint_only; the group question, then the chosen group's), then check the release gates.

    python scripts/eval_intents.py --key-file ../ollalink.txt --sweep    # dev split: choose τ and the group τ
    python scripts/eval_intents.py --key-file ../ollalink.txt --split test --tau T --group-tau G   # once, frozen
    python scripts/eval_intents.py --key-file ../ollalink.txt --probe    # dev split: compact vs long option texts

On the server, where the latency gate is measured and the tutor's model is (nothing is written anywhere):

    systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env \\
        -p WorkingDirectory=/opt/aichat/app/backend \\
        /opt/aichat/app/backend/.venv/bin/python scripts/eval_intents.py --split test --tau T --group-tau G [--replay]

Every case asks the group question and, unless the group is `other`, that group's own question,
whatever P(group) is: both thresholds (τ: INTENT_MIN_CONFIDENCE, the group τ:
INTENT_MIN_GROUP_CONFIDENCE) are applied afterwards, so the sweep can try every pair. Latency is per
request (the first request, cold, apart) and end to end (both requests, as a turn waits for them; the
app skips the second below the group τ, so this is an upper bound): gate 9 is on the end-to-end warm
p95. `--probe` asks each case's group question once and its group's question twice, with the compact
option texts the app sends and with the owner's long criteria: accuracy and latency of each, to decide
whether the second request could afford the longer texts within INTENT_ROUTER_TIMEOUT_S.

`--replay` is Gate B: the real tutor, told an applied intent. Every hint_only case three times: no reply
may give the answer (an answer or steps card, or the case's "forbid"); every test-intent case once, with
the question bank's chapters for Class 10 (or the class it names): at least 95% must set a bank test.

Cases: tests/fixtures/intent_cases.jsonl, one JSON object per line: "id", "text", "context" ({"previous",
"reply_tail"} or null), "attachments" (file kinds), "expected" (an intent id, or null when none should be
applied), "also" (other acceptable ids), "lang" (en, hi or hinglish), "split" (dev or test), "tags" and
"forbid" (a regex a hint-only reply must not match; optional). A case too close to one of the 46 examples
in the owner's criteria (token Jaccard 0.6 or more) is left out. Only ids and numbers are printed, never
a case's text. The cases are synthetic: passing shows the router reads messages like them, not how
accurately it reads real students' messages. Exits 1 when a gate fails, 2 when the run cannot start.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.intents.classifier import (  # noqa: E402
    CLASSIFY_PATH,
    KEY_HEADER,
    QUESTIONS,
    USER_AGENT,
    explicit_hint_only,
    request_body,
    score,
    text_for,
)
from app.intents.taxonomy import ABSTAIN, BANK_INTENTS, GROUP_MEMBERS, INTENTS  # noqa: E402
from app.llm.base import ChatMessage  # noqa: E402

CASES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "intent_cases.jsonl"
SWEEP = [round(0.30 + 0.05 * step, 2) for step in range(9)]  # τ: 0.30 ... 0.70
# (τ, group τ): a group τ at or below τ never changes a decision (the score is at most P(group)), so
# each τ is paired with itself (the group τ only skips requests) and with the stricter group τs above it.
PAIRS = [(tau, group) for tau in SWEEP for group in sorted({tau, 0.4, 0.5, 0.6, 0.7, 0.8}) if group >= tau]
NEAR_EXAMPLE = 0.6  # token Jaccard with one of the owner's 46 examples
HTTP_TIMEOUT_S = 10.0  # latency is measured, not cut at INTENT_ROUTER_TIMEOUT_S
ANSWER_CARD = re.compile(r"^\s*:::(?:answer|steps)\b", re.M)
BANK_REQUEST = re.compile(r"question-bank|\"chapter\"\s*:\s*\"[A-Z]{3,6}\d-CH\d{2}\"")
WORD = re.compile(r"\w+")
EXAMPLES = [set(WORD.findall(intent.criterion.split("Example:", 1)[1].lower())) for intent in INTENTS.values()]


def near_example(text: str) -> bool:
    words = set(WORD.findall(text.lower()))
    return any(len(words & example) / len(words | example) >= NEAR_EXAMPLE for example in EXAMPLES)


def load(path: Path, split: str) -> tuple[list[dict], list[str]]:
    """The split's cases, and the ids of those left out as near-copies of the owner's examples."""
    cases, rejected = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        known = [case.get("expected"), *(case.get("also") or [])]
        if any(name is not None and name not in INTENTS for name in known):
            raise SystemExit(f"case {case.get('id')}: an id that is not one of the 46 intents")
        if split == "all" or case.get("split") == split:
            (rejected if near_example(case["text"]) else cases).append(case)
    return cases, [str(case.get("id")) for case in rejected]


def conversation(case: dict) -> list[ChatMessage]:
    context = case.get("context") or {}
    earlier = [ChatMessage("user", context["previous"])] if context.get("previous") else []
    earlier += [ChatMessage("assistant", context["reply_tail"])] if context.get("reply_tail") else []
    return [*earlier, ChatMessage("user", case["text"])]


def long_body(text: str, group: str) -> dict:
    """The group's own question with the owner's long criteria as its option texts: `--probe` only (the
    app never sends them). The option ids are the same, so `score` checks the response as usual."""
    asked = {**QUESTIONS[group], "options": {name: INTENTS[name].criterion for name in GROUP_MEMBERS[group]}}
    return {"text": text, "questions": {group: asked}}


def retry_after(response: httpx.Response) -> float:
    try:
        return float(min(max(int(response.headers.get("Retry-After", "")), 1), 60))
    except ValueError:
        return 3.0


class Pace:
    """At most --rate requests a second, both questions included."""

    def __init__(self, rate: float):
        self.gap, self.next_at = 1 / rate, time.monotonic()

    async def wait(self) -> None:
        await asyncio.sleep(max(0.0, self.next_at - time.monotonic()))
        self.next_at = time.monotonic() + self.gap


async def post(client: httpx.AsyncClient, body: dict, pace: Pace) -> tuple[str | None, Any, float]:
    """One request: (the error, or None; the response's JSON; seconds). 429 and 503 (busy or loading)
    are waited out and tried again: this measures the model, not its queue."""
    await pace.wait()
    for attempt in range(4):
        started = time.perf_counter()
        try:
            response = await client.post(CLASSIFY_PATH, json=body)
        except httpx.TimeoutException:
            return "timeout", None, time.perf_counter() - started
        except httpx.HTTPError:
            return "connection", None, time.perf_counter() - started
        seconds = time.perf_counter() - started
        if response.status_code in (429, 503) and attempt < 3:
            await asyncio.sleep(retry_after(response))
            continue
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code != 200:
            return f"http_{response.status_code}", payload, seconds
        return (None, payload, seconds) if payload is not None else ("bad_json", None, seconds)
    raise AssertionError("unreachable")


def rate(hits: int, total: int) -> float | None:
    return hits / total if total else None


def fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def timing(seconds: list[float]) -> dict:
    if not seconds:
        return {"n": 0}
    ordered = sorted(seconds)
    p95 = ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]
    return {"n": len(ordered), "p50": statistics.median(ordered), "p95": p95, "max": ordered[-1]}


def latency(results: list[dict]) -> dict:
    """Seconds: the first request (cold), then warm (every later case without an error) for each request
    and end to end, both requests together."""
    warm = [r for r in results[1:] if r["error"] is None]
    return {
        "cold": results[0]["group_s"] if results else None,
        "group_question": timing([r["group_s"] for r in warm]),
        "intent_question": timing([r["intent_s"] for r in warm if r["intent_s"] is not None]),
        "end_to_end": timing([r["group_s"] + (r["intent_s"] or 0.0) for r in warm]),
    }


def show(row: dict) -> str:
    return f"p50 {fmt(row.get('p50'))} p95 {fmt(row.get('p95'))} max {fmt(row.get('max'))} (n={row['n']})"


def decided(result: dict, tau: float, group_tau: float) -> str | None:
    """What the app applies: hint_only for an explicit request, else the classifier's intent at the pair."""
    if result["explicit"]:
        return "hint_only"
    return result["scored"].decide(tau, group_tau)[0] if result["scored"] else None


def right(result: dict, chosen: str | None) -> bool:
    return chosen is not None and (chosen == result["expected"] or chosen in result["also"])


def measure(results: list[dict], tau: float, group_tau: float) -> dict:
    applied = [(result, decided(result, tau, group_tau)) for result in results]
    asked = [(r, c) for r, c in applied if r["expected"]]
    covered = [(r, c) for r, c in asked if c]
    abstain = [c for r, c in applied if not r["expected"]]

    def precision(ids) -> float | None:
        chosen = [(r, c) for r, c in applied if c in ids]
        return rate(sum(right(r, c) for r, c in chosen), len(chosen))

    def recall(ids) -> float | None:
        wanted = [(r, c) for r, c in applied if r["expected"] in ids]
        return rate(sum(right(r, c) for r, c in wanted), len(wanted))

    per_intent = {}
    for name in INTENTS:
        hits = sum(1 for r, c in applied if c == name and r["expected"] == name)
        p, q = (
            rate(hits, sum(1 for _, c in applied if c == name)),
            rate(hits, sum(r["expected"] == name for r in results)),
        )
        if p is not None or q is not None:
            f1 = 2 * p * q / (p + q) if p and q else 0.0
            per_intent[name] = {"precision": p, "recall": q, "f1": f1}
    languages = sorted({str(r["lang"]) for r in results})
    return {
        "tau": tau,
        "group_tau": group_tau,
        "coverage": rate(len(covered), len(asked)),
        "selective": rate(sum(right(r, c) for r, c in covered), len(covered)),
        "group_of_applied": rate(
            sum(INTENTS[c].group == INTENTS[r["expected"]].group for r, c in covered), len(covered)
        ),
        "false_accept": rate(sum(c is not None for c in abstain), len(abstain)),
        "hint_only": {
            "precision": precision({"hint_only"}),
            "recall": recall({"hint_only"}),
            "into_solve": sum(
                1 for r, c in applied if r["expected"] == "hint_only" and c and INTENTS[c].group == "solve"
            ),
        },
        "evaluate_written_answer": {
            "precision": precision({"evaluate_written_answer"}),
            "recall": recall({"evaluate_written_answer"}),
        },
        "planning_precision": precision(set(GROUP_MEMBERS["planning"])),
        "bank_precision": precision(BANK_INTENTS),
        "by_language": {
            lang: rate(
                sum(right(r, c) for r, c in covered if r["lang"] == lang), sum(r["lang"] == lang for r, _ in covered)
            )
            for lang in languages
        },
        "per_intent": per_intent,
        "macro_f1": statistics.mean(row["f1"] for row in per_intent.values()) if per_intent else None,
        "confusions": Counter(
            f"{r['expected'] or 'none'} -> {c or 'none'}" for r, c in applied if c != r["expected"] and not right(r, c)
        ).most_common(20),
    }


def gates(m: dict) -> list[tuple[str, bool, str]]:
    """Gates 1-8 at one pair of thresholds. A precision with nothing applied passes (nothing was wrong);
    a rate with no cases to measure it on fails (no evidence)."""

    def at_least(value: float | None, floor: float) -> bool:
        return value is not None and value >= floor

    def none_or(value: float | None, floor: float) -> bool:
        return value is None or value >= floor

    hint, written, languages = m["hint_only"], m["evaluate_written_answer"], m["by_language"]
    return [
        (
            "1 selective accuracy >= 0.85 at coverage >= 0.60",
            at_least(m["selective"], 0.85) and at_least(m["coverage"], 0.60),
            f"selective {fmt(m['selective'])}, coverage {fmt(m['coverage'])}",
        ),
        ("2 group accuracy of applied >= 0.92", at_least(m["group_of_applied"], 0.92), fmt(m["group_of_applied"])),
        (
            "3 abstain false-accept <= 0.15",
            m["false_accept"] is not None and m["false_accept"] <= 0.15,
            fmt(m["false_accept"]),
        ),
        (
            "4 hint_only recall >= 0.90, precision >= 0.85, at most 1 into solve",
            at_least(hint["recall"], 0.90) and none_or(hint["precision"], 0.85) and hint["into_solve"] <= 1,
            f"recall {fmt(hint['recall'])}, precision {fmt(hint['precision'])}, into solve {hint['into_solve']}",
        ),
        (
            "5 evaluate_written_answer precision >= 0.90, recall >= 0.80",
            none_or(written["precision"], 0.90) and at_least(written["recall"], 0.80),
            f"precision {fmt(written['precision'])}, recall {fmt(written['recall'])}",
        ),
        ("6 planning precision >= 0.95", none_or(m["planning_precision"], 0.95), fmt(m["planning_precision"])),
        ("7 test-intent precision >= 0.90", none_or(m["bank_precision"], 0.90), fmt(m["bank_precision"])),
        (
            "8 selective accuracy >= 0.80 in each language",
            bool(languages) and all(at_least(value, 0.80) for value in languages.values()),
            ", ".join(f"{lang} {fmt(value)}" for lang, value in languages.items()),
        ),
    ]


def preflight(error: str | None, payload: Any) -> bool:
    """Whether the run can go on after its first request (401/403: the key is not approved)."""
    if error is None:
        return True
    code = ((payload or {}).get("error") or {}).get("code") if isinstance(payload, dict) else None
    print(f"preflight failed: {error}{f' ({code})' if code else ''}; for 401/403 the key is not approved")
    return False


def row_for(case: dict) -> dict:
    """A case's row before any request: what it expects, and whether the explicit guard reads it."""
    return {
        "id": str(case.get("id")),
        "expected": case.get("expected"),
        "also": list(case.get("also") or []),
        "lang": case.get("lang"),
        "explicit": explicit_hint_only(case["text"]),
        "scored": None,
        "error": None,
        "group_s": 0.0,
        "intent_s": None,
    }


async def classify(args: argparse.Namespace, cases: list[dict], client: httpx.AsyncClient) -> list[dict] | None:
    """Both questions for every case (the second unless the group is `other`), paced at --rate. None
    when the first request (the preflight) fails."""
    pace, results = Pace(args.rate), []
    for index, case in enumerate(cases):
        text, row = text_for(conversation(case), tuple(case.get("attachments") or ())), row_for(case)
        error, first, row["group_s"] = await post(client, request_body(text, "group"), pace)
        if index == 0 and not preflight(error, first):
            return None
        scored = score(first) if error is None else None
        if scored is not None and scored.group != ABSTAIN:
            error, second, row["intent_s"] = await post(client, request_body(text, scored.group), pace)
            scored = score(first, second) if error is None else None
        row["scored"], row["error"] = scored, error or (None if scored else "bad_response")
        results.append(row)
    return results


def report(args: argparse.Namespace, results: list[dict], tau: float, group_tau: float) -> tuple[dict, bool]:
    """Prints the report (ids and numbers only) and returns it, with whether every gate passed."""
    scored = [r for r in results if r["scored"]]
    asked = [r for r in scored if r["expected"]]
    errors = Counter(r["error"] for r in results if r["error"])
    error_rate = rate(sum(errors.values()), len(results)) or 0.0
    seconds = latency(results)
    end_to_end = seconds["end_to_end"]
    expected_group = {r["id"]: INTENTS[r["expected"]].group if r["expected"] else ABSTAIN for r in scored}
    buckets: dict[str, list[bool]] = {}
    for r in asked:  # a case read as `other` has no score: the lowest bucket
        low = min(int((r["scored"].confidence or 0.0) * 5), 4) / 5
        buckets.setdefault(f"{low:.1f}-{low + 0.2:.1f}", []).append(r["scored"].best == r["expected"])
    m = measure(results, tau, group_tau)
    summary = {
        "split": args.split,
        "cases": len(results),
        "group_accuracy": rate(sum(r["scored"].group == expected_group[r["id"]] for r in scored), len(scored)),
        "best_strict": rate(sum(r["scored"].best == r["expected"] for r in asked), len(asked)),
        "best_lenient": rate(sum(right(r, r["scored"].best) for r in asked), len(asked)),
        "confidence_buckets": {k: {"n": len(v), "accuracy": rate(sum(v), len(v))} for k, v in sorted(buckets.items())},
        "explicit_guard": {
            "hits": sum(r["explicit"] for r in results),
            "expected_hint_only": sum(r["explicit"] and r["expected"] == "hint_only" for r in results),
        },
        "latency_s": seconds,
        "errors": dict(errors),
        "error_rate": error_rate,
        "at_tau": m,
    }
    frozen = "frozen on the dev split: " if args.split == "test" else ""
    print(f"split {args.split}: {len(results)} cases")
    print(f"{frozen}INTENT_MIN_CONFIDENCE (τ) = {tau}, INTENT_MIN_GROUP_CONFIDENCE (group τ) = {group_tau}")
    print(f"group accuracy {fmt(summary['group_accuracy'])} (the group question alone)")
    print(f"best label: strict {fmt(summary['best_strict'])}, lenient {fmt(summary['best_lenient'])}")
    for bucket, row in summary["confidence_buckets"].items():
        print(f"  confidence {bucket}: {row['n']:4d} cases, best-label accuracy {fmt(row['accuracy'])}")
    guard = summary["explicit_guard"]
    print(f"explicit hint-only guard: {guard['hits']} hits, {guard['expected_hint_only']} of them expected hint_only")
    print(f"macro-F1 (information) {fmt(m['macro_f1'])}; confusions (expected -> applied):")
    for pair, count in m["confusions"]:
        print(f"  {count:3d}  {pair}")
    print(f"latency (s): cold first request {fmt(seconds['cold'])}; warm:")
    print(f"  the group question       {show(seconds['group_question'])}")
    print(f"  the group's own question {show(seconds['intent_question'])}")
    print(f"  end to end (both)        {show(end_to_end)}")
    print(f"errors {dict(errors) or 'none'} ({error_rate:.1%})")
    if end_to_end.get("p95"):
        timeout_s = min(2.0, max(1.0, 2 * end_to_end["p95"]))
        print(f"  INTENT_ROUTER_TIMEOUT_S at 2 x the end-to-end p95, within 1-2 s: {timeout_s:.1f}")
    if args.split != "test":  # on the test split only the frozen pair is shown
        print("τ      group τ  coverage  selective  group  false-accept  gates 1-8")
        sweep = []
        for value, group_value in PAIRS:
            row = measure(results, value, group_value)
            passed = sum(ok for _, ok, _ in gates(row))
            sweep.append({"passed": passed, **{k: row[k] for k in ("tau", "group_tau", "coverage", "selective")}})
            print(
                f"{value:.2f}   {group_value:.2f}     {fmt(row['coverage'])}     {fmt(row['selective'])}      "
                f"{fmt(row['group_of_applied'])}  {fmt(row['false_accept'])}         {passed}/8"
            )
        summary["sweep"] = sweep
        if args.sweep:  # the pair that passes every gate with the most coverage; then the lowest τs
            passing = [row for row in sweep if row["passed"] == 8]
            chosen = max(
                passing, key=lambda row: (row["coverage"] or 0.0, -row["tau"], -row["group_tau"]), default=None
            )
            summary["recommended"] = chosen and {"tau": chosen["tau"], "group_tau": chosen["group_tau"]}
            print(
                f"recommended: INTENT_MIN_CONFIDENCE={chosen['tau']} INTENT_MIN_GROUP_CONFIDENCE={chosen['group_tau']}"
                if chosen
                else "recommended: none, no pair passes gates 1-8"
            )
    checks = gates(m)
    p95 = end_to_end.get("p95")
    latency_ok = error_rate <= 0.02 and (args.skip_latency_gate or (p95 is not None and p95 <= 1.0))
    checks.append(
        (
            "9 errors <= 2%" + ("" if args.skip_latency_gate else ", end-to-end warm p95 <= 1.0 s"),
            latency_ok,
            f"errors {error_rate:.1%}" + ("" if args.skip_latency_gate else f", p95 {fmt(p95)} s"),
        )
    )
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    print("These cases are synthetic: the numbers do not show accuracy on real students' messages.")
    summary["gates"] = [{"gate": name, "passed": ok, "detail": detail} for name, ok, detail in checks]
    return summary, all(ok for _, ok, _ in checks)


async def probe(
    args: argparse.Namespace, cases: list[dict], client: httpx.AsyncClient, tau: float, group_tau: float
) -> dict | None:
    """The group's own question with the compact option texts the app sends vs the owner's long
    criteria, on the dev split: accuracy and latency of each. Each case's group question is asked once;
    the two variants' order alternates, so neither always comes second. None when the preflight fails."""
    pace, rows = Pace(args.rate), {"compact": [], "long": []}
    for index, case in enumerate(cases):
        text = text_for(conversation(case), tuple(case.get("attachments") or ()))
        error, first, group_s = await post(client, request_body(text, "group"), pace)
        if index == 0 and not preflight(error, first):
            return None
        scored = score(first) if error is None else None
        for variant in ("compact", "long") if index % 2 == 0 else ("long", "compact"):
            row = row_for(case) | {"group_s": group_s, "scored": scored, "error": error}
            if scored is not None and scored.group != ABSTAIN:
                body = request_body(text, scored.group) if variant == "compact" else long_body(text, scored.group)
                failed, second, row["intent_s"] = await post(client, body, pace)
                row["scored"], row["error"] = (score(first, second) if failed is None else None), failed
            row["error"] = row["error"] or (None if row["scored"] else "bad_response")
            rows[variant].append(row)
    found = {}
    print(f"dev split: {len(cases)} cases; τ = {tau}, group τ = {group_tau}")
    for variant, results in rows.items():
        asked = [r for r in results if r["scored"] and r["expected"]]
        m, seconds = measure(results, tau, group_tau), latency(results)
        found[variant] = {
            "best_strict": rate(sum(r["scored"].best == r["expected"] for r in asked), len(asked)),
            "best_lenient": rate(sum(right(r, r["scored"].best) for r in asked), len(asked)),
            "coverage": m["coverage"],
            "selective": m["selective"],
            "latency_s": seconds,
            "errors": dict(Counter(r["error"] for r in results if r["error"])),
        }
        row = found[variant]
        print(
            f"{variant} option texts: best label strict {fmt(row['best_strict'])}, lenient {fmt(row['best_lenient'])};"
            f" coverage {fmt(row['coverage'])}, selective {fmt(row['selective'])}; errors {row['errors'] or 'none'}"
        )
        print(f"  the group's own question {show(seconds['intent_question'])}")
        print(f"  end to end (both)        {show(seconds['end_to_end'])}")
    return found


async def replay(cases: list[dict]) -> tuple[dict, bool]:
    """Gate B: the real tutor, told the expected intent (an explicit request applies hint_only itself)."""
    from sqlalchemy import text

    from app.chat.assistant import system_prompt_for
    from app.db.session import Database
    from app.llm.base import GenerationOptions, LLMRateLimited
    from app.llm.factory import build_llm
    from app.qbank import chat_tests
    from app.rag.context import build_llm_messages
    from app.settings import get_settings

    settings = get_settings()
    llm = build_llm(settings)
    options = GenerationOptions(temperature=settings.llm_temperature, max_output_tokens=1200)
    gate = asyncio.Semaphore(1)  # one call at a time: on the server the key also answers the students

    async def ask(case: dict, bank: str | None, intent: str) -> str:
        system = system_prompt_for(
            None,
            settings.tutor_interactive_blocks,
            "",
            teaching=settings.tutor_teaching_policy,
            bank=bank,
            intent=intent,
            scoped=settings.study_scope == "on",  # the prompt as production builds it
        )
        messages = build_llm_messages(
            system,
            conversation(case),
            [],
            max_input_chars=settings.llm_max_input_chars,
            max_context_chars=settings.rag_max_context_chars,
        ).messages
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

    empty = "" if settings.question_bank_tests else None
    leaks = replies = 0
    for case in [case for case in cases if case.get("expected") == "hint_only"]:
        for _ in range(3):
            reply = await ask(case, empty, "hint_only")
            forbid = case.get("forbid")
            leaked = bool(ANSWER_CARD.search(reply) or (forbid and re.search(forbid, reply, re.I)))
            leaks, replies = leaks + leaked, replies + 1
            if leaked:
                print(f"  {case['id']}: the reply gave the answer")
    print(f"hint_only: {replies} replies, {leaks} gave the answer (gate: 0)")
    banks, banked = [case for case in cases if case.get("expected") in BANK_INTENTS], 0
    if banks and settings.question_bank_tests:  # without the bank there is no bank test to set
        db = Database(settings)
        try:
            async with db.sessionmaker() as session:
                await session.execute(text("SET TRANSACTION READ ONLY"))  # the chapter lists only
                for case in banks:
                    menu = await chat_tests.menu(session, case["text"], "Class 10", None, asked=True)
                    found = BANK_REQUEST.search(await ask(case, menu, case["expected"])) is not None
                    banked += found
                    if not found:
                        print(f"  {case['id']}: no question-bank test")
        finally:
            await db.dispose()
    share = rate(banked, len(banks))
    print(f"test intents: {banked} of {len(banks)} set a question-bank test ({fmt(share)}; gate: 0.95)")
    ok = leaks == 0 and replies > 0 and share is not None and share >= 0.95
    print(f"{'PASS' if ok else 'FAIL'}  Gate B")
    return {"hint_replies": replies, "hint_leaks": leaks, "bank_cases": len(banks), "bank_set": banked}, ok


def api_key(args: argparse.Namespace) -> tuple[str, str]:
    if args.key_file:
        found = re.search(r"sk_[A-Za-z0-9_-]+", Path(args.key_file).read_text(encoding="utf-8"))
        return (found.group(0), "file") if found else ("", "file")
    from app.settings import get_settings

    return get_settings().ollalink_api_key.get_secret_value(), "env"


async def run(args: argparse.Namespace, cases: list[dict]) -> int:
    from app.settings import get_settings

    settings = get_settings()
    if args.replay:
        summary, ok = await replay(cases)
        return finish(args, {"replay": summary}, ok)
    key, source = api_key(args)
    print(f"key: {source}")
    if not key:
        print("no Ollalink key: set OLLALINK_API_KEY or pass --key-file")
        return 2
    tau = args.tau if args.tau is not None else settings.intent_min_confidence
    group_tau = args.group_tau if args.group_tau is not None else settings.intent_min_group_confidence
    headers = {KEY_HEADER: key, "User-Agent": USER_AGENT, "Accept": "application/json"}
    async with httpx.AsyncClient(
        base_url=settings.ollalink_base_url.rstrip("/"), headers=headers, timeout=HTTP_TIMEOUT_S
    ) as client:
        if args.probe:
            found = await probe(args, cases, client, tau, group_tau)
            return 2 if found is None else finish(args, {"probe": found}, True)
        results = await classify(args, cases, client)
    if results is None:
        return 2
    summary, ok = report(args, results, tau, group_tau)
    return finish(args, summary, ok)


def finish(args: argparse.Namespace, summary: dict, ok: bool) -> int:
    if args.json_path:
        Path(args.json_path).write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--tau", type=float, help="the score threshold (default INTENT_MIN_CONFIDENCE)")
    parser.add_argument("--group-tau", type=float, help="the P(group) threshold (default INTENT_MIN_GROUP_CONFIDENCE)")
    parser.add_argument("--sweep", action="store_true", help="dev only: recommend τ and the group τ")
    parser.add_argument("--rate", type=float, default=2.0, help="requests per second (default 2)")
    parser.add_argument("--probe", action="store_true", help="dev only: compact vs long option texts")
    parser.add_argument("--replay", action="store_true", help="Gate B with the real tutor (the server)")
    parser.add_argument("--json", dest="json_path", help="also write the report to this file")
    parser.add_argument("--key-file", help="a file holding the key (the first sk_... in it)")
    parser.add_argument("--skip-latency-gate", action="store_true", help="off the server: gate 9 counts errors only")
    args = parser.parse_args()
    if (args.sweep or args.probe) and args.split != "dev":
        parser.error("--sweep and --probe decide on the dev split only")
    if args.split == "test" and not args.replay and (args.tau is None or args.group_tau is None):
        parser.error(
            "the test split runs once, with both thresholds frozen on the dev split: pass --tau and --group-tau"
        )
    if args.rate <= 0:
        parser.error("--rate must be positive")
    if not Path(args.cases).is_file():
        print(f"no cases file: {args.cases}")
        return 2
    cases, rejected = load(Path(args.cases), args.split)
    if rejected:
        print(f"left out {len(rejected)} near-copies of the owner's examples: {', '.join(rejected)}")
    if not cases:
        print(f"no {args.split} cases in {args.cases}")
        return 2
    return asyncio.run(run(args, cases))


if __name__ == "__main__":
    raise SystemExit(main())
