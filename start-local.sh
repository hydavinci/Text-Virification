#!/bin/bash
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

[[ $# -eq 0 ]] || fail "Usage: ./start-local.sh"
[[ -f .env ]] || fail "Missing .env; follow the macOS setup in README.md first."
for command in docker npm curl lsof; do
  command -v "$command" >/dev/null || fail "Required command not found: $command"
done
for command in alembic uvicorn text-verification-worker celery; do
  [[ -x "apps/api/.venv/bin/$command" ]] ||
    fail "Missing $command in apps/api/.venv; install apps/api[dev] first."
done
[[ -d apps/web/node_modules ]] || fail "Run npm --prefix apps/web ci first."

mkdir -p var/jobs var/local
mkdir var/local/run.lock 2>/dev/null ||
  fail "Another launcher is running. If it crashed, confirm its processes have stopped, then remove var/local/run.lock."

pids=()
names=()
# Job control gives each service its own process group, including reload/worker children.
set -m
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  local pid attempt alive
  if [[ ${#pids[@]} -gt 0 ]]; then
    printf '\nStopping local application processes...\n'
    for pid in "${pids[@]}"; do
      kill -TERM -- "-$pid" 2>/dev/null || true
    done
    for ((attempt = 0; attempt < 10; attempt++)); do
      alive=0
      for pid in "${pids[@]}"; do
        if kill -0 -- "-$pid" 2>/dev/null; then alive=1; fi
      done
      [[ $alive -eq 1 ]] || break
      sleep 1
    done
    for pid in "${pids[@]}"; do
      if kill -0 -- "-$pid" 2>/dev/null; then
        printf 'Force-stopping remaining service process group %s\n' "$pid" >&2
        kill -KILL -- "-$pid" 2>/dev/null || true
      fi
      wait "$pid" 2>/dev/null || true
    done
  fi
  rmdir var/local/run.lock
  printf 'PostgreSQL, Redis and the renderer are left running; database data is preserved.\n'
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for port in 8000 5173; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null; then
    fail "Port $port is already in use. Stop the existing service before starting this launcher."
  fi
done

compose=(docker compose --env-file .env -f infra/compose.yaml -f infra/compose.local-services.yaml)
docker info >/dev/null || fail "Docker is not ready. Start Docker Desktop first."
running_services=$("${compose[@]}" ps --status running --services)
while IFS= read -r service; do
  case "$service" in
    api|worker|maintenance-worker|beat|web)
      fail "Docker service '$service' is running. Stop the Docker application services before using native mode."
      ;;
  esac
done <<< "$running_services"

printf 'Starting PostgreSQL and Redis...\n'
"${compose[@]}" up -d --wait postgres redis
printf 'Starting the Docker document renderer (reusing installed dependencies)...\n'
"${compose[@]}" up -d --wait renderer renderer-gateway
printf 'Applying database migrations...\n'
apps/api/.venv/bin/alembic -c apps/api/alembic.ini upgrade head

start() {
  local name=$1
  shift
  "$@" >"var/local/$name.log" 2>&1 &
  pids+=("$!")
  names+=("$name")
}

check_processes() {
  local index
  for ((index = 0; index < ${#pids[@]}; index++)); do
    if ! kill -0 "${pids[$index]}" 2>/dev/null; then
      fail "${names[$index]} exited. See var/local/${names[$index]}.log"
    fi
  done
}

start api apps/api/.venv/bin/uvicorn text_verification.main:app \
  --reload --reload-dir apps/api/src --timeout-graceful-shutdown 5 \
  --host 127.0.0.1 --port 8000
start worker env \
  TEXT_VERIFICATION_WORKER_ROLE=verification \
  TEXT_VERIFICATION_WORKER_QUEUES=celery,verification-v2 \
  TEXT_VERIFICATION_WORKER_CONCURRENCY=2 \
  apps/api/.venv/bin/text-verification-worker
start maintenance-worker env \
  TEXT_VERIFICATION_WORKER_ROLE=maintenance \
  TEXT_VERIFICATION_WORKER_QUEUES=maintenance-v2 \
  TEXT_VERIFICATION_WORKER_CONCURRENCY=1 \
  apps/api/.venv/bin/text-verification-worker
start beat apps/api/.venv/bin/celery \
  -A text_verification.workers.celery_app:celery_app \
  beat --loglevel=INFO --schedule=var/celerybeat-schedule
start web npm --prefix apps/web run dev -- \
  --host 127.0.0.1 --port 5173 --strictPort

printf 'Waiting for API dependencies, verification worker and frontend (up to 60 seconds)...\n'
deadline=$((SECONDS + 60))
while true; do
  check_processes
  if curl --fail --silent --max-time 5 http://127.0.0.1:8000/api/v1/ready >/dev/null &&
    curl --fail --silent --max-time 2 http://127.0.0.1:5173/ >/dev/null; then
    break
  fi
  [[ $SECONDS -lt $deadline ]] || fail "Startup timed out. See logs in var/local/."
  sleep 1
done
# Catch services that exited while the HTTP probes were running.
check_processes
printf '\nLocal services ready: http://localhost:5173\n'
printf 'API: http://127.0.0.1:8000/docs\nLogs: %s/var/local/*.log\n' "$PWD"
printf 'Keep this terminal open. Press Ctrl+C to stop the application processes.\n'
while true; do
  sleep 1
  check_processes
done
