"""
clinical/episodes.py
--------------------
One health concern = one longitudinal episode.

WHY THIS EXISTS
`ConsultContext` has ONE `problem` and ONE `condition`. A person with acidity,
knee pain and insomnia therefore had all three collapsed into whichever they
mentioned last, and the "new complaint" branch in `graph.run_turn` threw the
previous reasoning away to start again — so switching topic and coming back
meant re-answering everything. Episodes let several concerns be open at once
and let the conversation move between them without losing state.

An episode is NOT a conversation. A conversation (`chatSessions.sessionId`) is
one sitting; an episode is one problem, and it spans as many sittings as the
problem lasts. Someone's acidity episode may be touched in March, again in
July, and be the reason a question in November is worth asking.

MATCHING IS DETERMINISTIC FIRST. `match(...)` decides by concept overlap before
anything asks a model: the clinically wrong outcome here is a SPLIT episode
(the same problem recorded twice, so the history looks empty), and a cheap
string match catches the common case — "acidity" again is the acidity episode.
The caller may pass `assist=` to let the reasoning stage break a genuine tie;
nothing here requires it.
"""

from __future__ import annotations

import datetime as _dt
import re
import uuid

from src.consult.schema import Episode

# How many episodes ride on the context. Bounded for the reason every list in
# `state.py` is bounded: this is round-tripped on every request and persisted
# per user. Oldest-touched are dropped first, so an active problem outlives a
# stale one.
MAX_EPISODES = 12

# Below this, two problems are different problems.
#
# The measure is the OVERLAP COEFFICIENT — shared concepts over the SMALLER
# set — not Jaccard. Jaccard divides by the union, so the filler people
# actually type inflates the denominator and buries the match: "acidity wapas
# aa gayi" against an episode named "Acidity" scored 1/4 = 0.25 and opened a
# SECOND acidity episode, which is the exact failure this module exists to
# prevent (a recurrence arriving with no history behind it). The same pair
# scores 1/1 here.
#
# It stays safe because `concepts()` has already removed the words that would
# make everything match: "pain" is a stop word, so "Knee pain" and "Chest
# pain" share nothing and score 0.
MATCH_THRESHOLD = 0.5

_STOP = {
    "the", "a", "an", "and", "or", "of", "in", "on", "my", "me", "i", "with",
    "problem", "issue", "trouble", "pain", "ka", "ki", "ke", "hai", "ho",
    "raha", "rahi", "mujhe", "mera", "meri",
}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def concepts(text: str) -> list[str]:
    """The content words of a problem name, for matching.

    "pain" is a stop word ON PURPOSE. It appears in knee pain, chest pain and
    period pain, so keeping it would make every painful thing one episode —
    the exact merge failure this module exists to avoid. The body part is what
    discriminates, and that is what survives.
    """
    words = re.findall(r"[a-z0-9ऀ-ॿ]+", (text or "").lower())
    return sorted({w for w in words if len(w) > 2 and w not in _STOP})


def _overlap(a: list[str], b: list[str]) -> float:
    """Shared concepts over the SMALLER set. 0.0 when either side is empty.

    See MATCH_THRESHOLD for why this is not Jaccard.
    """
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / min(len(sa), len(sb))


def match(episodes: list[Episode], problem: str) -> tuple[Episode | None, float]:
    """The open episode this problem belongs to, and how confident that is.

    Prefers an OPEN episode over a resolved one at the same score: someone
    saying "my acidity is back" is reopening the acidity they had, and
    matching the resolved record is how a recurrence gets filed as a new
    problem with no history behind it.
    """
    wanted = concepts(problem)
    if not wanted or not episodes:
        return None, 0.0
    ranked = []
    for ep in episodes:
        score = max(
            _overlap(wanted, ep.canonical_concepts),
            _overlap(wanted, concepts(ep.problem_name)),
        )
        # A tiny nudge, not a tie-break that can beat a real difference in
        # concept overlap.
        if ep.status == "active":
            score += 0.01
        ranked.append((score, ep))
    ranked.sort(key=lambda pair: pair[0], reverse=True)
    best_score, best = ranked[0]
    return (best, best_score) if best_score >= MATCH_THRESHOLD else (None, best_score)


def open_episode(problem: str, condition: str = "") -> Episode:
    """Start a new episode for a problem nothing else covers."""
    name = (condition or problem or "").strip()[:80] or "unnamed concern"
    return Episode(
        episode_id=uuid.uuid4().hex[:12],
        problem_name=name,
        canonical_concepts=concepts(f"{problem} {condition}"),
        status="active",
        first_seen_at=_now(),
        last_discussed_at=_now(),
    )


def touch(episode: Episode) -> Episode:
    """Mark an episode as discussed now, and reopen it if it had resolved.

    A resolved problem the person raises again is a RECURRENCE, not a new
    problem: the history of what was tried and whether it helped is exactly
    what makes the next answer better than the first one.
    """
    episode.last_discussed_at = _now()
    if episode.status == "resolved":
        episode.status = "active"
        episode.recurrences += 1
    return episode


def select(
    episodes: list[Episode], problem: str, condition: str = ""
) -> tuple[list[Episode], Episode, bool]:
    """The episode this turn is about. Returns (episodes, active, is_new).

    Always returns an episode — a turn is always about something — so callers
    never branch on None. `is_new` is what tells the caller whether to greet
    the problem as fresh or to carry the previous reasoning forward.
    """
    found, _score = match(episodes, f"{problem} {condition}")
    if found is not None:
        return episodes, touch(found), False

    fresh = open_episode(problem, condition)
    episodes = [*episodes, fresh]
    if len(episodes) > MAX_EPISODES:
        # Drop the least recently discussed, never the one in hand.
        episodes = sorted(episodes, key=lambda e: e.last_discussed_at)[-MAX_EPISODES:]
        if fresh not in episodes:
            episodes = [*episodes[1:], fresh]
    return episodes, fresh, True


def get(episodes: list[Episode], episode_id: str) -> Episode | None:
    return next((e for e in episodes if e.episode_id == episode_id), None)


def render(episodes: list[Episode], active_id: str = "") -> str:
    """The other open problems, as one line for a prompt. "" when there are none.

    Deliberately terse and deliberately NOT the active episode: this exists so
    a model knows the person also has a knee problem when they mention their
    knee, not so it can recite a case file back at them.
    """
    others = [
        e for e in episodes
        if e.episode_id != active_id and e.status == "active"
    ]
    if not others:
        return ""
    parts = [
        f"{e.problem_name} (last discussed {e.last_discussed_at})" for e in others[-4:]
    ]
    return "Also open, not the current topic: " + "; ".join(parts)
