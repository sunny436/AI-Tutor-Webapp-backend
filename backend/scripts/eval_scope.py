"""How well does the study scope filter (app/intents/scope.py) decide what PadhAI helps with? Read the
labelled synthetic cases exactly as the app does (the fixed rules, then text_for and the scope question,
checked like every classifier response), then report each kind of mistake separately.

    python scripts/eval_scope.py --key-file ../ollalink.txt --sweep                  # dev split: choose the τ
    python scripts/eval_scope.py --key-file ../ollalink.txt --split test --tau-redirect R --tau C   # once, frozen

On the server, where the latency gate is measured (nothing is written anywhere):

    systemd-run --pipe --wait --collect -p EnvironmentFile=/etc/aichat/api.env \\
        -p WorkingDirectory=/opt/aichat/app/backend \\
        /opt/aichat/app/backend/.venv/bin/python scripts/eval_scope.py --split test --tau-redirect R --tau C

Cases: tests/fixtures/scope_cases.jsonl, one JSON object per line: "id", "text", "context" (earlier turns,
optional), "attachments" (file kinds, optional), "expected" (a decision), "acceptable" (every decision that
is right for it), "category" (the brief's A-F), "lang", "split". Only ids and numbers are printed, never a
case's text. The cases are synthetic: passing shows the filter decides messages like them, not how
accurately it decides real students' messages.

- **False rejection:** a case that should be answered (REDIRECT not acceptable) is redirected. The gate.
- **False acceptance:** a case that should be redirected is answered (the policy in the prompt still applies).

`--replay` (on the host: the real tutor) is Gate B, what a student would get with STUDY_SCOPE on: every
unrelated case, every mixed, support and clarify case and REPLAY_STUDY learning cases, each answered by the
app's redirect or by the tutor told the policy and its decision's line. It prints one JSON line per case
with the reply (synthetic cases, to be read: did it decline the unrelated task, answer the learning one?).
Exits 1 when a gate fails, 2 when the run cannot start.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.intents.classifier import (  # noqa: E402
    CLASSIFY_PATH,
    KEY_HEADER,
    USER_AGENT,
    BadResponse,
    check,
    explicit_hint_only,
    request_body,
    text_for,
)
from app.intents.scope import (  # noqa: E402
    ALLOW_STUDY,
    ALLOW_SUPPORT,
    CLARIFY,
    PARTIAL_ALLOW,
    QUESTION_ID,
    REDIRECT,
    Scope,
    decide,
    redirect_copy,
    settled,
)
from app.llm.base import ChatMessage  # noqa: E402
from app.progress.learning import is_meaningful  # noqa: E402

CASES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "scope_cases.jsonl"
TAUS = [round(0.30 + 0.05 * step, 2) for step in range(14)]  # 0.30 ... 0.95
HTTP_TIMEOUT_S = 20.0
REPLAY_STUDY = 20  # learning cases replayed: curiosity, learning through fun, writing for school, facts, coding
REPLAY_STUDY_CATEGORIES = (
    "C.beyond_syllabus",
    "C.edu_style",
    "C.academic_writing",
    "C.in_syllabus",
    "C.projects_coding",
)
GATES = {"false_rejection_max": 0.02, "redirect_recall_min": 0.70, "added_p95_ms_max": 400, "error_rate_max": 0.02}


def load(split: str) -> list[dict]:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [case for case in cases if split == "all" or case["split"] == split]


def conversation(case: dict) -> list[ChatMessage]:
    turns = [ChatMessage(turn["role"], turn["content"]) for turn in case.get("context") or []]
    return [*turns, ChatMessage("user", case["text"])]


def rule(case: dict) -> Scope | None:
    """The fixed rules, in the app's order: a hint-only request, then small talk and bare files."""
    if explicit_hint_only(case["text"]):
        return Scope(ALLOW_STUDY, reason="hint_only", source="rule")
    return settled(is_meaningful(case["text"]), tuple(case.get("attachments") or ()))


