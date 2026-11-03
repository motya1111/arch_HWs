import os
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4
import grpc
import psycopg
import pytest
from redis.sentinel import Sentinel
from flights.v1 import flight_pb2 as pb


def seats(stub, auth, id):
    return stub.GetFlight(
        pb.GetFlightRequest(flight_id=id), metadata=auth, timeout=5
    ).available_seats


def wait_for(check, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.2)
    assert check()


@pytest.mark.parametrize(
    "method,message",
    [
        ("SearchFlights", pb.SearchFlightsRequest()),
        ("GetFlight", pb.GetFlightRequest()),
        ("ReserveSeats", pb.ReserveSeatsRequest()),
        ("ReleaseReservation", pb.ReleaseReservationRequest()),
        ("CreateFlight", pb.CreateFlightRequest()),
        ("UpdateFlight", pb.UpdateFlightRequest()),
        ("Health", pb.HealthRequest()),
    ],
)
@pytest.mark.parametrize("metadata", [[], [("x-api-key", "invalid")]])
def test_all_rpcs_require_authentication(stub, method, message, metadata):
    with pytest.raises(grpc.RpcError) as error:
        getattr(stub, method)(message, metadata=metadata, timeout=3)
    assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED


def test_search_optional_date_and_missing_flight(stub, auth, flight):
    value = flight[0]
    found = stub.SearchFlights(
        pb.SearchFlightsRequest(origin="SVO", destination="LED"),
        metadata=auth,
        timeout=5,
    )
    assert value.id in [f.id for f in found.flights]
    day = value.departure_time.ToDatetime().date().isoformat()
    found = stub.SearchFlights(
        pb.SearchFlightsRequest(origin="SVO", destination="LED", date=day),
        metadata=auth,
        timeout=5,
    )
    assert value.id in [f.id for f in found.flights]
    with pytest.raises(grpc.RpcError) as e:
        stub.GetFlight(pb.GetFlightRequest(flight_id=str(uuid4())), metadata=auth)
    assert e.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.parametrize(
    "message",
    [
        pb.SearchFlightsRequest(origin="sv", destination="LED"),
        pb.SearchFlightsRequest(origin="SVO", destination="SVO"),
        pb.SearchFlightsRequest(origin="SVO", destination="LED", date="2026-13-02"),
        pb.GetFlightRequest(flight_id="bad"),
        pb.ReserveSeatsRequest(
            flight_id=str(uuid4()), booking_id=str(uuid4()), seat_count=0
        ),
    ],
)
def test_grpc_validation(stub, auth, message):
    method = {
        pb.SearchFlightsRequest: "SearchFlights",
        pb.GetFlightRequest: "GetFlight",
        pb.ReserveSeatsRequest: "ReserveSeats",
    }[type(message)]
    with pytest.raises(grpc.RpcError) as e:
        getattr(stub, method)(message, metadata=auth)
    assert e.value.code() == grpc.StatusCode.INVALID_ARGUMENT


def test_flight_unique_number_day_and_capacity(stub, auth, flight):
    value = flight[1]
    with pytest.raises(grpc.RpcError) as e:
        stub.CreateFlight(pb.CreateFlightRequest(flight=value), metadata=auth)
    assert e.value.code() == grpc.StatusCode.ALREADY_EXISTS
    booking_id = str(uuid4())
    stub.ReserveSeats(
        pb.ReserveSeatsRequest(
            flight_id=flight[0].id, booking_id=booking_id, seat_count=3
        ),
        metadata=auth,
    )
    value.total_seats = 2
    with pytest.raises(grpc.RpcError) as e:
        stub.UpdateFlight(
            pb.UpdateFlightRequest(flight_id=flight[0].id, flight=value), metadata=auth
        )
    assert e.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    stub.ReleaseReservation(
        pb.ReleaseReservationRequest(booking_id=booking_id), metadata=auth
    )


