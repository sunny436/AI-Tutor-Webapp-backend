from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])

# Production runs the checkout /opt/aichat/app, with a RELEASE file at its root (written by
# deploy/server/update.sh on every deploy). It is read once, at start: the value is the commit
# this process started from.
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


@router.get("/health", summary="Liveness: the process is up, the release it runs, and whether files work")
async def health(request: Request) -> dict:
    worker = getattr(request.app.state, "file_worker", None)
    files = "available" if worker is not None and worker.available else "unavailable"
    return {"status": "ok", "release": RELEASE, "files": files}


@router.get("/ready", summary="Readiness: the database is reachable")
async def ready(request: Request) -> JSONResponse:
    database_ok = await request.app.state.db.ping()
    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={"status": "ok" if database_ok else "unavailable", "database": database_ok},
    )
