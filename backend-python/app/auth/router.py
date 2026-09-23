from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status

from app.auth.dependencies import Principal, client_info, get_auth_service, get_principal
from app.auth.schemas import (
    AcceptedOut,
    AuthResult,
    ChangePasswordRequest,
    DeleteMeRequest,
    ForgotPasswordRequest,
    LoginRequest,
    ResendCodeRequest,
    ResetPasswordRequest,
    SessionOut,
    SettingsOut,
    SignupRequest,
    UpdateMeRequest,
    UpdateSettingsRequest,
    UserOut,
    VerifyEmailRequest,
)
from app.auth.service import AuthService, IssuedSession
from app.db.models import User

router = APIRouter(prefix="/v1", tags=["auth"])


def user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        email_verified=user.email_verified_at is not None,
        created_at=user.created_at,
    )


def auth_result(issued: IssuedSession) -> AuthResult:
    return AuthResult(user=user_out(issued.user), session=SessionOut(token=issued.token, expires_at=issued.expires_at))


@router.post("/auth/signup", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut)
async def signup(body: SignupRequest, request: Request, auth: AuthService = Depends(get_auth_service)):
    await auth.signup(body.email, body.password, body.display_name, client_info(request))
    return AcceptedOut()


@router.post("/auth/verify-email", response_model=AuthResult)
async def verify_email(body: VerifyEmailRequest, request: Request, auth: AuthService = Depends(get_auth_service)):
    return auth_result(await auth.verify_email(body.email, body.code, client_info(request)))


@router.post("/auth/login", response_model=AuthResult)
async def login(body: LoginRequest, request: Request, auth: AuthService = Depends(get_auth_service)):
    return auth_result(await auth.login(body.email, body.password, client_info(request)))


@router.post("/auth/resend-code", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut)
async def resend_code(body: ResendCodeRequest, request: Request, auth: AuthService = Depends(get_auth_service)):
    await auth.resend_code(body.email, body.purpose, client_info(request))
    return AcceptedOut()


@router.post("/auth/password/forgot", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut)
async def forgot_password(body: ForgotPasswordRequest, request: Request, auth: AuthService = Depends(get_auth_service)):
    await auth.forgot_password(body.email, client_info(request))
    return AcceptedOut()


@router.post("/auth/password/reset", response_model=AuthResult)
async def reset_password(body: ResetPasswordRequest, request: Request, auth: AuthService = Depends(get_auth_service)):
    return auth_result(await auth.reset_password(body.email, body.code, body.new_password, client_info(request)))


@router.post("/auth/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    principal: Principal = Depends(get_principal),
    auth: AuthService = Depends(get_auth_service),
):
    await auth.change_password(principal.user, principal.session.id, body.current_password, body.new_password)
    return Response(status_code=204)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)):
    await auth.logout(principal.session.id)
    return Response(status_code=204)


@router.post("/auth/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_others(principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)):
    await auth.revoke_other_sessions(principal.user.id, principal.session.id)
    return Response(status_code=204)


@router.get("/me", response_model=UserOut, tags=["me"])
async def get_me(principal: Principal = Depends(get_principal)):
    return user_out(principal.user)


@router.patch("/me", response_model=UserOut, tags=["me"])
async def update_me(
    body: UpdateMeRequest, principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)
):
    return user_out(await auth.update_profile(principal.user, body.display_name))


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, tags=["me"])
async def delete_me(
    body: DeleteMeRequest, principal: Principal = Depends(get_principal), auth: AuthService = Depends(get_auth_service)
):
    await auth.delete_account(principal.user, body.password)
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
