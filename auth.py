"""Officer accounts, password hashing, login lock-out and permissions.

Passwords are never stored: only a salted scrypt hash (PBKDF2 if scrypt is unavailable).
After MAX_FAILED wrong passwords an account is locked for LOCK_MINUTES.
"""
import datetime as dt
import hashlib
import hmac
import os
import re

import database

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
MIN_PASSWORD = 8
MAX_FAILED = 5
LOCK_MINUTES = 5
SESSION_MINUTES = 30
CREW_ID_RE = re.compile(r"^[A-Za-z0-9\-]{2,12}$")
PERMISSIONS = {
    "crew": {"crew_work"},                       # field crews see and update only their own jobs
    "officer": {"view", "review", "resolve"},
    "admin": {"view", "review", "resolve", "manage_users", "reset", "seed", "export", "audit"},
}
GENERIC_ERROR = "Wrong username or password."


class AuthError(Exception):
    pass


def hash_password(password, salt=None):
    salt = salt or os.urandom(16)
    data = password.encode("utf-8")
    if hasattr(hashlib, "scrypt"):
        n, r, p = 2 ** 14, 8, 1
        digest = hashlib.scrypt(data, salt=salt, n=n, r=r, p=p, dklen=32)
        return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"
    iterations = 600_000
    digest = hashlib.pbkdf2_hmac("sha256", data, salt, iterations, dklen=32)
    return f"pbkdf2${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        parts = stored.split("$")
        data = password.encode("utf-8")
        if parts[0] == "scrypt":
            _, n, r, p, salt, digest = parts
            candidate = hashlib.scrypt(data, salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        elif parts[0] == "pbkdf2":
            _, iterations, salt, digest = parts
            candidate = hashlib.pbkdf2_hmac("sha256", data, bytes.fromhex(salt), int(iterations), dklen=32)
        else:
            return False
        return hmac.compare_digest(candidate.hex(), digest)
    except (ValueError, TypeError):
        return False


_DUMMY = None


def _dummy_hash():
    """Hash checked when the username does not exist, so a missing user takes as long as a wrong password."""
    global _DUMMY
    if _DUMMY is None:
        _DUMMY = hash_password("not-a-real-password")
    return _DUMMY


def create_user(conn, username, password, role="officer", now=None, crew_id=None):
    username = (username or "").strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError("Username must be 3 to 32 characters: letters, numbers, dot, dash or underscore")
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
    if password.lower() == username:
        raise ValueError("Password must not be the same as the username")
    if role not in PERMISSIONS:
        raise ValueError(f"Role must be one of {sorted(PERMISSIONS)}")
    if role == "crew" and not CREW_ID_RE.match(crew_id or ""):
        raise ValueError("A crew account needs a crew id such as PW-1")
    if role != "crew" and crew_id:
        raise ValueError("Only crew accounts have a crew id")
    if database.get_user(conn, username):
        raise ValueError("That username already exists")
    database.add_user(conn, username, hash_password(password), role, (now or dt.datetime.now()).isoformat(timespec="seconds"),
                      crew_id if role == "crew" else None)


def set_password(conn, username, password, now=None):
    """Choose a new password for an existing account. Also unlocks it and makes it active."""
    username = (username or "").strip().lower()
    if not database.get_user(conn, username):
        raise ValueError("No such account")
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"Password must be at least {MIN_PASSWORD} characters")
    if password.lower() == username:
        raise ValueError("Password must not be the same as the username")
    database.update_user(conn, username, password_hash=hash_password(password), failed_attempts=0, locked_until=None, active=1)
    database.log_audit(conn, (now or dt.datetime.now()).isoformat(timespec="seconds"), username, "password_reset")


def authenticate(conn, username, password, now=None):
    """Return the user (without the password hash) or raise AuthError."""
    now = now or dt.datetime.now()
    username = (username or "").strip().lower()
    user = database.get_user(conn, username) if username else None
    if user and user["locked_until"] and now < dt.datetime.fromisoformat(user["locked_until"]):
        raise AuthError(f"Too many failed attempts. Try again in {LOCK_MINUTES} minutes.")
    good = verify_password(password or "", user["password_hash"] if user else _dummy_hash())
    if not user or not good or not user["active"]:
        if user:
            failed = user["failed_attempts"] + 1
            if failed >= MAX_FAILED:
                database.update_user(conn, username, failed_attempts=0,
                                     locked_until=(now + dt.timedelta(minutes=LOCK_MINUTES)).isoformat(timespec="seconds"))
            else:
                database.update_user(conn, username, failed_attempts=failed)
        raise AuthError(GENERIC_ERROR)
    database.update_user(conn, username, failed_attempts=0, locked_until=None)
    return {k: v for k, v in user.items() if k not in ("password_hash", "failed_attempts", "locked_until")}


def can(user, permission):
    return bool(user) and permission in PERMISSIONS.get(user.get("role"), set())


def require(user, permission):
    if not can(user, permission):
        raise PermissionError(f"Your role is not allowed to do this ({permission})")


def session_expired(last_active_iso, now=None):
    now = now or dt.datetime.now()
    return now - dt.datetime.fromisoformat(last_active_iso) > dt.timedelta(minutes=SESSION_MINUTES)
