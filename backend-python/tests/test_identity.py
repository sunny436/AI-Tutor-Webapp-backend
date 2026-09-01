r"""
Who the backend thinks is asking. Deterministic — a real RS256 key, no network.

THE BUG THIS PINS, found on 2026-09-01 by looking at the `patientProfiles`
table after a consultation in which the user had given their age, their
diabetes and their metformin. The table was EMPTY.

Convex Auth puts two ids in the JWT subject, joined by "|":

    "m572jrdvnt10jr7d25e9nhke098dg7rv|js7cfyj9z922v5j2f7kbbkfhkd8dhhhb"
     \______________ user ___________/ \____________ session ________/

`verify_token` returned the whole thing as the user id, and that is wrong in
two independent ways:

  1. It is not a `v.id("users")`. Convex answered every `patientProfile.get`
     and `patientProfile.upsert` with `ArgumentValidationError`; `http.ts`
     caught it and replied 200 with `{profile: null}` / `{saved: false}`;
     `patient_profile.py` fails soft by design and logged nothing. So the
     patient profile was never once loaded or saved, silently, for everyone.
  2. The session half changes on every login, so `user_documents`' Chroma
     filter — which only needs a stable opaque string — stopped matching a
     user's own uploaded reports as soon as they signed out and back in.

Convex Auth's own `getAuthUserId` is `identity.subject.split("|")[0]`, so the
fix is to do the same.

    python tests/test_identity.py
"""

from __future__ import annotations

import sys
import time
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


import jwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

import config  # noqa: E402
import server  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f' - {detail}' if detail else ''}")


# A real key pair, generated here. `_signing_key` is patched to hand back the
# public half, so `verify_token` runs its genuine signature check — this is not
# a stub of the function under test, only of the JWKS fetch it would do.
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_private = _key
_public = _key.public_key()
server._signing_key = lambda token: _public  # type: ignore[assignment]

USER_ID = "m572jrdvnt10jr7d25e9nhke098dg7rv"
SESSION_ID = "js7cfyj9z922v5j2f7kbbkfhkd8dhhhb"


def mint(subject: str, **overrides) -> str:
    claims = {
        "sub": subject,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "aud": config.CONVEX_AUDIENCE,
        "iss": config.CONVEX_SITE_URL,
    }
    claims.update(overrides)
    return jwt.encode(claims, _private, algorithm="RS256")


# --- the fix itself --------------------------------------------------------
check(
    "the composite subject resolves to the USER id alone",
    server.verify_token(mint(f"{USER_ID}|{SESSION_ID}")) == USER_ID,
    server.verify_token(mint(f"{USER_ID}|{SESSION_ID}")),
)

check(
    "the session id is not part of the identity",
    SESSION_ID not in server.verify_token(mint(f"{USER_ID}|{SESSION_ID}")),
)

# THE POINT OF THE WHOLE FIX. Two logins by the same person differ only in the
# session half, and they must resolve to one identity — otherwise the profile,
# the memory and the uploaded reports all belong to a stranger after signing
# back in.
_first = server.verify_token(mint(f"{USER_ID}|session-one"))
_second = server.verify_token(mint(f"{USER_ID}|session-two"))
check(
    "two sessions for one person are the same identity",
    _first == _second == USER_ID,
    f"{_first!r} vs {_second!r}",
)

# ...and two different people still are not.
check(
    "two different people are still different identities",
    server.verify_token(mint(f"{USER_ID}|s1"))
    != server.verify_token(mint(f"m57bzzty4xxsv62ewrw59hjxd58dgnk6|s1")),
)

check(
    "a subject with no divider is returned whole",
    server.verify_token(mint("plain-subject-no-divider")) == "plain-subject-no-divider",
    server.verify_token(mint("plain-subject-no-divider")),
)


# --- nothing about rejection may have loosened -----------------------------
# `verify_token` is the only thing that establishes who is asking, so the
# negatives matter more than the positives.
check("an empty token is rejected", server.verify_token("") == "")
check("a garbage token is rejected", server.verify_token("not.a.jwt") == "")

_expired = mint(f"{USER_ID}|{SESSION_ID}", exp=int(time.time()) - 60)
check("an expired token is rejected", server.verify_token(_expired) == "", "expired")

_wrong_aud = mint(f"{USER_ID}|{SESSION_ID}", aud="somebody-else")
check("a token for another audience is rejected", server.verify_token(_wrong_aud) == "")

_other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_forged = jwt.encode(
    {
        "sub": f"{USER_ID}|{SESSION_ID}",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "aud": config.CONVEX_AUDIENCE,
    },
    _other_key,
    algorithm="RS256",
)
check(
    "a token signed by the wrong key is rejected",
    server.verify_token(_forged) == "",
    "forged",
)

# A subject that is empty, or is only the divider, must not become a truthy
# user id — `patient_profile.load`/`save` and `user_documents.search` all gate
# on `if not user_id`, and "" is what makes that gate close.
check("an empty subject stays empty", server.verify_token(mint("")) == "")
check("a bare divider stays empty", server.verify_token(mint("|abc")) == "")


passed = sum(1 for _, ok, _ in results if ok)
print(f"\n===== identity: {passed}/{len(results)} passed =====")
if passed != len(results):
    print("\nFailing:")
    for name, ok, detail in results:
        if not ok:
            print(f"  - {name}{f' [{detail}]' if detail else ''}")
sys.exit(0 if passed == len(results) else 1)
