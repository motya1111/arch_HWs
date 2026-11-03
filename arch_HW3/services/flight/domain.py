import re
from datetime import timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from flights.v1 import flight_pb2 as pb


class Fault(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def invalid(message):
    raise Fault(grpc.StatusCode.INVALID_ARGUMENT, message)


def uuid(value, field):
    try:
        parsed = UUID(value)
        if str(parsed) != value.lower():
            raise ValueError()
        return parsed
    except (ValueError, TypeError, AttributeError):
        invalid(f"{field} must be a canonical UUID")


def route(origin, destination):
    if (
        not re.fullmatch("[A-Z]{3}", origin)
        or not re.fullmatch("[A-Z]{3}", destination)
        or origin == destination
    ):
        invalid("origin/destination must be distinct uppercase IATA codes")


def money(value):
    try:
        number = Decimal(value)
        if (
            not number.is_finite()
            or number <= 0
            or number > Decimal("9999999999.99")
            or number != number.quantize(Decimal(".01"))
        ):
            raise ValueError()
        return number
    except (InvalidOperation, ValueError):
        invalid("price must be positive decimal with at most 2 fractional digits")


def timestamp(value):
    result = Timestamp()
    result.FromDatetime(value)
    return result


def flight(row):
    return pb.Flight(
        id=str(row["id"]),
        airline_code=row["airline_code"],
        airline_name=row["airline_name"],
        flight_number=row["flight_number"],
        origin=row["origin"],
        destination=row["destination"],
        departure_time=timestamp(row["departure_time"]),
        arrival_time=timestamp(row["arrival_time"]),
        total_seats=row["total_seats"],
        available_seats=row["available_seats"],
        price=str(row["price"]),
        status=pb.FlightStatus.Value(row["status"]),
    )


def reservation(row):
    return pb.SeatReservation(
        id=str(row["id"]),
        booking_id=str(row["booking_id"]),
        flight_id=str(row["flight_id"]),
        seat_count=row["seat_count"],
        status=pb.ReservationStatus.Value(row["status"]),
        price_at_reservation=str(row["price_at_reservation"]),
        created_at=timestamp(row["created_at"]),
    )


SELECT = "SELECT f.*, (f.departure_time AT TIME ZONE 'UTC')::date AS departure_date, a.name AS airline_name FROM flights f JOIN airlines a ON a.code=f.airline_code"


def get(conn, flight_id, lock=False):
    row = conn.execute(
        SELECT + " WHERE f.id=%s" + (" FOR UPDATE OF f" if lock else ""), (flight_id,)
    ).fetchone()
    if not row:
        raise Fault(grpc.StatusCode.NOT_FOUND, "Flight not found")
    return row


def validate_input(value):
    route(value.origin, value.destination)
    if (
        not re.fullmatch("[A-Z0-9]{2,3}", value.airline_code)
        or not value.airline_name.strip()
        or len(value.airline_name) > 200
        or "\x00" in value.airline_name
    ):
        invalid("invalid airline code or name")
    if not re.fullmatch("[A-Z0-9]{2,12}", value.flight_number):
        invalid("invalid flight_number")
    if value.status not in (pb.SCHEDULED, pb.DEPARTED, pb.CANCELLED, pb.COMPLETED):
        invalid("status is required")
    if not 1 <= value.total_seats <= 1000000:
        invalid("total_seats must be 1..1000000")
    try:
        start = value.departure_time.ToDatetime(tzinfo=timezone.utc)
        end = value.arrival_time.ToDatetime(tzinfo=timezone.utc)
        if (
            not value.HasField("departure_time")
            or not value.HasField("arrival_time")
            or end <= start
        ):
            raise ValueError()
    except (ValueError, OverflowError):
        invalid(
            "arrival_time must be after departure_time; both timestamps are required"
        )
    return start, end, money(value.price)
