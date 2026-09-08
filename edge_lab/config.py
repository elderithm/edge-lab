"""Typed settings with a fixed precedence: CLI flags > env vars > defaults.

The CLI is responsible for the first tier: it constructs :class:`Settings`
from the environment and then calls :meth:`Settings.with_overrides` with any
flags the user passed. Nothing here reads or stores trading credentials; by
design this project has none.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field

from .errors import ConfigError

DEFAULT_GAMMA_URL = "https://gamma-api.polymarket.com"
DEFAULT_DATA_URL = "https://data-api.polymarket.com"
DEFAULT_CLOB_URL = "https://clob.polymarket.com"
DEFAULT_GEOBLOCK_URL = "https://polymarket.com/api/geoblock"

DEFAULT_USER_AGENT = "polymarket-edge-lab/0.1"
DEFAULT_DB_PATH = ".edge-lab/paper.db"


class Settings(BaseModel):
    """Validated runtime settings."""

    gamma_url: str = DEFAULT_GAMMA_URL
    data_url: str = DEFAULT_DATA_URL
    clob_url: str = DEFAULT_CLOB_URL
    geoblock_url: str = DEFAULT_GEOBLOCK_URL

    user_agent: str = DEFAULT_USER_AGENT
    http_timeout: float = Field(default=10.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)

    db_path: str = DEFAULT_DB_PATH

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        data: dict[str, Any] = {}
        if v := env.get("EDGE_LAB_DB_PATH"):
            data["db_path"] = v
        if v := env.get("EDGE_LAB_USER_AGENT"):
            data["user_agent"] = v
        if v := env.get("EDGE_LAB_HTTP_TIMEOUT"):
            data["http_timeout"] = _parse_float("EDGE_LAB_HTTP_TIMEOUT", v)
        if v := env.get("EDGE_LAB_MAX_RETRIES"):
            data["max_retries"] = _parse_int("EDGE_LAB_MAX_RETRIES", v)
        for name, key in (
            ("EDGE_LAB_GAMMA_URL", "gamma_url"),
            ("EDGE_LAB_DATA_URL", "data_url"),
            ("EDGE_LAB_CLOB_URL", "clob_url"),
            ("EDGE_LAB_GEOBLOCK_URL", "geoblock_url"),
        ):
            if v := env.get(name):
                data[key] = v
        try:
            return cls(**data)
        except ValueError as exc:  # pydantic ValidationError is a ValueError
            raise ConfigError(f"invalid settings: {exc}") from exc

    def with_overrides(self, *, http_timeout: float | None = None) -> Settings:
        """Return a copy with non-None CLI overrides applied (highest priority)."""
        updates: dict[str, Any] = {}
        if http_timeout is not None:
            updates["http_timeout"] = http_timeout
        if not updates:
            return self
        try:
            return self.model_copy(update=updates)
        except ValueError as exc:
            raise ConfigError(f"invalid override: {exc}") from exc


def _parse_float(name: str, value: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {value!r}") from exc


def _parse_int(name: str, value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc
