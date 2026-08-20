"""Password hashing and JWT validation for optional scholar accounts."""
from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.db import SessionLocal
from app.models.user import UserRecord
from app.schemas.auth import ScholarProfile

JWT_SECRET = os.getenv("ARB_JWT_SECRET", "development-only-change-me-before-deploying")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 12
_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def profile_for(user: UserRecord) -> ScholarProfile:
    return ScholarProfile(
        id=user.id, email=user.email, username=user.username, full_name=user.full_name,
        organization=user.organization, organization_id=user.organization_id,
        phone_number=user.phone_number, experience=user.experience, created_at=user.created_at,
    )


def create_access_token(user: UserRecord) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(user.id), "role": "scholar", "iat": now, "exp": now + timedelta(hours=JWT_EXPIRY_HOURS)},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def find_user(session: Session, identifier: str) -> UserRecord | None:
    value = identifier.strip().lower()
    return session.scalar(select(UserRecord).where(or_(UserRecord.email == value, UserRecord.username == value)))


def get_current_scholar(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> ScholarProfile:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Scholar login required")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload.get("sub", ""))
        if payload.get("role") != "scholar":
            raise ValueError("invalid role")
    except (jwt.InvalidTokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired login")

    session = SessionLocal()
    try:
        user = session.get(UserRecord, user_id)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Scholar account no longer exists")
        return profile_for(user)
    finally:
        session.close()
