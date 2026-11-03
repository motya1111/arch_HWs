import os
import grpc
from flights.v1 import flight_pb2 as pb, flight_pb2_grpc as rpc
from services.booking.interceptors import (
    CircuitBreaker,
    CircuitInterceptor,
    RetryInterceptor,
    ApiKeyInterceptor,
)


class FlightClient:
    def __init__(self):
        self.timeout = float(os.getenv("GRPC_TIMEOUT_SECONDS", "1"))
        if not 0.05 <= self.timeout <= 10:
            raise ValueError("GRPC_TIMEOUT_SECONDS must be 0.05..10")
        self.breaker = CircuitBreaker(
            int(os.getenv("CB_FAILURE_THRESHOLD", "5")),
            float(os.getenv("CB_WINDOW_SECONDS", "30")),
            float(os.getenv("CB_RESET_SECONDS", "10")),
        )
        raw = grpc.insecure_channel(
            os.getenv("FLIGHT_GRPC_TARGET", "flight:50051"),
            options=[
                ("grpc.enable_retries", 0),
                ("grpc.initial_reconnect_backoff_ms", 100),
                ("grpc.min_reconnect_backoff_ms", 100),
                ("grpc.max_reconnect_backoff_ms", 1000),
            ],
        )
        self.channel = grpc.intercept_channel(
            raw,
            CircuitInterceptor(self.breaker),
            RetryInterceptor(
                int(os.getenv("GRPC_MAX_ATTEMPTS", "3")),
                float(os.getenv("GRPC_BACKOFF_SECONDS", "0.1")),
            ),
            ApiKeyInterceptor(os.environ["GRPC_API_KEY"]),
        )
        self.stub = rpc.FlightServiceStub(self.channel)

    def get(self, flight_id):
        return self.stub.GetFlight(
            pb.GetFlightRequest(flight_id=str(flight_id)), timeout=self.timeout
        )

    def search(self, origin, destination, date=None):
        request = pb.SearchFlightsRequest(origin=origin, destination=destination)
        if date is not None:
            request.date = str(date)
        return self.stub.SearchFlights(request, timeout=self.timeout)

    def reserve(self, flight_id, count, booking_id, price, fault=None):
        metadata = [("x-test-fault", fault)] if fault else None
        return self.stub.ReserveSeats(
            pb.ReserveSeatsRequest(
                flight_id=str(flight_id),
                seat_count=count,
                booking_id=str(booking_id),
                expected_price=price,
            ),
            timeout=self.timeout,
            metadata=metadata,
        )

    def release(self, booking_id):
        return self.stub.ReleaseReservation(
            pb.ReleaseReservationRequest(booking_id=str(booking_id)),
            timeout=self.timeout,
        )