async def read(client: httpx.AsyncClient, case: dict) -> dict:
    """The scope question's checked probabilities and timings for one case, asked as the app asks it."""
    text = text_for(conversation(case), tuple(case.get("attachments") or ()))
    started = time.perf_counter()
    try:
        response = await client.post(CLASSIFY_PATH, json=request_body(text, QUESTION_ID))
    except httpx.HTTPError as error:
        return {"error": type(error).__name__}
    client_ms = int((time.perf_counter() - started) * 1000)
    if response.status_code != 200:
        return {"error": f"http_{response.status_code}", "client_ms": client_ms}
    try:
        found = check(response.json(), QUESTION_ID)
    except (BadResponse, ValueError) as error:
        return {"error": f"bad_response:{error}", "client_ms": client_ms}
    server = response.headers.get("x-process-ms")
    return {
        "probabilities": found,
        "client_ms": client_ms,
        "server_ms": int(float(server)) if server and re.fullmatch(r"\d+(\.\d+)?", server) else None,
    }


def decision(case: dict, reading: dict, tau_redirect: float, tau: float) -> Scope:
    if reading.get("rule"):
        return reading["rule"]
    if "probabilities" not in reading:
        return Scope(None, reason="failed")
    return decide(reading["probabilities"], tau_redirect, tau)


def rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def metrics(cases: list[dict], readings: dict[str, dict], tau_redirect: float, tau: float) -> dict:
    got = {case["id"]: decision(case, readings[case["id"]], tau_redirect, tau) for case in cases}
    allow = [c for c in cases if REDIRECT not in c["acceptable"]]
    redirect = [c for c in cases if c["expected"] == REDIRECT]
    mixed = [c for c in cases if c["expected"] == PARTIAL_ALLOW]
    clarify = [c for c in cases if c["expected"] == CLARIFY]
    plain = [c for c in cases if c["expected"] == ALLOW_STUDY and CLARIFY not in c["acceptable"]]
    # No decision (a failed reading) is the tutor with the policy: counted as an allow, never a redirect.
    final = {key: scope.decision or ALLOW_STUDY for key, scope in got.items()}
    by: dict[str, dict[str, list[int]]] = {"category": defaultdict(lambda: [0, 0]), "lang": defaultdict(lambda: [0, 0])}
    for case in cases:
        for field in by:
            by[field][case[field]][0] += final[case["id"]] in case["acceptable"]
            by[field][case[field]][1] += 1
    false_rejections = [c["id"] for c in allow if final[c["id"]] == REDIRECT]
    false_acceptances = [c["id"] for c in redirect if final[c["id"]] not in c["acceptable"]]
    return {
        "tauRedirect": tau_redirect,
        "tau": tau,
        "cases": len(cases),
        "accuracy": rate(sum(final[c["id"]] in c["acceptable"] for c in cases), len(cases)),
        "falseRejection": {"rate": rate(len(false_rejections), len(allow)), "of": len(allow), "ids": false_rejections},
        "falseAcceptance": {
            "rate": rate(len(false_acceptances), len(redirect)),
            "of": len(redirect),
            "ids": false_acceptances,
        },
        "redirectRecall": rate(sum(final[c["id"]] == REDIRECT for c in redirect), len(redirect)),
        "mixedKept": rate(sum(final[c["id"]] in (PARTIAL_ALLOW, ALLOW_STUDY) for c in mixed), len(mixed)),
        "mixedDetected": rate(sum(final[c["id"]] == PARTIAL_ALLOW for c in mixed), len(mixed)),
        "clarifyRecall": rate(sum(final[c["id"]] == CLARIFY for c in clarify), len(clarify)),
        "needlessClarify": rate(sum(final[c["id"]] == CLARIFY for c in plain), len(plain)),
        "byDecision": dict(Counter(final.values())),
        "byCategory": {key: f"{right}/{whole}" for key, (right, whole) in sorted(by["category"].items())},
        "byLanguage": {key: f"{right}/{whole}" for key, (right, whole) in sorted(by["lang"].items())},
        "wrong": sorted(
            f"{c['id']}:{c['expected']}->{final[c['id']]}" for c in cases if final[c["id"]] not in c["acceptable"]
        ),
    }


