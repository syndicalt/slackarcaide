"""Alembic adoption and fail-closed migration tests."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import get_settings


def _config(database_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("ARCADE_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    get_settings.cache_clear()
    return Config(str(Path(__file__).parents[1] / "alembic.ini"))


def test_unversioned_exact_legacy_schema_is_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "legacy.db"
    config = _config(database_path, monkeypatch)
    command.upgrade(config, "0001_legacy_schema")

    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("DELETE FROM alembic_version")
        connection.commit()

    command.upgrade(config, "head")

    with closing(sqlite3.connect(database_path)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        rating_event = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'rating_event'"
        ).fetchone()

    assert revision == ("0002_hardened_schema",)
    assert rating_event == ("rating_event",)
    get_settings.cache_clear()


def test_partial_legacy_schema_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "partial.db"
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("CREATE TABLE agent (id TEXT PRIMARY KEY)")
        connection.commit()

    config = _config(database_path, monkeypatch)
    with pytest.raises(RuntimeError, match="partial legacy schema"):
        command.upgrade(config, "head")
    get_settings.cache_clear()
