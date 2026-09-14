import logging
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_migration_keeps_existing_application_loggers_enabled(
    request: pytest.FixtureRequest,
) -> None:
    logger = logging.getLogger("text_verification.ci_migration_probe")
    logger.disabled = False
    request.getfixturevalue("db_engine")
    assert not logger.disabled


@pytest.mark.parametrize("case", [1, 2])
def test_database_schema_isolates_committed_test_data(db_engine: Engine, case: int) -> None:
    with db_engine.begin() as connection:
        assert connection.execute(text("SELECT to_regclass('ci_isolation_probe')")).scalar() is None
        connection.execute(text("CREATE TABLE ci_isolation_probe (id integer PRIMARY KEY)"))
        connection.execute(text("INSERT INTO ci_isolation_probe (id) VALUES (:id)"), {"id": case})


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def test_pass():\n    assert True\n", 0),
        ("import pytest\n\ndef test_skip():\n    pytest.skip('service unavailable')\n", 1),
        ("import pytest\n\npytest.skip('service unavailable', allow_module_level=True)\n", 1),
    ],
)
def test_ci_gate_fails_on_runtime_and_collection_skips(
    tmp_path: Path, source: str, expected: int
) -> None:
    test_file = tmp_path / "test_gate.py"
    test_file.write_text(source, encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable, str(BACKEND_ROOT / "scripts/ci_pytest.py"),
            "--gate", "database", str(test_file), "-q",
            "--basetemp", str(tmp_path / "pytest"),
        ],
        env={
            **os.environ,
            "TEST_DATABASE_URL": "postgresql://unused/ci",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    if expected:
        assert "CI gate rejected skipped tests" in result.stderr


def test_ci_gate_requires_explicit_service_configuration() -> None:
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts/ci_pytest.py"), "--gate", "database"],
        env={key: value for key, value in os.environ.items() if key != "TEST_DATABASE_URL"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert "TEST_DATABASE_URL must be set" in result.stderr


def test_backend_lock_pins_every_registry_package_and_artifact() -> None:
    lock = tomllib.loads((BACKEND_ROOT / "uv.lock").read_text(encoding="utf-8"))
    packages = lock["package"]
    names = {package["name"] for package in packages}
    assert {"pytest", "ruff", "mypy", "rapidocr", "onnxruntime"} <= names
    assert "debugpy" not in names
    for package in packages:
        assert package["version"]
        for dependency in package.get("dependencies", []):
            assert dependency["name"] in names
        if "registry" not in package["source"]:
            assert package["name"] == "text-verification"
            continue
        artifacts = [*package.get("wheels", [])]
        if "sdist" in package:
            artifacts.append(package["sdist"])
        assert artifacts, package["name"]
        assert all(artifact["hash"].startswith("sha256:") for artifact in artifacts)
