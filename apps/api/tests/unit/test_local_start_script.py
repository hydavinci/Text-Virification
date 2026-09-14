from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX launcher")


@pytest.fixture
def local_project(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    script = ROOT / "start-local.sh"
    assert script.is_file(), "The one-command local launcher is missing"
    root = tmp_path / "project with spaces"
    root.mkdir()
    shutil.copy2(script, root / script.name)
    (root / ".env").write_text("APP_ENV=development\n")
    (root / "apps/web/node_modules").mkdir(parents=True)
    bin_dir = root / "apps/api/.venv/bin"
    bin_dir.mkdir(parents=True)
    fake = f"""#!{sys.executable}
import json
import os
import subprocess
import sys
import time
from pathlib import Path

name = Path(sys.argv[0]).name
with open("calls.jsonl", "a") as stream:
    stream.write(json.dumps({{
        "name": name, "args": sys.argv[1:], "cwd": os.getcwd(),
        "role": os.environ.get("TEXT_VERIFICATION_WORKER_ROLE"),
        "queues": os.environ.get("TEXT_VERIFICATION_WORKER_QUEUES"),
        "concurrency": os.environ.get("TEXT_VERIFICATION_WORKER_CONCURRENCY"),
    }}) + "\\n")
if name == "lsof":
    sys.exit(0 if os.environ.get("PORT_BUSY") else 1)
if name == "alembic":
    sys.exit(int(os.environ.get("MIGRATION_EXIT", "0")))
if name == "docker" and "ps" in sys.argv and os.environ.get("DOCKER_APP"):
    print("worker")
if name in ("docker", "curl"):
    sys.exit(0)
if name == "uvicorn" and os.environ.get("CRASH_API"):
    sys.exit(7)
child = subprocess.Popen(["/bin/sleep", "300"])
with open("pids", "a") as stream:
    stream.write(f"{{os.getpid()}} {{child.pid}}\\n")
child.wait()
"""
    for name in ("docker", "curl", "lsof", "npm", "alembic",
                 "uvicorn", "text-verification-worker", "celery"):
        executable = bin_dir / name
        executable.write_text(fake)
        executable.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"}
    return root, env


def calls(root: Path) -> list[dict[str, object]]:
    path = root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def assert_children_stopped(root: Path) -> None:
    path = root / "pids"
    if not path.exists():
        return
    for pid in map(int, path.read_text().split()):
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            pytest.fail(f"Launcher left process {pid} running")


def test_missing_env_fails_before_starting_services(local_project):
    root, env = local_project
    (root / ".env").unlink()
    result = subprocess.run(
        ["bash", str(root / "start-local.sh")], cwd=root.parent, env=env,
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert ".env" in result.stderr
    assert not calls(root)


def test_migration_failure_does_not_start_application(local_project):
    root, env = local_project
    result = subprocess.run(
        ["bash", str(root / "start-local.sh")], cwd=root.parent,
        env={**env, "MIGRATION_EXIT": "9"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert not (root / "pids").exists()
    assert not (root / "var/local/run.lock").exists()
    renderer_call = next(call for call in calls(root) if "renderer" in call["args"])
    assert "--build" not in renderer_call["args"]


@pytest.mark.parametrize("conflict", ["PORT_BUSY", "DOCKER_APP"])
def test_existing_services_are_not_modified(local_project, conflict):
    root, env = local_project
    result = subprocess.run(
        ["bash", str(root / "start-local.sh")], cwd=root.parent,
        env={**env, conflict: "1"},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert not (root / "pids").exists()
    assert not any(call["name"] == "alembic" or "up" in call["args"] for call in calls(root))
    assert not (root / "var/local/run.lock").exists()


@pytest.mark.parametrize("stop_signal", [signal.SIGINT, signal.SIGTERM])
def test_startup_and_shutdown_own_all_five_processes(local_project, stop_signal):
    root, env = local_project
    output = root / "output"
    with output.open("w") as stream:
        process = subprocess.Popen(
            ["bash", str(root / "start-local.sh")], cwd=root.parent, env=env,
            stdout=stream, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while "Local services ready" not in output.read_text():
                assert process.poll() is None, output.read_text()
                assert time.monotonic() < deadline, output.read_text()
                time.sleep(0.1)
            # HTTP readiness does not imply the independent Workers have finished spawning.
            pid_file = root / "pids"
            while not pid_file.exists() or len(pid_file.read_text().splitlines()) != 5:
                assert process.poll() is None, output.read_text()
                assert time.monotonic() < deadline, output.read_text()
                time.sleep(0.1)
            recorded = calls(root)
            migration = next(call for call in recorded if call["name"] == "alembic")
            assert migration["args"] == ["-c", "apps/api/alembic.ini", "upgrade", "head"]
            assert all(call["cwd"] == str(root.resolve()) for call in recorded)
            workers = [call for call in recorded if call["name"] == "text-verification-worker"]
            assert {(call["role"], call["queues"], call["concurrency"]) for call in workers} == {
                ("verification", "celery,verification-v2", "2"),
                ("maintenance", "maintenance-v2", "1"),
            }
            assert any(
                call["name"] == "npm"
                and call["args"] == [
                    "--prefix", "apps/web", "run", "dev", "--",
                    "--host", "127.0.0.1", "--port", "5173", "--strictPort",
                ]
                for call in recorded
            )
            assert len((root / "pids").read_text().splitlines()) == 5
            duplicate = subprocess.run(
                ["bash", str(root / "start-local.sh")], env=env,
                capture_output=True, text=True, timeout=10,
            )
            assert duplicate.returncode != 0
            assert process.poll() is None
        finally:
            process.send_signal(stop_signal)
            process.wait(timeout=20)
    assert_children_stopped(root)
    assert not (root / "var/local/run.lock").exists()
    assert not any("down" in call["args"] for call in calls(root))


def test_child_failure_stops_other_services(local_project):
    root, env = local_project
    result = subprocess.run(
        ["bash", str(root / "start-local.sh")], cwd=root.parent,
        env={**env, "CRASH_API": "1"},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert "api" in result.stderr.lower()
    assert_children_stopped(root)