def latency(readings: dict[str, dict]) -> dict:
    asked = [r for r in readings.values() if not r.get("rule")]
    client = sorted(r["client_ms"] for r in asked if "probabilities" in r)
    server = sorted(r["server_ms"] for r in asked if r.get("server_ms") is not None)

    def p(values: list[int], q: float) -> int | None:
        return values[min(len(values) - 1, int(q * len(values)))] if values else None

    errors = Counter(r["error"].split(":")[0] for r in asked if "error" in r)
    return {
        "asked": len(asked),
        "rules": len(readings) - len(asked),
        "errors": dict(errors),
        "errorRate": rate(sum(errors.values()), len(asked)),
        # The first request after a pause loads the model (seconds): reported, left out of p50/p95.
        "coldMs": asked[0].get("client_ms") if asked else None,
        "clientP50": p(client[1:], 0.5),
        "clientP95": p(client[1:], 0.95),
        "serverP50": p(server[1:], 0.5),
        "serverP95": p(server[1:], 0.95),
        "clientMean": round(statistics.fmean(client[1:])) if len(client) > 1 else None,
    }


async def ask(cases: list[dict], key: str) -> dict[str, dict]:
    """Each case's reading, one request at a time as the service serves them: a fixed rule, or the scope
    question's checked probabilities and timings."""
    from app.settings import get_settings

    headers = {KEY_HEADER: key, "User-Agent": USER_AGENT, "Accept": "application/json"}
    base_url = get_settings().ollalink_base_url.rstrip("/")
    readings: dict[str, dict] = {}
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=HTTP_TIMEOUT_S) as client:
        for case in cases:
            found = rule(case)
            readings[case["id"]] = {"rule": found} if found else await read(client, case)
    return readings


def replay_cases(cases: list[dict]) -> list[dict]:
    unrelated = [case for case in cases if case["expected"] == REDIRECT]
    others = [case for case in cases if case["expected"] in (PARTIAL_ALLOW, ALLOW_SUPPORT, CLARIFY)]
    study = [c for c in cases if c["expected"] == ALLOW_STUDY and c["category"] in REPLAY_STUDY_CATEGORIES]
    return unrelated + others + study[:REPLAY_STUDY]


