#!/usr/bin/env python3

import json
import os
import time
from urllib.request import urlopen
from urllib.error import HTTPError
from demo import compose, call, new_flight, BASE


def raw(path):
    started = time.monotonic()
    try:
        response = urlopen(BASE + path, timeout=20)
    except HTTPError as exc:
        response = exc
    with response:
        result = (
            response.status,
            json.loads(response.read()),
            time.monotonic() - started,
        )
    return result


def wait_for(fn, timeout=60):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if fn():
            return
        time.sleep(0.5)
    assert fn(), "Timed out waiting for recovery"


def main():
    if os.getenv("COMPOSE_PROJECT_NAME") != "arch-hw3-test":
        raise SystemExit(
            "Run with scripts/test.sh: fault demonstration uses only isolated arch-hw3-test containers"
        )
    flight, _ = new_flight()
    path = "/flights/" + flight["id"]
    call("GET", path)
    print("\n1. Flight outage: retries → OPEN → immediate HTTP 503")
    compose("stop", "flight")
    try:
        for index in range(8):
            status, body, elapsed = raw(path)
            print(
                "request",
                index + 1,
                "status",
                status,
                "seconds",
                round(elapsed, 3),
                "code",
                body.get("error_code"),
            )
            assert status == 503
            if raw("/diagnostics")[1]["circuit_breaker"]["state"] == "OPEN":
                break
        else:
            raise AssertionError("Circuit did not open")
        status, body, elapsed = raw(path)
        assert status == 503 and body["error_code"] == "CIRCUIT_OPEN" and elapsed < 0.8
        print("OPEN rejected without waiting for RPC:", round(elapsed, 3), "seconds")
    finally:
        compose("start", "flight")
    wait_for(lambda: raw(path)[0] == 200)
    assert raw("/diagnostics")[1]["circuit_breaker"]["state"] == "CLOSED"
    print("PASS: HALF_OPEN probe closed the breaker after recovery")
    logs = compose("logs", "--no-color", "--no-log-prefix", "booking")
    assert (
        '"current": "OPEN"' in logs
        and '"current": "HALF_OPEN"' in logs
        and '"current": "CLOSED"' in logs
    )
    print("\n2. Redis master failure and automatic Sentinel promotion")
    old = compose(
        "exec",
        "-T",
        "sentinel-1",
        "redis-cli",
        "-p",
        "26379",
        "--raw",
        "SENTINEL",
        "get-master-addr-by-name",
        "flights",
    ).splitlines()[0]
    assert old in ("redis-master", "redis-replica-1", "redis-replica-2"), old
    compose("stop", old)
    try:

        def promoted():
            current = compose(
                "exec",
                "-T",
                "sentinel-1",
                "redis-cli",
                "-p",
                "26379",
                "--raw",
                "SENTINEL",
                "get-master-addr-by-name",
                "flights",
            ).splitlines()
            return bool(current and current[0] != old)

        wait_for(promoted)
        current = compose(
            "exec",
            "-T",
            "sentinel-1",
            "redis-cli",
            "-p",
            "26379",
            "--raw",
            "SENTINEL",
            "get-master-addr-by-name",
            "flights",
        ).splitlines()[0]
        print("Master switched:", old, "→", current)
        for _ in range(3):
            assert raw(path)[0] == 200

        def cached():
            ttl = compose(
                "exec",
                "-T",
                current,
                "redis-cli",
                "--raw",
                "TTL",
                "flight:" + flight["id"],
            )
            return ttl.lstrip("-").isdigit() and 0 < int(ttl) <= 600

        wait_for(cached)
        print("PASS: API works and Sentinel client writes TTL cache to the new master")
    finally:
        compose("start", old)
    print("\n3. Complete Redis outage: PostgreSQL fallback")
    nodes = ["redis-master", "redis-replica-1", "redis-replica-2"]
    compose("stop", *nodes)
    try:
        assert raw(path)[0] == 200
        print("PASS: flight reads work without Redis")
    finally:
        compose("start", *nodes)
    print(
        "\nPASS: live outage, circuit transitions, Redis failover and cache fallback."
    )


if __name__ == "__main__":
    main()
