from __future__ import annotations

import pytest

from text_verification import config as config_module
from text_verification.config import Settings


def _validate(settings: Settings) -> None:
    validator = getattr(
        config_module,
        "validate_runtime_settings",
        lambda _settings: None,
    )
    validator(settings)


@pytest.mark.parametrize(
    ("app_env", "secret"),
    [
        ("production", ""),
        ("staging", "short-secret"),
        ("deployed", ""),
    ],
)
def test_deployed_settings_require_a_32_byte_recheck_secret(
    app_env: str,
    secret: str,
) -> None:
    settings = Settings(
        app_env=app_env,
        recheck_grant_secret=secret,
    )

    with pytest.raises(RuntimeError, match="RECHECK_GRANT_SECRET"):
        _validate(settings)


def test_deployed_settings_accept_a_32_byte_recheck_secret() -> None:
    _validate(
        Settings(
            app_env="production",
            recheck_grant_secret="x" * 32,
        )
    )


def test_explicit_test_environment_allows_an_empty_recheck_secret() -> None:
    _validate(
        Settings(
            app_env="test",
            recheck_grant_secret="",
        )
    )


def test_recheck_secret_is_not_exposed_in_repr_or_validation_errors() -> None:
    secret = "short-secret-never-log"
    settings = Settings(
        app_env="production",
        recheck_grant_secret=secret,
    )

    assert secret not in repr(settings)
    with pytest.raises(RuntimeError) as raised:
        _validate(settings)
    assert secret not in str(raised.value)


def test_application_startup_validates_deployed_recheck_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from text_verification import main

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(
            app_env="production",
            recheck_grant_secret="",
        ),
    )

    with pytest.raises(RuntimeError, match="RECHECK_GRANT_SECRET"):
        main.create_app()
