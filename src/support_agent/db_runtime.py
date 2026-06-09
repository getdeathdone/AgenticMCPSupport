"""Runtime database selection helpers for the web application."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from support_agent.config import get_settings


UPLOAD_DB_PATH = Path("data/uploaded_support.db")


def get_active_database_info() -> dict[str, str | bool]:
    """Return the currently selected SQLite database path and mode."""

    settings = get_settings()
    active_path = settings.support_db_path
    default_path = Path("data/support.db")
    return {
        "path": str(active_path),
        "name": active_path.name,
        "is_default": active_path == default_path,
        "seed_enabled": settings.support_db_seed_enabled,
    }


def use_default_database() -> dict[str, str | bool]:
    """Switch the running app back to the seeded demo database."""

    os.environ["SUPPORT_DB_PATH"] = "data/support.db"
    os.environ["SUPPORT_DB_SEED_ENABLED"] = "true"
    return get_active_database_info()


def use_uploaded_database(uploaded_path: Path) -> dict[str, str | bool]:
    """Switch the running app to an uploaded SQLite database."""

    os.environ["SUPPORT_DB_PATH"] = str(uploaded_path)
    os.environ["SUPPORT_DB_SEED_ENABLED"] = "false"
    return get_active_database_info()


def validate_sqlite_database(path: Path) -> None:
    """Validate that a file is a readable SQLite database."""

    try:
        with sqlite3.connect(path) as connection:
            connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.DatabaseError as exc:
        raise ValueError("Uploaded file is not a valid SQLite database.") from exc
