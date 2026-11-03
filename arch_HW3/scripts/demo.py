#!/usr/bin/env python3

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4, UUID

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv(
    "BOOKING_BASE_URL", "http://localhost:" + os.getenv("HOST_PORT", "8082")
).rstrip("/")


def compose(*args, input=None):
    result = subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        input=input,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr + "\n" + result.stdout)
    return result.stdout.strip()


def grpc(method, value):
    return json.loads(
        compose(
            "exec",
            "-T",
            "flight",
            "python",
            "scripts/grpc_cli.py",
            method,
            input=json.dumps(value),
        )
    )


def call(method, path, body=None, expected=200, headers=None):
    request = Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        response = urlopen(request, timeout=20)
    except HTTPError as exc:
        response = exc
    with response:
        value = json.loads(response.read())
        assert response.status == expected, (method, path, response.status, value)
        assert response.headers.get("X-Request-Id")
        print(f"{method:5} {path} → {response.status}")
        return value


def sql(service, statement, show=False):
    user = "flight" if service == "flight-db" else "booking"
    database = (
        user + "_test" if os.getenv("COMPOSE_PROJECT_NAME") == "arch-hw3-test" else user
    )
    result = compose(
        "exec",
        "-T",
        service,
        "psql",
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        *(() if show else ("-t", "-A")),
        input=statement,
    )
    if show:
        print("\nSQL>", statement, "\n" + result)
    return result


def new_flight(seats=10):
    start = datetime.now(timezone.utc) + timedelta(days=40)
    value = {
        "airline_code": "DE",
        "airline_name": "Demo Air",
        "flight_number": "D" + uuid4().hex[:10].upper(),
        "origin": "SVO",
        "destination": "LED",
        "departure_time": start.isoformat(),
        "arrival_time": (start + timedelta(hours=2)).isoformat(),
        "total_seats": seats,
        "price": "7500.00",
        "status": "SCHEDULED",
    }
    return grpc("CreateFlight", {"flight": value}), value


def run():
    call("GET", "/health")
    flight, original = new_flight()
    fid = str(UUID(flight["id"]))
    user = str(uuid4())
    key = str(uuid4())
    print("flight_id:", fid, "user_id:", user)
    found = call("GET", "/flights?origin=SVO&destination=LED")
    assert fid in [f["id"] for f in found]
    day = original["departure_time"][:10]
    assert fid in [
        f["id"] for f in call("GET", f"/flights?origin=SVO&destination=LED&date={day}")
    ]
    for _ in range(2):
        assert call("GET", "/flights/" + fid)["available_seats"] == 10
    body = {
        "user_id": user,
        "flight_id": fid,
        "passenger_name": "Demo Passenger",
        "passenger_email": "demo@example.com",
        "seat_count": 2,
    }
    booking = call("POST", "/bookings", body, 201, {"Idempotency-Key": key})
    assert booking["id"] == key and Decimal(booking["total_price"]) == 15000
    assert call("GET", "/flights/" + fid)["available_seats"] == 8
    sql(
        "flight-db",
        f"SELECT id,flight_number,origin,destination,price,total_seats,available_seats,status FROM flights WHERE id='{fid}';",
        True,
    )
    sql(
        "flight-db",
        f"SELECT booking_id,flight_id,seat_count,status,price_at_reservation FROM seat_reservations WHERE booking_id='{key}';",
        True,
    )
    sql(
        "booking-db",
        f"SELECT id,user_id,flight_id,seat_count,total_price,status FROM bookings WHERE id='{key}';",
        True,
    )
    original["price"] = "9000.00"
    grpc("UpdateFlight", {"flight_id": fid, "flight": original})
    assert call("GET", "/flights/" + fid)["price"] == "9000.00"
    assert Decimal(call("GET", "/bookings/" + key)["total_price"]) == 15000
    assert key in [b["id"] for b in call("GET", "/bookings?user_id=" + user)]
    assert call("POST", "/bookings", body, 201, {"Idempotency-Key": key})["id"] == key
    assert (
        sql(
            "flight-db",
            f"SELECT count(*) FROM seat_reservations WHERE booking_id='{key}';",
        )
        == "1"
    )
    failure = call("POST", "/bookings", {**body, "seat_count": 999}, 409)
    assert failure["error_code"] == "INSUFFICIENT_SEATS"
    assert call("GET", "/flights/" + fid)["available_seats"] == 8
    call("POST", "/bookings", {**body, "seat_count": 0}, 400)
    call("GET", "/flights/" + str(uuid4()), expected=404)
    call("GET", "/bookings/" + str(uuid4()), expected=404)
    cancelled = call("POST", "/bookings/" + key + "/cancel")
    assert cancelled["status"] == "CANCELLED"
    assert call("GET", "/flights/" + fid)["available_seats"] == 10
    call("POST", "/bookings/" + key + "/cancel", expected=409)
    sql(
        "booking-db",
        f"SELECT id,status,total_price FROM bookings WHERE id='{key}';",
        True,
    )
    sql("flight-db", f"SELECT available_seats FROM flights WHERE id='{fid}';", True)
    sql(
        "flight-db",
        f"SELECT booking_id,status FROM seat_reservations WHERE booking_id='{key}';",
        True,
    )
    print(
        "\nPASS: REST → gRPC → two PostgreSQL databases, snapshot, idempotency, errors and cancellation."
    )
    print("Cache logs: docker compose logs --no-log-prefix flight")


if __name__ == "__main__":
    run()
