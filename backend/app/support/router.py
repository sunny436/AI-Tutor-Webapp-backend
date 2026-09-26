"""POST /v1/support/requests: a signed-in student asks for help or reports a problem.

- **Limits** per account: 5 an hour, 20 a day, and at most 30 open at once (429).
- **Idempotent:** the client picks `requestId`; sending it again (a retry after a network
  error) returns the request already made (200) instead of making another.
- **Forwarded** to SUPPORT_EMAIL through the email outbox, in the same transaction, so a slow
  mail provider never fails the request. Without SUPPORT_EMAIL requests are only stored.
- Kept until the account is deleted.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import Principal, get_principal
from app.auth.devices import device_label
from app.db.models import SupportRequest
from app.db.session import get_session
from app.errors import AppError, RateLimited
from app.health import RELEASE
from app.notifications.emails import support_forward
from app.notifications.outbox import SUPPORT_FORWARD, queue_email
from app.support.schemas import SupportRequestIn, SupportRequestOut

router = APIRouter(prefix="/v1/support", tags=["support"])

PER_HOUR = 5
PER_DAY = 20
MAX_OPEN = 30
FORWARD_LIFETIME = timedelta(days=7)


class TooManyOpenRequests(AppError):
    status_code, code, message = 429, "too_many_open_requests", "You have many open requests. Please wait for replies."


def request_out(row: SupportRequest) -> SupportRequestOut:
    return SupportRequestOut(
        id=row.id,
        request_id=row.client_request_id,
        kind=row.kind,
        subject=row.subject,
        status=row.status,
        created_at=row.created_at,
    )


async def _count(db: AsyncSession, *conditions) -> int:
    return await db.scalar(select(func.count()).select_from(SupportRequest).where(*conditions)) or 0


@router.post(
    "/requests",
    response_model=SupportRequestOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": SupportRequestOut, "description": "The same requestId was already sent."}},
)
async def create_support_request(
    body: SupportRequestIn,
    request: Request,
    response: Response,
    principal: Principal = Depends(get_principal),
    db: AsyncSession = Depends(get_session),
):
    user = principal.user
    user_id, user_email = user.id, user.email
    existing = await db.scalar(
        select(SupportRequest).where(
            SupportRequest.user_id == user_id, SupportRequest.client_request_id == body.request_id
        )
    )
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return request_out(existing)

    now = datetime.now(UTC)
    mine = SupportRequest.user_id == user_id
    if await _count(db, mine, SupportRequest.created_at > now - timedelta(hours=1)) >= PER_HOUR:
        raise RateLimited()
    if await _count(db, mine, SupportRequest.created_at > now - timedelta(days=1)) >= PER_DAY:
        raise RateLimited()
    if await _count(db, mine, SupportRequest.status == "open") >= MAX_OPEN:
        raise TooManyOpenRequests()

    context = {"page": body.page, "release": RELEASE, "device": device_label(request.headers.get("user-agent"))}
    inserted = await db.execute(
        insert(SupportRequest)
        .values(
            user_id=user_id,
            client_request_id=body.request_id,
            kind=body.kind,
            subject=body.subject,
            message=body.message,
            context=context,
        )
        .on_conflict_do_nothing(index_elements=[SupportRequest.user_id, SupportRequest.client_request_id])
        .returning(SupportRequest.id)
    )
    row_id = inserted.scalar()
    if row_id is None:  # the same request, sent twice at once: the other one made it
        await db.rollback()
        response.status_code = status.HTTP_200_OK
    else:
        settings = request.app.state.settings
        if settings.support_email:
            subject, text = support_forward(
                settings.app_name,
                body.kind,
                body.subject,
                body.message,
                user_email,
                str(row_id),
                ", ".join(f"{key}={value}" for key, value in context.items() if value),
            )
            await queue_email(
                db,
                kind=SUPPORT_FORWARD,
                to=settings.support_email,
                subject=subject,
                body=text,
                send_before=now + FORWARD_LIFETIME,
                user_id=user_id,
            )
        await db.commit()
    row = await db.scalar(
        select(SupportRequest).where(
            SupportRequest.user_id == user_id, SupportRequest.client_request_id == body.request_id
        )
    )
    return request_out(row)