async def replay(cases: list[dict], readings: dict[str, dict], tau_redirect: float, tau: float) -> list[dict]:
    """Gate B: each case as a student would get it with STUDY_SCOPE on."""
    from app.chat.assistant import system_prompt_for
    from app.llm.base import GenerationOptions, LLMRateLimited
    from app.llm.factory import build_llm
    from app.rag.context import build_llm_messages
    from app.settings import get_settings

    settings = get_settings()
    llm = build_llm(settings)
    options = GenerationOptions(temperature=settings.llm_temperature, max_output_tokens=800)

    async def tutor(case: dict, decision: str | None) -> str:
        system = system_prompt_for(
            None,
            settings.tutor_interactive_blocks,
            "",
            teaching=settings.tutor_teaching_policy,
            bank="" if settings.question_bank_tests else None,
            scoped=True,
            scope=decision,
        )
        messages = build_llm_messages(
            system,
            conversation(case),
            [],
            max_input_chars=settings.llm_max_input_chars,
            max_context_chars=settings.rag_max_context_chars,
        ).messages
        for attempt in range(4):  # one call at a time: on the server the key also answers the students
            try:
                stream = await llm.stream(messages, options)
                return "".join([part.text async for part in stream.parts])
            except LLMRateLimited:
                if attempt == 3:
                    raise
            await asyncio.sleep(15 * 2**attempt)
        raise AssertionError("unreachable")

    rows = []
    for case in replay_cases(cases):
        scope = decision(case, readings[case["id"]], tau_redirect, tau)
        redirected = scope.decision == REDIRECT
        reply = redirect_copy(case["text"], None) if redirected else await tutor(case, scope.decision)
        row = {
            "id": case["id"],
            "expected": case["expected"],
            "category": case["category"],
            "decision": scope.decision,
            "reply": reply[:700],
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    return rows


def report(args: argparse.Namespace, cases: list[dict], readings: dict[str, dict]) -> tuple[dict, bool]:
    summary: dict[str, Any] = {"split": args.split, "latency": latency(readings)}
    if args.sweep:
        table = [metrics(cases, readings, r, t) for r in TAUS for t in TAUS]
        for row in table:
            print(
                f"τR={row['tauRedirect']:.2f} τ={row['tau']:.2f} acc={row['accuracy']:.3f} "
                f"FR={row['falseRejection']['rate']} FA={row['falseAcceptance']['rate']} "
                f"redirect={row['redirectRecall']} mixedKept={row['mixedKept']} "
                f"clarify={row['clarifyRecall']} needless={row['needlessClarify']}"
            )
        # No false rejection first; then the most redirects, the best accuracy, the widest margin.
        safe = [row for row in table if not row["falseRejection"]["ids"]]
        summary["chosen"] = max(
            safe or table,
            key=lambda row: (row["redirectRecall"] or 0, row["accuracy"] or 0, row["tauRedirect"], -row["tau"]),
        )
        return summary, True
    result = metrics(cases, readings, args.tau_redirect, args.tau)
    summary["result"] = result
    lat = summary["latency"]
    summary["gates"] = {
        "falseRejection": (result["falseRejection"]["rate"] or 0) <= GATES["false_rejection_max"],
        "redirectRecall": (result["redirectRecall"] or 0) >= GATES["redirect_recall_min"],
        "errorRate": (lat["errorRate"] or 0) <= GATES["error_rate_max"],
        "latencyP95": lat["clientP95"] is not None and lat["clientP95"] <= GATES["added_p95_ms_max"],
    }
    return summary, all(summary["gates"].values())


def api_key(args: argparse.Namespace) -> str:
    if args.key_file:
        found = re.search(r"sk_[A-Za-z0-9_-]+", Path(args.key_file).read_text(encoding="utf-8"))
        return found.group(0) if found else ""
    from app.settings import get_settings

    return get_settings().ollalink_api_key.get_secret_value()


def main() -> int:
    from app.settings import get_settings

    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--key-file", help="a file holding the key (the first sk_... in it)")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--sweep", action="store_true", help="every τ pair; choose the safest with most redirects")
    parser.add_argument("--tau-redirect", type=float, default=settings.scope_min_redirect, help="SCOPE_MIN_REDIRECT")
    parser.add_argument("--tau", type=float, default=settings.scope_min_confidence, help="SCOPE_MIN_CONFIDENCE")
    parser.add_argument("--save", help="write the readings (probabilities, timings; no text) to this file")
    parser.add_argument("--load", help="score saved readings instead of calling the service")
    parser.add_argument("--out", help="write the summary JSON here")
    parser.add_argument("--replay", action="store_true", help="Gate B: the replies a student would get (host)")
    args = parser.parse_args()
    cases = load(args.split)
    if args.load:
        stored = json.loads(Path(args.load).read_text(encoding="utf-8"))
        readings = {case["id"]: {**stored.get(case["id"], {}), "rule": rule(case)} for case in cases}
    else:
        key = api_key(args)
        if not key:
            print("no Ollalink key: set OLLALINK_API_KEY or pass --key-file")
            return 2
        readings = asyncio.run(ask(cases, key))
        if args.save:
            saved = {k: {f: v for f, v in r.items() if f != "rule"} for k, r in readings.items()}
            Path(args.save).write_text(json.dumps(saved), encoding="utf-8")
    if args.replay:
        asyncio.run(replay(cases, readings, args.tau_redirect, args.tau))
        return 0
    summary, ok = report(args, cases, readings)
    text = json.dumps(summary, ensure_ascii=False, indent=1)
    print(
        text if not args.sweep else json.dumps({"latency": summary["latency"], "chosen": summary["chosen"]}, indent=1)
    )
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
