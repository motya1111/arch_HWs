import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import grpc
import httpx
import psycopg
import pytest
from google.protobuf.timestamp_pb2 import Timestamp
from flights.v1 import flight_pb2 as pb, flight_pb2_grpc as rpc


@pytest.fixture(scope="session")
def database_urls():
    urls = {
        name: os.environ[f"{name.upper()}_DATABASE_URL"]
        for name in ("flight", "booking")
    }
    for name, url in urls.items():
        with psycopg.connect(url) as conn:
            assert (
                conn.execute("SELECT current_database()").fetchone()[0]
                == name + "_test"
            )
    return urls


@pytest.fixture(scope="session")
def stub(database_urls):
    with grpc.insecure_channel(
        os.getenv("FLIGHT_GRPC_TARGET", "flight:50051")
    ) as channel:
        yield rpc.FlightServiceStub(channel)


@pytest.fixture(scope="session")
def auth():
    return [("x-api-key", os.environ["GRPC_API_KEY"])]


@pytest.fixture(scope="session")
def api(database_urls):
    with httpx.Client(
        base_url=os.getenv("BOOKING_BASE_URL", "http://booking:8080"), timeout=20
    ) as client:
        yield client


@pytest.fixture
def flight(stub, auth):
    start = datetime.now(timezone.utc) + timedelta(days=40)
    t1, t2 = Timestamp(), Timestamp()
    t1.FromDatetime(start)
    t2.FromDatetime(start + timedelta(hours=2))
    value = pb.FlightInput(
        airline_code="TE",
        airline_name="Test Air",
        flight_number="T" + uuid4().hex[:10].upper(),
        origin="SVO",
        destination="LED",
        departure_time=t1,
        arrival_time=t2,
        total_seats=10,
        price="1000.00",
        status=pb.SCHEDULED,
    )
    return stub.CreateFlight(
        pb.CreateFlightRequest(flight=value), metadata=auth, timeout=5
    ), value


@pytest.fixture
def body(flight):
    return {
        "user_id": str(uuid4()),
        "flight_id": flight[0].id,
        "passenger_name": "Test Passenger",
        "passenger_email": "test@example.com",
        "seat_count": 2,
    }
