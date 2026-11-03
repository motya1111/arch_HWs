#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=arch-hw3-test
export COMPOSE_FILE=compose.yaml:compose.test.yaml
export BOOKING_BASE_URL=http://localhost:8092
cleanup() { docker compose --profile test down --volumes --remove-orphans; }
trap cleanup EXIT

docker compose up --build -d --wait --wait-timeout 240
status=0
docker compose --profile test run --rm tests || status=$?
if [ "$status" -eq 0 ]; then
  python3 scripts/demo.py
  python3 scripts/resilience.py
else
  docker compose logs --no-color --tail=100 booking flight
fi
exit "$status"
