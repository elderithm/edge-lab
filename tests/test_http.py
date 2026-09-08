"""HTTP client: retries are bounded, transient failures retried, 4xx not."""

from __future__ import annotations

import httpx
import pytest

from edge_lab.errors import HttpError, NotFoundError, RateLimitError
from edge_lab.http import HttpClient

URL = "https://example.test/thing"


def client(max_retries=3, **kw):
    kw.setdefault("sleep", lambda _s: None)  # never sleep in tests
    return HttpClient(max_retries=max_retries, **kw)


def test_success_returns_json(httpx_mock):
    httpx_mock.add_response(url=URL, json={"ok": True})
    with client() as c:
        assert c.get_json(URL) == {"ok": True}


def test_404_raises_not_found_without_retry(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=404)
    with client() as c:
        with pytest.raises(NotFoundError):
            c.get_json(URL)
    assert len(httpx_mock.get_requests()) == 1


def test_4xx_not_retried(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=400, text="bad")
    with client() as c:
        with pytest.raises(HttpError):
            c.get_json(URL)
    assert len(httpx_mock.get_requests()) == 1


def test_5xx_retried_then_succeeds(httpx_mock):
    httpx_mock.add_response(url=URL, status_code=503)
    httpx_mock.add_response(url=URL, status_code=503)
    httpx_mock.add_response(url=URL, json={"ok": 1})
    with client() as c:
        assert c.get_json(URL) == {"ok": 1}
    assert len(httpx_mock.get_requests()) == 3


def test_retries_are_bounded(httpx_mock):
    for _ in range(3):  # 1 initial + 2 retries
        httpx_mock.add_response(url=URL, status_code=500)
    with client(max_retries=2) as c:
        with pytest.raises(HttpError):
            c.get_json(URL)
    # 1 initial attempt + 2 retries
    assert len(httpx_mock.get_requests()) == 3


def test_429_raises_rate_limit(httpx_mock):
    for _ in range(2):  # 1 initial + 1 retry
        httpx_mock.add_response(url=URL, status_code=429)
    with client(max_retries=1) as c:
        with pytest.raises(RateLimitError):
            c.get_json(URL)
    assert len(httpx_mock.get_requests()) == 2


def test_timeout_is_retried_and_bounded(httpx_mock):
    httpx_mock.add_exception(httpx.ReadTimeout("slow"))
    httpx_mock.add_exception(httpx.ReadTimeout("slow"))
    httpx_mock.add_exception(httpx.ReadTimeout("slow"))
    with client(max_retries=2) as c:
        with pytest.raises(HttpError):
            c.get_json(URL)
    assert len(httpx_mock.get_requests()) == 3
