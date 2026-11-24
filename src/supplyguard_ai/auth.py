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
