"""Pytest fixtures exposing the shared builders."""

from __future__ import annotations

import pytest
from helpers import activity, book


@pytest.fixture
def make_book():
    return book


@pytest.fixture
def make_activity():
    return activity
