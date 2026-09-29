import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import LoginSession, RateBucket, User
from .models.base import utc_now

router = APIRouter(prefix="/auth", tags=["auth"])
password_hasher = PasswordHasher()
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))
COOKIE = "alem_session"


def get_auth_db():
    # Separate from the endpoint's transaction: checking a session must not open it.
    with SessionLocal() as db:
        yield db


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def check_origin(request: Request) -> None:
    if request.headers.get("origin", "").rstrip("/") != str(
        settings.frontend_origin
    ).rstrip("/"):
        raise HTTPException(403, "Недопустимый источник запроса")


def consume_rate(db: Session, key: str, *, limit: int, seconds: int) -> None:
    now = utc_now()
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    expired = RateBucket.window_start <= now - timedelta(seconds=seconds)
    statement = insert(RateBucket).values(key=digest(key), window_start=now, count=1)
    statement = statement.on_conflict_do_update(
        index_elements=[RateBucket.key],
        set_={
            "window_start": case((expired, now), else_=RateBucket.window_start),
            "count": case((expired, 1), else_=RateBucket.count + 1),
        },
    ).returning(RateBucket.count)
    count = db.scalar(statement)
    db.commit()
    if count > limit:
        raise HTTPException(
            429,
            "Слишком много запросов. Повторите позже.",
            headers={"Retry-After": str(seconds)},
        )


@dataclass(frozen=True)
class Identity:
    id: UUID
    email: str
    name: str
    csrf_token: str


def current_user(request: Request, db: Session = Depends(get_auth_db)) -> Identity:
    token = request.cookies.get(COOKIE, "")
    row = (
        db.execute(
            select(LoginSession, User)
            .join(User, User.id == LoginSession.user_id)
            .where(
                LoginSession.token_hash == digest(token),
                LoginSession.expires_at > utc_now(),
                User.is_active.is_(True),
            )
        ).first()
        if token
        else None
    )
    if row is None:
        raise HTTPException(401, "Войдите в систему")
    session, user = row
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        if not secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), session.csrf_token
        ):
            raise HTTPException(403, "Обновите страницу: неверный CSRF-токен")
    return Identity(user.id, user.email, user.name, session.csrf_token)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_auth_db),
):
    check_origin(request)
    email = body.email.strip().casefold()
    address = request.client.host if request.client else "unknown"
    consume_rate(db, "login-ip:" + address, limit=30, seconds=900)
    consume_rate(db, "login-email:" + email, limit=10, seconds=900)
    user = db.scalar(select(User).where(User.email == email))
    try:
        password_hasher.verify(
            user.password_hash if user else dummy_hash, body.password
        )
        valid = user is not None and user.is_active
    except (VerificationError, InvalidHashError):
        valid = False
    if not valid:
        raise HTTPException(401, "Неверный email или пароль")
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash = password_hasher.hash(body.password)
    # Rotate a previous session on login and remove expired sessions.
    previous = request.cookies.get(COOKIE, "")
    db.execute(
        delete(LoginSession).where(
            (LoginSession.expires_at <= utc_now())
            | (LoginSession.token_hash == digest(previous))
        )
    )
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.add(
        LoginSession(
            token_hash=digest(token),
            user_id=user.id,
            csrf_token=csrf,
            expires_at=utc_now() + timedelta(hours=settings.session_hours),
        )
    )
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_hours * 3600,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"id": user.id, "email": user.email, "name": user.name, "csrf_token": csrf}


@router.get("/session")
def session(response: Response, user: Identity = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return user


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    user: Identity = Depends(current_user),
    db: Session = Depends(get_auth_db),
):
    db.execute(
        delete(LoginSession).where(
            LoginSession.token_hash == digest(request.cookies.get(COOKIE, ""))
        )
    )
    db.commit()
    response.delete_cookie(
        COOKIE, secure=settings.cookie_secure, httponly=True, samesite="lax", path="/"
    )
