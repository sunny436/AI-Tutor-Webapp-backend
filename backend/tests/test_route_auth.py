"""Every route needs a session unless it is on the public list below — for routes added later too.

The routes are read from the application's own OpenAPI description (the same one exported to
docs/openapi.json), not listed by hand, so a new endpoint that forgets its auth dependency fails
here instead of shipping open. A route hidden from that description would escape this check,
so hiding one is refused too. Making a route public is a decision recorded in PUBLIC, next to
the reason.
"""

import re
import uuid
from pathlib import Path

PUBLIC = {
    ("GET", "/health"): "liveness probe",
    ("GET", "/ready"): "readiness probe",
    ("POST", "/v1/auth/signup"): "creating an account",
    ("POST", "/v1/auth/verify-email"): "signs in",
    ("POST", "/v1/auth/login"): "signs in",
    ("POST", "/v1/auth/resend-code"): "before signing in",
    ("POST", "/v1/auth/password/forgot"): "before signing in",
    ("POST", "/v1/auth/password/reset"): "signs in",
    ("GET", "/v1/catalog/academic"): "the same reference data for everyone, needed before sign-up is complete",
}

PARAMETER = re.compile(r"\{[^}]+\}")


METHODS = ("get", "post", "put", "patch", "delete")
APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _routes(app) -> list[tuple[str, str]]:
    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in METHODS
        if method in operations
    ]


def test_no_route_is_hidden_from_the_api_description():
    hidden = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if "include_in_schema=False" in path.read_text(encoding="utf-8")
    ]
    assert not hidden, f"routes hidden from OpenAPI escape the auth check: {hidden}"


def test_the_public_list_names_only_routes_that_exist(app):
    stale = set(PUBLIC) - set(_routes(app))
    assert not stale, f"PUBLIC lists routes that no longer exist: {sorted(stale)}"


async def test_every_non_public_route_rejects_a_request_without_a_session(app, client):
    checked = 0
    for method, path in _routes(app):
        if (method, path) in PUBLIC:
            continue
        url = PARAMETER.sub(str(uuid.uuid4()), path)
        body = {} if method in {"POST", "PUT", "PATCH", "DELETE"} else None
        for headers in ({}, {"Authorization": "Bearer not-a-real-session"}):
            response = await client.request(method, url, json=body, headers=headers)
            assert response.status_code == 401, (method, path, headers, response.status_code, response.text)
            assert response.json()["error"]["code"] == "unauthorized", (method, path)
        checked += 1
    assert checked >= 15, f"only {checked} protected routes found; is the router wired?"