def test_reservation_idempotent_and_release_once(stub, auth, flight):
    f = flight[0]
    bid = str(uuid4())
    request = pb.ReserveSeatsRequest(flight_id=f.id, booking_id=bid, seat_count=2)
    first = stub.ReserveSeats(request, metadata=auth)
    second = stub.ReserveSeats(request, metadata=auth)
    assert first.id == second.id and seats(stub, auth, f.id) == 8
    request.seat_count = 1
    with pytest.raises(grpc.RpcError) as e:
        stub.ReserveSeats(request, metadata=auth)
    assert e.value.code() == grpc.StatusCode.ALREADY_EXISTS
    assert stub.ReleaseReservation(
        pb.ReleaseReservationRequest(booking_id=bid), metadata=auth
    ).changed
    assert not stub.ReleaseReservation(
        pb.ReleaseReservationRequest(booking_id=bid), metadata=auth
    ).changed
    assert seats(stub, auth, f.id) == 10


def test_cancel_fence_prevents_late_reserve(stub, auth, flight):
    bid = str(uuid4())
    stub.ReleaseReservation(pb.ReleaseReservationRequest(booking_id=bid), metadata=auth)
    with pytest.raises(grpc.RpcError) as e:
        stub.ReserveSeats(
            pb.ReserveSeatsRequest(
                flight_id=flight[0].id, booking_id=bid, seat_count=1
            ),
            metadata=auth,
        )
    assert e.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert seats(stub, auth, flight[0].id) == 10


def test_last_seat_race(stub, auth, flight):
    f, value = flight
    value.total_seats = 1
    stub.UpdateFlight(
        pb.UpdateFlightRequest(flight_id=f.id, flight=value), metadata=auth
    )

    def reserve(_):
        try:
            result = stub.ReserveSeats(
                pb.ReserveSeatsRequest(
                    flight_id=f.id, booking_id=str(uuid4()), seat_count=1
                ),
                metadata=auth,
            )
            return "OK", result.booking_id
        except grpc.RpcError as e:
            return e.code().name, None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, range(2)))
    assert sorted(r[0] for r in results) == ["OK", "RESOURCE_EXHAUSTED"]
    assert seats(stub, auth, f.id) == 0
    for _, id in results:
        if id:
            stub.ReleaseReservation(
                pb.ReleaseReservationRequest(booking_id=id), metadata=auth
            )


def test_concurrent_same_booking_reserves_once(stub, auth, flight):
    request = pb.ReserveSeatsRequest(
        flight_id=flight[0].id, booking_id=str(uuid4()), seat_count=2
    )
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(
            executor.map(
                lambda _: stub.ReserveSeats(request, metadata=auth).id, range(4)
            )
        )
    assert len(set(ids)) == 1 and seats(stub, auth, flight[0].id) == 8
    stub.ReleaseReservation(
        pb.ReleaseReservationRequest(booking_id=request.booking_id), metadata=auth
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("seat_count", 0),
        ("seat_count", 1.5),
        ("seat_count", "2"),
        ("seat_count", True),
        ("passenger_name", " "),
        ("passenger_email", "bad"),
        ("flight_id", "bad"),
        ("user_id", "bad"),
    ],
)
def test_rest_validation_before_grpc(api, body, stub, auth, field, value):
    flight_id = body["flight_id"]
    body[field] = value
    response = api.post("/bookings", json=body)
    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "VALIDATION_ERROR"
    assert seats(stub, auth, flight_id) == 10


