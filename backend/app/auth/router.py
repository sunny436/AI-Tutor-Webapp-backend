from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.auth import avatar as avatars
from app.auth.dependencies import Principal, get_auth_service, get_principal
from app.auth.devices import device_label, masked_ip
from app.auth.schemas import (
    AcceptedOut,
    AvatarOut,
    DeleteMeRequest,
    EmailChangeRequest,
    EmailConfirmRequest,
    SessionInfo,
    SessionListOut,
    SettingsOut,
    UpdateMeRequest,
    UpdateProfileRequest,
    UpdateSettingsRequest,
    UserOut,
)
from app.auth.service import AuthService
from app.db.models import User
from app.errors import VersionConflict, error_body
from app.settings import Settings

router = APIRouter(prefix="/v1", tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name or None,  # Better Auth stores "" for "no name"
        email_verified=user.email_verified,
        created_at=user.created_at,
        profile_version=user.profile_version,
        timezone=user.timezone,
        avatar=AvatarOut(url=f"/v1/me/avatar?v={user.avatar_hash}") if user.avatar_hash else None,
        password_changed_at=user.password_changed_at,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)):
    await auth.logout(principal.session.id)
    return Response(status_code=204)


@router.post("/auth/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_others(principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)):
    await auth.revoke_other_sessions(principal.user.id, principal.session.id)
    return Response(status_code=204)


@router.get("/auth/sessions", response_model=SessionListOut)
async def list_sessions(principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)):
    """The account's signed-in devices, most recently used first. Only a device label and a
    masked network leave the server, never the raw IP address or user agent."""
    rows = await auth.list_sessions(principal.user.id)
    return SessionListOut(
        items=[
            SessionInfo(
                id=row.id,
                current=row.id == principal.session.id,
                device=device_label(row.user_agent),
                ip_masked=masked_ip(row.ip),
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.expires_at,
            )
            for row in rows
        ]
    )


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    auth: AuthService = Depends(get_auth_service),
):
    """Signs one other device out. The current device signs out with POST /v1/auth/logout."""
    await auth.revoke_session(principal.user.id, session_id, principal.session.id)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut, tags=["me"])
async def get_me(principal: Principal = Depends(get_principal)):
    return user_out(principal.user)


@router.patch("/me", response_model=UserOut, tags=["me"], deprecated=True)
async def update_me(
    body: UpdateMeRequest, principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)
):
    """Superseded by PATCH /v1/me/profile, which is versioned; kept for existing clients."""
    return user_out(await auth.update_profile(principal.user, body.display_name))


@router.patch("/me/profile", response_model=UserOut, tags=["me"])
async def update_my_profile(
    body: UpdateProfileRequest,
    principal: Principal = Depends(get_principal),
    auth: AuthService = Depends(get_auth_service),
):
    """Versioned edit of the identity profile: `{version, set, reset}` (docs/api-contract.md).
    A stale version answers 409 version_conflict with the current profile in `error.current`."""
    changes = body.set.model_dump(by_alias=True, include=body.set.model_fields_set)
    try:
        user = await auth.update_profile_versioned(principal.user, body.version, changes, list(body.reset))
    except VersionConflict:
        raise VersionConflict(current=user_out(principal.user).model_dump(mode="json", by_alias=True)) from None
    return user_out(user)


# The photo is served by the API (through the web app's proxy) to its signed-in owner only;
# there is no public bucket.
AVATAR_BODY = {
    "requestBody": {
        "required": True,
        "content": {kind: {"schema": {"type": "string", "format": "binary"}} for kind in avatars.ACCEPTED},
        # The default AVATAR_MAX_BYTES; the web app's proxy caps uploads at this.
        "x-max-bytes": Settings.model_fields["avatar_max_bytes"].default,
    }
}
AVATAR_RESPONSE = {200: {"content": {avatars.STORED_TYPE: {"schema": {"type": "string", "format": "binary"}}}}}
IMMUTABLE = "private, max-age=31536000, immutable"


@router.put("/me/avatar", response_model=UserOut, tags=["me"], openapi_extra=AVATAR_BODY)
async def put_my_avatar(
    request: Request, principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)
):
    """Upload a profile photo as the raw request body (JPEG, PNG or WebP, up to
    AVATAR_MAX_BYTES). It is stored as a 256 px WebP without metadata (app/auth/avatar.py)."""
    await auth.throttle_avatar(principal.user)
    processed = await avatars.process_async(
        await request.body(),
        request.headers.get("content-type", ""),
        request.app.state.settings.avatar_max_bytes,
        request.app.state.avatar_decodes,
    )
    return user_out(await auth.set_avatar(principal.user, processed))


@router.delete("/me/avatar", response_model=UserOut, tags=["me"])
async def delete_my_avatar(
    principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)
):
    return user_out(await auth.remove_avatar(principal.user))


@router.get("/me/avatar", response_class=Response, responses=AVATAR_RESPONSE, tags=["me"])
async def get_my_avatar(
    v: str = Query(pattern=r"^[0-9a-f]{32}$", description="The hash in `avatar.url` from GET /v1/me."),
    principal: Principal = Depends(get_principal),
    auth: AuthService = Depends(get_auth_service),
):
    """Content-addressed: cacheable forever only when `v` names the current photo. Any other
    `v` (a replaced or removed photo) is a 404 that is never cached, so an old URL can never
    be served new bytes."""
    row = await auth.get_avatar(principal.user.id)
    if row is None or row.hash != v:
        return JSONResponse(
            status_code=404,
            content=error_body("not_found", "Not found."),
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=row.image,
        media_type=row.content_type,
        headers={"Cache-Control": IMMUTABLE, "ETag": f'"{row.hash}"', "X-Content-Type-Options": "nosniff"},
    )


@router.post("/me/email/change", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut, tags=["me"])
async def request_email_change(
    body: EmailChangeRequest,
    principal: Principal = Depends(get_principal),
    auth: AuthService = Depends(get_auth_service),
):
    """Sends a code to the new address. Always 202, whether or not the address is free. Needs the
    password, or for an account without one a sign-in within 15 minutes (409 reauth_required)."""
    await auth.request_email_change(principal.user, principal.session, body.new_email, body.password)
    return AcceptedOut()


@router.post("/me/email/confirm", response_model=UserOut, tags=["me"])
async def confirm_email_change(
    body: EmailConfirmRequest,
    principal: Principal = Depends(get_principal),
    auth: AuthService = Depends(get_auth_service),
):
    """Moves the account to the new address and signs out every other device."""
    return user_out(await auth.confirm_email_change(principal.user, principal.session.id, body.new_email, body.code))


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, tags=["me"])
async def delete_me(
    body: DeleteMeRequest, principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)
):
    """Deletes the account and all of its data. Needs the password, or for an account without
    one a sign-in within 15 minutes (409 reauth_required)."""
    await auth.delete_account(principal.user, principal.session, body.password)
    return Response(status_code=204)


@router.get("/me/settings", response_model=SettingsOut, tags=["me"])
async def get_my_settings(principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)):
    row = await auth.get_settings(principal.user.id)
    return SettingsOut(preferences=row.preferences if row else {}, updated_at=row.updated_at if row else None)


@router.patch("/me/settings", response_model=SettingsOut, tags=["me"])
async def update_my_settings(
    body: UpdateSettingsRequest,
    principal: Principal = Depends(get_principal),
    auth: AuthService = Depends(get_auth_service),
):
    row = await auth.update_settings(principal.user.id, body.preferences)
    return SettingsOut(preferences=row.preferences, updated_at=row.updated_at)
