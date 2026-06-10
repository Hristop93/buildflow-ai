"""Auth endpoints — register, login, logout, me.

Email + password with bcrypt; a signed JWT is returned in an httpOnly cookie
(SPEC 2.4 / 8). GDPR consent is mandatory at registration (SPEC 5.1).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.base import get_db
from backend.db.models.app import User, _now
from backend.api import schemas
from backend.api.deps import get_current_user
from backend.api.security import (
    hash_password, verify_password, create_access_token,
    COOKIE_NAME, ACCESS_TOKEN_TTL,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_access_token(user_id),
        httponly=True,
        samesite="lax",
        secure=False,  # TODO: True once served over HTTPS (SPEC 8)
        max_age=int(ACCESS_TOKEN_TTL.total_seconds()),
        path="/",
    )


@router.post("/register", response_model=schemas.UserOut, status_code=201)
def register(payload: schemas.RegisterIn, response: Response, db: Session = Depends(get_db)):
    if not payload.gdpr_consent:
        raise HTTPException(400, "GDPR consent is required")
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(409, "email already registered")

    user = User(
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        company=payload.company,
        gdpr_consent_at=_now(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    _set_auth_cookie(response, user.id)
    return user


@router.post("/login", response_model=schemas.UserOut)
def login(payload: schemas.LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    # Verify even when the user is missing would be ideal to equalize timing;
    # kept simple here — a generic message avoids leaking which field was wrong.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid email or password")
    _set_auth_cookie(response, user.id)
    return user


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=schemas.UserOut)
def me(user: User = Depends(get_current_user)):
    return user
