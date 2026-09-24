from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])

# A production release is /opt/aichat/releases/<commit>/ with a RELEASE file at its root
# (written by deploy/server/release.sh). The path is taken from this module's own location,
# not from the /opt/aichat/current pointer, so the value is the release this process runs.
RELEASE_FILE = Path(__file__).resolve().parents[2] / "RELEASE"


def read_release(path: Path = RELEASE_FILE) -> str:
    """The commit this code was released as, or "development" outside a release."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("commit="):
                return line.split("=", 1)[1].strip() or "development"
    except OSError:
        pass
    return "development"


RELEASE = read_release()  # read once: a running process never changes release


@router.get("/health", summary="Liveness: the process is up, and the release it runs")
async def health() -> dict:
    return {"status": "ok", "release": RELEASE}


@router.get("/ready", summary="Readiness: the database is reachable")
async def ready(request: Request) -> JSONResponse:
    database_ok = await request.app.state.db.ping()
    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={"status": "ok" if database_ok else "unavailable", "database": database_ok},
    )