def test_rest_booking_snapshot_list_cancel(api, body, flight, stub, auth):
    response = api.post("/bookings", json=body)
    assert response.status_code == 201, response.text
    booking = response.json()
    bid = booking["id"]
    assert Decimal(booking["total_price"]) == 2000
    assert seats(stub, auth, flight[0].id) == 8
    flight[1].price = "1500.00"
    stub.UpdateFlight(
        pb.UpdateFlightRequest(flight_id=flight[0].id, flight=flight[1]), metadata=auth
    )
    assert Decimal(api.get("/bookings/" + bid).json()["total_price"]) == 2000
    assert bid in [
        b["id"]
        for b in api.get("/bookings", params={"user_id": body["user_id"]}).json()
    ]
    response = api.post("/bookings/" + bid + "/cancel")
    assert response.status_code == 200 and response.json()["status"] == "CANCELLED"
    assert seats(stub, auth, flight[0].id) == 10
    assert api.post("/bookings/" + bid + "/cancel").status_code == 409


def test_no_booking_on_reserve_failure(api, body, database_urls, stub, auth):
    body["seat_count"] = 11
    key = str(uuid4())
    response = api.post("/bookings", json=body, headers={"Idempotency-Key": key})
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "INSUFFICIENT_SEATS"
    with psycopg.connect(database_urls["booking"]) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM bookings WHERE id=%s", (key,)
            ).fetchone()[0]
            == 0
        )
    assert seats(stub, auth, body["flight_id"]) == 10


def test_rest_idempotency_and_conflict(api, body, stub, auth):
    key = str(uuid4())
    a = api.post("/bookings", json=body, headers={"Idempotency-Key": key})
    b = api.post("/bookings", json=body, headers={"Idempotency-Key": key})
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"] == key
    body["seat_count"] = 1
    assert (
        api.post("/bookings", json=body, headers={"Idempotency-Key": key}).status_code
        == 409
    )
    assert seats(stub, auth, body["flight_id"]) == 8
    api.post("/bookings/" + key + "/cancel")


def test_lost_reserve_response_retried_without_double_decrement(
    api, body, stub, auth, database_urls
):
    key = str(uuid4())
    response = api.post(
        "/bookings",
        json=body,
        headers={"Idempotency-Key": key, "X-Test-Fault": "reserve-after-commit-once"},
    )
    assert response.status_code == 201, response.text
    assert seats(stub, auth, body["flight_id"]) == 8
    with psycopg.connect(database_urls["flight"]) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM seat_reservations WHERE booking_id=%s", (key,)
            ).fetchone()[0]
            == 1
        )
    api.post("/bookings/" + key + "/cancel")


def test_local_failure_compensates_remote_reservation(
    api, body, stub, auth, database_urls
):
    key = str(uuid4())
    response = api.post(
        "/bookings",
        json=body,
        headers={"Idempotency-Key": key, "X-Test-Fault": "booking-after-reserve"},
    )
    assert response.status_code == 503, response.text
    assert seats(stub, auth, body["flight_id"]) == 10
    with psycopg.connect(database_urls["booking"]) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM bookings WHERE id=%s", (key,)
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT state FROM booking_operations WHERE booking_id=%s", (key,)
            ).fetchone()[0]
            == "FAILED"
        )


def test_crashed_creation_recovered_from_durable_intent(
    api, body, stub, auth, database_urls
):
    key = str(uuid4())
    stub.ReserveSeats(
        pb.ReserveSeatsRequest(
            flight_id=body["flight_id"], booking_id=key, seat_count=2
        ),
        metadata=auth,
    )
    with psycopg.connect(database_urls["booking"]) as conn:
        conn.execute(
            "INSERT INTO booking_operations(booking_id,request_hash,state,created_at,updated_at) VALUES(%s,%s,'CREATING',clock_timestamp()-interval '10 seconds',clock_timestamp()-interval '10 seconds')",
            (key, "0" * 64),
        )
    wait_for(lambda: seats(stub, auth, body["flight_id"]) == 10)
    assert api.get("/bookings/" + key).status_code == 404


def test_crashed_cancellation_recovered(api, body, stub, auth, database_urls):
    booking = api.post("/bookings", json=body).json()
    key = booking["id"]
    stub.ReleaseReservation(pb.ReleaseReservationRequest(booking_id=key), metadata=auth)
    with psycopg.connect(database_urls["booking"]) as conn:
        conn.execute(
            "UPDATE booking_operations SET state='CANCELLING' WHERE booking_id=%s",
            (key,),
        )
    wait_for(lambda: api.get("/bookings/" + key).json()["status"] == "CANCELLED")
    assert seats(stub, auth, body["flight_id"]) == 10


