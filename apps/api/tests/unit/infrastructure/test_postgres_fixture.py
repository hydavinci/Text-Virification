from __future__ import annotations

import os
from importlib import import_module
from types import SimpleNamespace

import pytest


def test_test_database_url_fixture_skips_without_explicit_opt_in(monkeypatch) -> None:
    conftest = import_module("tests.conftest")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        conftest,
        "subprocess",
        SimpleNamespace(run=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError())),
        raising=False,
    )
    conftest._reset_database_caches()

    fixture = conftest.test_database_url.__wrapped__()

    with pytest.raises(pytest.skip.Exception, match="TEST_DATABASE_URL"):
        next(fixture)


def test_test_database_url_fixture_yields_configured_url_and_restores_cached_settings(
    monkeypatch,
) -> None:
    conftest = import_module("tests.conftest")
    original_database_url = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/original"
    configured_test_database_url = (
        "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/text_verification"
    )
    monkeypatch.setenv("DATABASE_URL", original_database_url)
    monkeypatch.setenv("TEST_DATABASE_URL", configured_test_database_url)
    conftest._reset_database_caches()

    engine = conftest._get_engine(original_database_url)
    conftest._get_session_factory(original_database_url)
    assert conftest.get_settings().database_url == original_database_url

    fixture = conftest.test_database_url.__wrapped__()

    assert next(fixture) == configured_test_database_url
    assert os.environ["TEST_DATABASE_URL"] == configured_test_database_url
    assert os.environ["DATABASE_URL"] == configured_test_database_url
    assert conftest.get_settings().database_url == configured_test_database_url
    assert conftest._get_engine.cache_info().currsize == 0
    assert conftest._get_session_factory.cache_info().currsize == 0

    with pytest.raises(StopIteration):
        next(fixture)

    assert os.environ["TEST_DATABASE_URL"] == configured_test_database_url
    assert os.environ["DATABASE_URL"] == original_database_url
    assert conftest.get_settings().database_url == original_database_url
    assert conftest._get_engine.cache_info().currsize == 0
    assert conftest._get_session_factory.cache_info().currsize == 0
    engine.dispose()
