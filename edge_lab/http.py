"""A thin, retrying JSON-over-HTTP client used by every API client.

Only idempotent GETs are issued. Retries are bounded and apply exponential
backoff with jitter, but never turn into a retry storm: 4xx responses (other
than 429) fail immediately. Sleep and jitter are injectable so tests remain
fast and deterministic.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from typing import Any

import httpx

from .errors import HttpError, NotFoundError, RateLimitError

logger = logging.getLogger("edge_lab.http")

# Status codes worth retrying: throttling and transient server-side failures.
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        user_agent: str = "polymarket-edge-lab/0.1",
        max_retries: int = 3,
        backoff_base: float = 0.4,
        backoff_cap: float = 8.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max(0, max_retries)
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers={"Accept": "application/json", "User-Agent": user_agent},
        )

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """GET ``url`` and decode JSON, retrying transient failures.

        Raises :class:`NotFoundError` on 404, :class:`RateLimitError` when
        throttling outlives the retry budget, and :class:`HttpError` for any
        other exhausted failure.
        """
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        last_status: int | None = None
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.get(url, params=clean)
            except httpx.TimeoutException as exc:
                last_error, last_status = exc, None
                logger.debug("timeout url=%s attempt=%d", url, attempt)
            except httpx.TransportError as exc:
                last_error, last_status = exc, None
                logger.debug("transport error url=%s attempt=%d err=%s", url, attempt, exc)
            else:
                status = resp.status_code
                if status == 404:
                    raise NotFoundError(f"not found: {url}")
                if 200 <= status < 300:
                    try:
                        return resp.json()
                    except ValueError as exc:
                        raise HttpError(f"invalid JSON from {url}: {exc}", url=url, status_code=status) from exc
                if status not in _RETRY_STATUSES:
                    raise HttpError(f"HTTP {status} from {url}: {resp.text[:200]}", url=url, status_code=status)
                last_status, last_error = status, None
                logger.debug("retryable status=%d url=%s attempt=%d", status, url, attempt)

            if attempt < self._max_retries:
                self._sleep(self._backoff(attempt))

        if last_status == 429:
            raise RateLimitError(f"rate limited after {self._max_retries} retries: {url}", url=url, status_code=429)
        raise HttpError(
            f"GET failed after {self._max_retries} retries: {url}: {last_error or f'HTTP {last_status}'}",
            url=url,
            status_code=last_status,
        )

    def _backoff(self, attempt: int) -> float:
        delay = min(self._backoff_cap, self._backoff_base * (2**attempt))
        return delay + self._rng.uniform(0.0, self._backoff_base)