def test_cache_ttl_invalidation_and_stale_epoch(stub, auth, flight):
    f, value = flight
    nodes = [
        (h, int(p))
        for h, p in (s.split(":") for s in os.environ["REDIS_SENTINELS"].split(","))
    ]
    cache = Sentinel(nodes, socket_timeout=1).master_for("flights")
    key = "flight:" + f.id
    stub.GetFlight(pb.GetFlightRequest(flight_id=f.id), metadata=auth)
    assert 0 < cache.ttl(key) <= 600
    old = cache.get(key)
    search_key = f"search:SVO:LED:{f.departure_time.ToDatetime().date().isoformat()}"
    stub.SearchFlights(
        pb.SearchFlightsRequest(
            origin="SVO",
            destination="LED",
            date=f.departure_time.ToDatetime().date().isoformat(),
        ),
        metadata=auth,
    )
    assert 0 < cache.ttl(search_key) <= 600
    value.price = "1250.00"
    stub.UpdateFlight(
        pb.UpdateFlightRequest(flight_id=f.id, flight=value), metadata=auth
    )
    assert cache.get(key) is None and cache.get(search_key) is None
    cache.set(key, old, ex=300)
    assert (
        stub.GetFlight(pb.GetFlightRequest(flight_id=f.id), metadata=auth).price
        == "1250.00"
    )
    bid = str(uuid4())
    stub.ReserveSeats(
        pb.ReserveSeatsRequest(flight_id=f.id, booking_id=bid, seat_count=1),
        metadata=auth,
    )
    assert cache.get(key) is None
    assert seats(stub, auth, f.id) == 9
    stub.ReleaseReservation(pb.ReleaseReservationRequest(booking_id=bid), metadata=auth)
    assert cache.get(key) is None
    assert seats(stub, auth, f.id) == 10


def test_only_scheduled_flights_searchable_and_bookable(stub, auth, flight):
    f, value = flight
    value.status = pb.CANCELLED
    stub.UpdateFlight(
        pb.UpdateFlightRequest(flight_id=f.id, flight=value), metadata=auth
    )
    result = stub.SearchFlights(
        pb.SearchFlightsRequest(origin="SVO", destination="LED"), metadata=auth
    )
    assert f.id not in [r.id for r in result.flights]
    with pytest.raises(grpc.RpcError) as e:
        stub.ReserveSeats(
            pb.ReserveSeatsRequest(
                flight_id=f.id, booking_id=str(uuid4()), seat_count=1
            ),
            metadata=auth,
        )
    assert e.value.code() == grpc.StatusCode.FAILED_PRECONDITION


def test_rest_not_found_and_required_filters(api):
    assert api.get("/bookings/" + str(uuid4())).status_code == 404
    assert api.get("/flights/" + str(uuid4())).status_code == 404
    assert api.get("/flights", params={"origin": "SVO"}).status_code == 400
    assert api.get("/bookings").status_code == 400


def test_database_constraints(database_urls, flight):
    with psycopg.connect(database_urls["flight"]) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "UPDATE flights SET available_seats=-1 WHERE id=%s", (flight[0].id,)
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE flights SET price=0 WHERE id=%s", (flight[0].id,))


def test_real_deadline_is_retried(stub, auth, flight):
    from services.booking.client import FlightClient

    client = FlightClient()
    try:
        result = client.stub.GetFlight(
            pb.GetFlightRequest(flight_id=flight[0].id),
            timeout=0.05,
            metadata=[("x-test-fault", "deadline-once")],
        )
        assert result.id == flight[0].id
        assert client.breaker.state == "CLOSED"
    finally:
        client.channel.close()
