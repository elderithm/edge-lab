"""Error hierarchy for Polymarket Edge Lab.

The distinction that matters at the CLI boundary is between *expected*
user/data/runtime failures (which should print a clean message and exit 1)
and unexpected programming errors (which should surface a traceback under
``--verbose``).
"""

from __future__ import annotations


class EdgeLabError(Exception):
    """Base class for all expected, user-facing errors."""


class ConfigError(EdgeLabError):
    """Invalid configuration or environment."""


class ApiError(EdgeLabError):
    """Base class for API-layer failures."""


class HttpError(ApiError):
    """A transport or non-success HTTP response after retries are exhausted."""

    def __init__(self, message: str, *, url: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class RateLimitError(HttpError):
    """HTTP 429 / throttling that persisted after bounded retries."""


class NotFoundError(ApiError):
    """A requested resource does not exist (HTTP 404 or empty lookup)."""


class DataError(EdgeLabError):
    """The response was retrieved but could not be normalized safely."""


class PaperTradingError(EdgeLabError):
    """An invariant of the paper-trading ledger was violated."""
