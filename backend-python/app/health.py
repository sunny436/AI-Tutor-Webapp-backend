from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: the process is up")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness: the database is reachable")
async def ready(request: Request) -> JSONResponse:
    database_ok = await request.app.state.db.ping()
    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={"status": "ok" if database_ok else "unavailable", "database": database_ok},
    )
