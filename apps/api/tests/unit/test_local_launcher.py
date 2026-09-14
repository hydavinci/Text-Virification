import os
import shutil
import subprocess
import time
from pathlib import Path


def test_local_launcher_waits_for_dependency_readiness(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[4] / "start-local.sh"
    launcher = tmp_path / "start-local.sh"
    shutil.copyfile(source, launcher)
    (tmp_path / ".env").touch()
    (tmp_path / "apps/web/node_modules").mkdir(parents=True)
    binaries = tmp_path / "bin"
    api_binaries = tmp_path / "apps/api/.venv/bin"
    binaries.mkdir()
    api_binaries.mkdir(parents=True)

    def executable(path: Path, body: str) -> None:
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(0o755)

    executable(binaries / "docker", "exit 0")
    executable(binaries / "lsof", "exit 1")
    executable(binaries / "curl", 'printf "%s\\n" "$*" >> "$PROBE_LOG"')
    executable(binaries / "npm", "exec sleep 30")
    executable(api_binaries / "alembic", "exit 0")
    executable(
        api_binaries / "uvicorn",
        'printf "%s\\n" "$@" > "$UVICORN_ARGUMENTS"\nexec sleep 30',
    )
    for name in ("text-verification-worker", "celery"):
        executable(api_binaries / name, "exec sleep 30")

    probe_log = tmp_path / "probes.log"
    uvicorn_arguments = tmp_path / "uvicorn-arguments.log"
    process = subprocess.Popen(
        ["/bin/bash", str(launcher)],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": f"{binaries}:/usr/bin:/bin",
            "PROBE_LOG": str(probe_log),
            "UVICORN_ARGUMENTS": str(uvicorn_arguments),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not probe_log.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        process.terminate()
        output, _ = process.communicate(timeout=12)
        assert probe_log.exists(), output
        probes = probe_log.read_text()
        assert "http://127.0.0.1:8000/api/v1/ready" in probes, probes
        assert "--max-time 5" in probes, probes
        arguments = uvicorn_arguments.read_text().splitlines()
        assert "--reload-dir" in arguments
        assert arguments[arguments.index("--reload-dir") + 1] == "apps/api/src"
        assert "--timeout-graceful-shutdown" in arguments
        assert arguments[arguments.index("--timeout-graceful-shutdown") + 1] == "5"
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
