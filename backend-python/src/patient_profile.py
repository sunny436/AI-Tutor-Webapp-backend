"""
patient_profile.py
------------------
Loads and saves the persistent patient profile, via Convex.

WHY THIS IS NOT A RETRIEVER
`retrieval/stubs.py::MedicalProfileRetriever` is the declared slot for
"structured medical profile", and it is deliberately left disabled. Retrievers
run inside the pipeline, which fires AFTER `asking_focus` resolves — far too
late to shape the questions being asked during gathering, which is the whole
point of having a profile. So this is a plain client called early in
`run_turn`, and the profile reaches the final answer through
`write_plan(profile=...)`, which already existed.

WHY ONE LOAD PER CONVERSATION, NOT PER TURN
The client round-trips `context` on every request and Convex already persists
it (`consults.state`), so once loaded the profile rides along for free.
`ConsultContext.profile_loaded` records that the attempt was made — separate
from "the profile is empty", because a genuinely empty profile must not cause
a refetch on every single turn.

ISOLATION
`user_id` is the subject of a VERIFIED Convex JWT (`server.require_user`),
never a client-supplied field. A service-key-only caller resolves to `""` and
both functions here refuse it — the same fail-closed guard
`UploadedReportsRetriever` uses before touching anyone's documents. The Convex
side is `internalQuery`/`internalMutation` behind a service-key-guarded route,
so there is no public function taking a `userId` that could be swapped.

FAILS SOFT, BOTH WAYS
An unconfigured or unreachable Convex means "no profile", never an error: a
consultation must not fail because long-term memory is down. A failed SAVE is
logged and swallowed for the same reason — losing a fact is bad, losing the
user's answer is worse.
"""

from __future__ import annotations

import asyncio
import json

import config
from src.consult.schema import PatientProfile

# Deliberately tighter than RETRIEVAL_TIMEOUT_S. This runs BEFORE the model
# call on the user's first turn, so it is latency the user feels directly,
# and an unavailable profile is survivable.
TIMEOUT_S = 4.0

_GET_PATH = "/backend/patient-profile"
_SAVE_PATH = "/backend/patient-profile/save"


def _configured() -> bool:
    return bool((config.CONVEX_SITE_URL or "").strip() and config.SERVICE_KEY)


def _load_sync(user_id: str) -> dict:
    """Blocking HTTP to Convex. The caller runs it off the event loop."""
    import httpx

    base = (config.CONVEX_SITE_URL or "").rstrip("/")
    response = httpx.post(
        f"{base}{_GET_PATH}",
        headers={
            "x-service-key": config.SERVICE_KEY,
            "content-type": "application/json",
        },
        json={"userId": user_id},
        timeout=TIMEOUT_S,
    )
    response.raise_for_status()
    body = response.json() or {}
    raw = body.get("profile")
    # The row stores JSON as a string, the same way `consults.state` does, so
    # the shape can change without a Convex migration.
    if isinstance(raw, str):
        raw = json.loads(raw or "{}")
    return raw if isinstance(raw, dict) else {}


def _save_sync(user_id: str, profile: PatientProfile) -> None:
    import httpx

    base = (config.CONVEX_SITE_URL or "").rstrip("/")
    response = httpx.post(
        f"{base}{_SAVE_PATH}",
        headers={
            "x-service-key": config.SERVICE_KEY,
            "content-type": "application/json",
        },
        json={"userId": user_id, "profile": profile.model_dump_json()},
        timeout=TIMEOUT_S,
    )
    response.raise_for_status()


async def load(user_id: str | None) -> PatientProfile:
    """This person's stored profile, or an empty one.

    Empty is returned for every failure mode — no verified user, feature off,
    Convex unconfigured, route missing, network error, unreadable body — so a
    backend deployed before the Convex side exists simply behaves as it does
    today, with the profile confined to the live conversation.
    """
    if not user_id or not config.PROFILE_ENABLED or not _configured():
        return PatientProfile()
    try:
        raw = await asyncio.to_thread(_load_sync, user_id)
    except Exception as error:  # noqa: BLE001 - never fail a consultation
        print(f"[profile] load failed: {error}")
        return PatientProfile()
    try:
        return PatientProfile.model_validate(raw)
    except Exception as error:  # noqa: BLE001
        print(f"[profile] stored profile is unreadable, ignoring it: {error}")
        return PatientProfile()


async def save(user_id: str | None, profile: PatientProfile) -> bool:
    """Persist the profile. Returns whether it was actually written.

    Callers should only reach this when `merge_profile` reported a change —
    most turns reveal nothing new and must not cost a round trip.
    """
    if not user_id or not config.PROFILE_ENABLED or not _configured():
        return False
    try:
        await asyncio.to_thread(_save_sync, user_id, profile)
        return True
    except Exception as error:  # noqa: BLE001
        # Swallowed on purpose: a fact that failed to persist is a smaller
        # loss than a consultation that 500s on the user mid-sentence.
        print(f"[profile] save failed: {error}")
        return False
