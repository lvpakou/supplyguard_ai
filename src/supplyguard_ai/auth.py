"""USERS AND ROLES (data/config/users.csv). OWNER: role 3.

Which document scopes a user may retrieve. Used by retrieval and by the chat login.
"""

import csv
from functools import lru_cache

from supplyguard_ai.config import data_dir


@lru_cache
def users() -> dict[str, dict]:
    with (data_dir() / "config" / "users.csv").open(newline="", encoding="utf-8") as f:
        return {row["user_id"]: row for row in csv.DictReader(f)}


def document_scopes(user_id: str) -> list[str]:
    user = users().get(user_id)
    return user["document_scopes"].split(";") if user else ["public"]


@lru_cache
def role_scopes() -> dict[str, list[str]]:
    """Role -> the document scopes that role may read, from users.csv.

    If two users ever share a role with different scopes, the role gets only the
    scopes they have in common (least access wins).
    """
    scopes: dict[str, set[str]] = {}
    for row in users().values():
        mine = set(row["document_scopes"].split(";"))
        role = row["role"]
        scopes[role] = scopes[role] & mine if role in scopes else mine
    return {role: sorted(s) for role, s in scopes.items()}


def scopes_for_role(role: str) -> list[str]:
    """Scopes for a role; an unknown role only sees public documents."""
    return role_scopes().get(role, ["public"])
