import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None,
    reason="Docker Compose is required to render the deployment configuration.",
)


@pytest.mark.parametrize("alternate_registry", [False, True])
def test_compose_isolates_container_addresses_and_selects_build_images(
    tmp_path: Path, alternate_registry: bool
) -> None:
    infra = tmp_path / "infra"
    infra.mkdir()
    shutil.copyfile(REPOSITORY_ROOT / "infra" / "compose.yaml", infra / "compose.yaml")
    (tmp_path / ".env").write_text(
        "APP_ENV=development\n"
        "DATABASE_URL=postgresql+psycopg://local:local@localhost:5432/local\n"
        "REDIS_URL=redis://localhost:6379/0\n"
        "STORAGE_ROOT=/Users/example/Work/Text-Virification/var/jobs\n",
        encoding="utf-8",
    )
    prefix = "public.ecr.aws/docker/library/" if alternate_registry else ""
    images = {
        "PYTHON_IMAGE": f"{prefix}python:3.12-slim",
        "NODE_IMAGE": f"{prefix}node:22-slim",
        "NGINX_IMAGE": f"{prefix}nginx:1.27-alpine",
    }
    environment = {
        key: os.environ[key]
        for key in ("PATH", "HOME", "DOCKER_CONFIG")
        if key in os.environ
    }
    if alternate_registry:
        environment.update(images)
    process = subprocess.run(
        [
            "docker", "compose", "--env-file", str(tmp_path / ".env"),
            "-f", str(infra / "compose.yaml"), "config", "--format", "json",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    )
    services = json.loads(process.stdout)["services"]
    for name in ("api", "migrate", "worker", "maintenance-worker", "beat"):
        settings = services[name]["environment"]
        assert urlsplit(settings["DATABASE_URL"]).hostname == "postgres", name
        assert urlsplit(settings["REDIS_URL"]).hostname == "redis", name
        assert settings["STORAGE_ROOT"] == "/var/lib/text-verification/jobs", name
        assert services[name]["build"]["args"]["PYTHON_IMAGE"] == images["PYTHON_IMAGE"]
    assert services["web"]["build"]["args"] == {
        "NODE_IMAGE": images["NODE_IMAGE"],
        "NGINX_IMAGE": images["NGINX_IMAGE"],
    }
    assert services["worker"]["environment"]["TEXT_VERIFICATION_WORKER_ROLE"] == (
        "verification"
    )
    assert services["maintenance-worker"]["environment"]["TEXT_VERIFICATION_WORKER_ROLE"] == (
        "maintenance"
    )
