"""Authentication: salted scrypt password hashes, opaque session tokens with expiry, roles.

* Passwords are never stored or compared in plaintext (the prototype did both).
* Only a SHA-256 of the session token is stored, so a leaked database cannot be replayed.
* Every page/API call resolves the token with ``AuthService.authenticate`` (session guard).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from .db import Database, utcnow

ROLES = ("student", "instructor")
MIN_PASSWORD_LENGTH = 8

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


class AuthError(Exception):
    """Login failed, or a session is missing, unknown or expired."""


class PermissionDenied(Exception):
    """The authenticated user may not perform this action."""


def hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    b64 = base64.b64encode
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(hash_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    display_name: str
    role: str

    @property
    def is_instructor(self) -> bool:
        return self.role == "instructor"


@dataclass(frozen=True)
class Session:
    token: str
    principal: Principal
    expires_at: datetime


# A throwaway hash checked for unknown usernames so both failure paths cost the same time.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class AuthService:
    def __init__(self, db: Database, *, ttl_minutes: int = 60, clock: Callable[[], datetime] = utcnow) -> None:
        self.db = db
        self.ttl = timedelta(minutes=ttl_minutes)
        self.clock = clock

    def register(self, username: str, password: str, *, role: str = "student", display_name: str = "") -> Principal:
        username = username.strip().lower()
        if not username:
            raise ValueError("username is required")
        if role not in ROLES:
            raise ValueError(f"role must be one of {ROLES}")
        if self.db.user_by_username(username) is not None:
            raise ValueError(f"username {username!r} is taken")
        uid = self.db.insert_user(username, display_name or username, role, hash_password(password))
        return Principal(uid, username, display_name or username, role)

    def login(self, username: str, password: str) -> Session:
        row = self.db.user_by_username(username.strip().lower())
        if row is None:
            verify_password(password, _DUMMY_HASH)
            raise AuthError("invalid username or password")
        if not verify_password(password, row["password_hash"]):
            raise AuthError("invalid username or password")
        now = self.clock()
        token = secrets.token_urlsafe(32)
        self.db.insert_session(_token_hash(token), row["id"], now, now + self.ttl)
        return Session(token, self._principal(row), now + self.ttl)

    def authenticate(self, token: str | None) -> Principal:
        if not token:
            raise AuthError("not logged in")
        th = _token_hash(token)
        row = self.db.session(th)
        if row is None:
            raise AuthError("unknown session")
        if datetime.fromisoformat(row["expires_at"]) <= self.clock():
            self.db.delete_session(th)
            raise AuthError("session expired, please log in again")
        user = self.db.user_by_id(row["user_id"])
        if user is None:
            raise AuthError("unknown user")
        return self._principal(user)

    def logout(self, token: str | None) -> None:
        if token:
            self.db.delete_session(_token_hash(token))

    @staticmethod
    def _principal(row) -> Principal:
        return Principal(int(row["id"]), row["username"], row["display_name"], row["role"])


def require_role(principal: Principal, role: str) -> None:
    if principal.role != role:
        raise PermissionDenied(f"requires role {role!r}")
