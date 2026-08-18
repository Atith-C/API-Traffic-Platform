"""Unit tests for settings parsing (no external dependencies)."""

from __future__ import annotations

from app.core.config import Settings


def test_cors_origins_parsed_from_csv_string() -> None:
    s = Settings(cors_origins="http://a.com, http://b.com ,")
    assert s.cors_origins == ["http://a.com", "http://b.com"]


def test_cors_origins_accepts_list() -> None:
    s = Settings(cors_origins=["http://a.com"])
    assert s.cors_origins == ["http://a.com"]


def test_is_production_flag() -> None:
    assert Settings(app_env="production").is_production is True
    assert Settings(app_env="development").is_production is False
