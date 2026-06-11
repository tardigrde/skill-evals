"""User directory service: authentication and search.

Fixture for the commit-push-pr eval suite. The eval prompts refer to two
changes in this file: the login fix (authenticate now normalizes the email
before lookup, so mixed-case logins stop failing) and the new search
feature (search_users).
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class User:
    email: str
    name: str
    password_hash: str
    active: bool = True


def _hash_password(password: str) -> str:
    return sha256(password.encode("utf-8")).hexdigest()


USERS: dict[str, User] = {
    "ada@example.com": User("ada@example.com", "Ada Lovelace", _hash_password("analytical-engine")),
    "grace@example.com": User("grace@example.com", "Grace Hopper", _hash_password("nanoseconds")),
    "alan@example.com": User("alan@example.com", "Alan Turing", _hash_password("enigma"), active=False),
}


def authenticate(email: str, password: str) -> User | None:
    """Return the matching active user, or None.

    Login fix: emails are normalized (trimmed, lowercased) before lookup, so
    "Ada@Example.com " authenticates the same as "ada@example.com".
    """
    user = USERS.get(email.strip().lower())
    if user is None or not user.active:
        return None
    if not hmac.compare_digest(user.password_hash, _hash_password(password)):
        return None
    return user


def search_users(query: str, *, include_inactive: bool = False, limit: int = 10) -> list[User]:
    """New search feature: case-insensitive substring match on name or email.

    Results are sorted by name and capped at `limit`.
    """
    needle = query.strip().lower()
    if not needle:
        return []
    matches = [
        user
        for user in USERS.values()
        if (include_inactive or user.active) and (needle in user.name.lower() or needle in user.email.lower())
    ]
    matches.sort(key=lambda user: user.name)
    return matches[: max(0, limit)]
