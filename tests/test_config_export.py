"""Config precedence and CSV export stability."""

from __future__ import annotations

from decimal import Decimal

import pytest
from helpers import activity

from edge_lab.config import DEFAULT_DB_PATH, Settings
from edge_lab.errors import ConfigError
from edge_lab.export.csv_export import ACTIVITY_HEADERS, write_activity_csv


def test_defaults():
    s = Settings.from_env(environ={})
    assert s.db_path == DEFAULT_DB_PATH
    assert s.http_timeout == 10.0


def test_env_overrides_defaults():
    s = Settings.from_env(environ={"EDGE_LAB_DB_PATH": "/tmp/x.db", "EDGE_LAB_HTTP_TIMEOUT": "3"})
    assert s.db_path == "/tmp/x.db"
    assert s.http_timeout == 3.0


def test_cli_override_beats_env():
    s = Settings.from_env(environ={"EDGE_LAB_HTTP_TIMEOUT": "3"}).with_overrides(http_timeout=7.5)
    assert s.http_timeout == 7.5


def test_invalid_timeout_raises_config_error():
    with pytest.raises(ConfigError):
        Settings.from_env(environ={"EDGE_LAB_HTTP_TIMEOUT": "not-a-number"})


def test_csv_headers_stable_and_iso(tmp_path):
    out = tmp_path / "a.csv"
    n = write_activity_csv([activity(timestamp=1_767_225_600, price=Decimal("0.5"))], out)
    assert n == 1
    lines = out.read_text().splitlines()
    assert lines[0] == ",".join(ACTIVITY_HEADERS)
    assert "2026-01-01T00:00:00Z" in lines[1]
