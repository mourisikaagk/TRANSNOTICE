from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Mapping

from werkzeug.security import check_password_hash, generate_password_hash

from timeutil import to_iso

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
ROUTE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,11}$")
HASH_METHOD = "pbkdf2:sha256:600000"
DUMMY_HASH = generate_password_hash("not-a-real-password", method="pbkdf2:sha256:600000")
MIN_PASSWORD = 8
MAX_ROUTES = 20
WINDOW = timedelta(minutes=10)

_failures: dict[str, list[datetime]] = {}
_lock = threading.Lock()


class AccountError(Exception):
    pass


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def clean_routes(values, limit: int = MAX_ROUTES) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        route = str(value).strip().upper()
        if ROUTE_RE.match(route) and route not in seen:
            seen.append(route)
    return seen[:limit]


def _recent_failures(key: str, now: datetime) -> list[datetime]:
    with _lock:
        kept = [t for t in _failures.get(key, []) if now - t < WINDOW]
        _failures[key] = kept
        return kept


def reset_throttle() -> None:
    with _lock:
        _failures.clear()


def sign_up(conn: sqlite3.Connection, email: str, password: str, now: datetime) -> int:
    email = normalize_email(email)
    if not EMAIL_RE.match(email):
        raise AccountError("Enter a valid e-mail address.")
    if len(password) < MIN_PASSWORD:
        raise AccountError(f"Use a password of at least {MIN_PASSWORD} characters.")
    if len(password) > 128:
        raise AccountError("The password is too long (128 characters at most).")
    try:
        cur = conn.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                           (email, generate_password_hash(password, method=HASH_METHOD), to_iso(now)))
    except sqlite3.IntegrityError as exc:
        raise AccountError("An account with this e-mail already exists. Try signing in.") from exc
    return cur.lastrowid


def authenticate(conn: sqlite3.Connection, email: str, password: str, now: datetime, client_key: str,
                 max_failures: int) -> sqlite3.Row:
    email = normalize_email(email)
    key = f"{client_key}|{email}"
    if len(_recent_failures(key, now)) >= max_failures:
        raise AccountError("Too many failed attempts. Wait 10 minutes and try again.")
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    ok = check_password_hash(user["password_hash"] if user else DUMMY_HASH, password or "")
    if not user or not ok:
        with _lock:
            _failures.setdefault(key, []).append(now)
        raise AccountError("E-mail or password is incorrect.")
    with _lock:
        _failures.pop(key, None)
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (to_iso(now), user["id"]))
    return user


def get_user(conn: sqlite3.Connection, user_id) -> sqlite3.Row | None:
    if not user_id:
        return None
    return conn.execute("SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()


def delete_user(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def followed_routes(conn: sqlite3.Connection, user_id: int) -> list[str]:
    return [r["route_id"] for r in conn.execute(
        "SELECT route_id FROM user_routes WHERE user_id = ? ORDER BY route_id", (user_id,))]


def follow_route(conn: sqlite3.Connection, user_id: int, route: str, now: datetime) -> bool:
    route = route.strip().upper()
    if not ROUTE_RE.match(route):
        raise AccountError("Route IDs may only contain letters, numbers, dots, dashes and underscores.")
    if route not in followed_routes(conn, user_id) and len(followed_routes(conn, user_id)) >= MAX_ROUTES:
        raise AccountError(f"You can follow up to {MAX_ROUTES} routes.")
    cur = conn.execute("INSERT OR IGNORE INTO user_routes (user_id, route_id, created_at) VALUES (?, ?, ?)",
                       (user_id, route, to_iso(now)))
    conn.execute(
        """INSERT OR IGNORE INTO subscriptions (label, route_filter, channel, user_id, created_at)
           VALUES (?, ?, 'demo', ?, ?)""", (f"Account alert: route {route}", route, user_id, to_iso(now)))
    return cur.rowcount > 0


def unfollow_route(conn: sqlite3.Connection, user_id: int, route: str) -> None:
    route = route.strip().upper()
    conn.execute("DELETE FROM user_routes WHERE user_id = ? AND route_id = ?", (user_id, route))
    conn.execute("DELETE FROM subscriptions WHERE user_id = ? AND route_filter = ?", (user_id, route))


def user_alerts(conn: sqlite3.Connection, user_id: int, limit: int = 20) -> list[Mapping]:
    return [dict(r) for r in conn.execute(
        """SELECT nt.id, nt.notice_id, nt.subject, nt.status, nt.created_at
           FROM notifications nt JOIN subscriptions s ON s.id = nt.subscription_id
           WHERE s.user_id = ? ORDER BY nt.id DESC LIMIT ?""", (user_id, limit))]
