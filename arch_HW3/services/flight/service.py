from datetime import date
from uuid import uuid4
import grpc
from flights.v1 import flight_pb2 as pb, flight_pb2_grpc as rpc
from services.flight.domain import (
    Fault,
    invalid,
    uuid,
    route,
    money,
    flight,
    reservation,
    get,
    validate_input,
    SELECT,
)


class FlightService(rpc.FlightServiceServicer):
    def __init__(self, pool, cache):
        self.pool, self.cache = pool, cache

    def _epoch(self, conn, write=False):
        return conn.execute(
            "SELECT version FROM cache_epoch WHERE id=1 FOR "
            + ("UPDATE" if write else "SHARE")
        ).fetchone()["version"]

    def _changed(self, conn, row, old=None):
        conn.execute("UPDATE cache_epoch SET version=version+1 WHERE id=1")
        rows = [row] + ([old] if old else [])
        self.cache.invalidate(
            row["id"],
            [(r["origin"], r["destination"], str(r["departure_date"])) for r in rows],
        )

    def SearchFlights(self, request, context):
        route(request.origin, request.destination)
        day = None
        if request.HasField("date"):
            try:
                day = date.fromisoformat(request.date)
                if day.isoformat() != request.date:
                    raise ValueError()
            except ValueError:
                invalid("date must be YYYY-MM-DD")
        key = f"search:{request.origin}:{request.destination}:{day or 'any'}"
        cached = self.cache.read(key)
        with self.pool.connection() as conn:
            epoch = self._epoch(conn)

            def load():
                query = (
                    SELECT
                    + " WHERE f.origin=%s AND f.destination=%s AND f.status='SCHEDULED'"
                )
                args = [request.origin, request.destination]
                if day:
                    query += " AND (f.departure_time AT TIME ZONE 'UTC')::date=%s"
                    args.append(day)
                rows = conn.execute(
                    query + " ORDER BY f.departure_time,f.id", args
                ).fetchall()
                return pb.SearchFlightsResponse(flights=[flight(r) for r in rows])

            return self.cache.resolve(
                key, cached, epoch, pb.SearchFlightsResponse, load
            )

    def GetFlight(self, request, context):
        flight_id = uuid(request.flight_id, "flight_id")
        key = f"flight:{flight_id}"
        cached = self.cache.read(key)
        with self.pool.connection() as conn:
            epoch = self._epoch(conn)
            return self.cache.resolve(
                key, cached, epoch, pb.Flight, lambda: flight(get(conn, flight_id))
            )

    def ReserveSeats(self, request, context):
        flight_id, booking_id = (
            uuid(request.flight_id, "flight_id"),
            uuid(request.booking_id, "booking_id"),
        )
        if not 1 <= request.seat_count <= 1000:
            invalid("seat_count must be 1..1000")
        expected = (
            money(request.expected_price)
            if request.HasField("expected_price")
            else None
        )
        with self.pool.connection() as conn:
            self._epoch(conn, True)
            if conn.execute(
                "SELECT 1 FROM reservation_cancellations WHERE booking_id=%s",
                (booking_id,),
            ).fetchone():
                raise Fault(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Reservation was already cancelled",
                )
            existing = conn.execute(
                "SELECT * FROM seat_reservations WHERE booking_id=%s", (booking_id,)
            ).fetchone()
            if existing:
                if (
                    existing["flight_id"] != flight_id
                    or existing["seat_count"] != request.seat_count
                ):
                    raise Fault(
                        grpc.StatusCode.ALREADY_EXISTS,
                        "booking_id was used with different reservation inputs",
                    )
                if existing["status"] != "ACTIVE":
                    raise Fault(
                        grpc.StatusCode.FAILED_PRECONDITION, "Reservation is not ACTIVE"
                    )
                return reservation(existing)
            row = get(conn, flight_id, True)
            if row["status"] != "SCHEDULED":
                raise Fault(
                    grpc.StatusCode.FAILED_PRECONDITION, "Flight is not SCHEDULED"
                )
            if expected is not None and expected != row["price"]:
                raise Fault(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Flight price changed; request a new quote",
                )
            if row["available_seats"] < request.seat_count:
                raise Fault(
                    grpc.StatusCode.RESOURCE_EXHAUSTED, "Not enough available seats"
                )
            conn.execute(
                "UPDATE flights SET available_seats=available_seats-%s WHERE id=%s",
                (request.seat_count, flight_id),
            )
            saved = conn.execute(
                "INSERT INTO seat_reservations(id,booking_id,flight_id,seat_count,status,price_at_reservation) VALUES(%s,%s,%s,%s,'ACTIVE',%s) RETURNING *",
                (uuid4(), booking_id, flight_id, request.seat_count, row["price"]),
            ).fetchone()
            self._changed(conn, row)
            result = reservation(saved)
        return result

    def ReleaseReservation(self, request, context):
        booking_id = uuid(request.booking_id, "booking_id")
        with self.pool.connection() as conn:
            self._epoch(conn, True)
            conn.execute(
                "INSERT INTO reservation_cancellations(booking_id) VALUES(%s) ON CONFLICT DO NOTHING",
                (booking_id,),
            )
            saved = conn.execute(
                "SELECT * FROM seat_reservations WHERE booking_id=%s FOR UPDATE",
                (booking_id,),
            ).fetchone()
            changed = bool(saved and saved["status"] == "ACTIVE")
            if changed:
                row = get(conn, saved["flight_id"], True)
                conn.execute(
                    "UPDATE flights SET available_seats=available_seats+%s WHERE id=%s",
                    (saved["seat_count"], saved["flight_id"]),
                )
                conn.execute(
                    "UPDATE seat_reservations SET status='RELEASED' WHERE booking_id=%s",
                    (booking_id,),
                )
                self._changed(conn, row)
        return pb.ReleaseReservationResponse(
            booking_id=str(booking_id), status=pb.RELEASED, changed=changed
        )

    def CreateFlight(self, request, context):
        start, end, price = validate_input(request.flight)
        v = request.flight
        with self.pool.connection() as conn:
            self._epoch(conn, True)
            conn.execute(
                "INSERT INTO airlines(code,name) VALUES(%s,%s) ON CONFLICT(code) DO UPDATE SET name=excluded.name",
                (v.airline_code, v.airline_name),
            )
            flight_id = uuid4()
            conn.execute(
                "INSERT INTO flights(id,airline_code,flight_number,origin,destination,departure_time,arrival_time,total_seats,available_seats,price,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    flight_id,
                    v.airline_code,
                    v.flight_number,
                    v.origin,
                    v.destination,
                    start,
                    end,
                    v.total_seats,
                    v.total_seats,
                    price,
                    pb.FlightStatus.Name(v.status),
                ),
            )
            row = get(conn, flight_id)
            self._changed(conn, row)
            result = flight(row)
        return result

    def UpdateFlight(self, request, context):
        flight_id = uuid(request.flight_id, "flight_id")
        start, end, price = validate_input(request.flight)
        v = request.flight
        with self.pool.connection() as conn:
            self._epoch(conn, True)
            old = get(conn, flight_id, True)
            reserved = old["total_seats"] - old["available_seats"]
            if v.total_seats < reserved:
                raise Fault(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Capacity is below reserved seat count",
                )
            conn.execute(
                "INSERT INTO airlines(code,name) VALUES(%s,%s) ON CONFLICT(code) DO UPDATE SET name=excluded.name",
                (v.airline_code, v.airline_name),
            )
            conn.execute(
                "UPDATE flights SET airline_code=%s,flight_number=%s,origin=%s,destination=%s,departure_time=%s,arrival_time=%s,total_seats=%s,available_seats=%s,price=%s,status=%s WHERE id=%s",
                (
                    v.airline_code,
                    v.flight_number,
                    v.origin,
                    v.destination,
                    start,
                    end,
                    v.total_seats,
                    v.total_seats - reserved,
                    price,
                    pb.FlightStatus.Name(v.status),
                    flight_id,
                ),
            )
            row = get(conn, flight_id)
            self._changed(conn, row, old)
            result = flight(row)
        return result

    def Health(self, request, context):
        with self.pool.connection() as conn:
            conn.execute("SELECT 1")
        return pb.HealthResponse(database_ok=True, cache_ok=self.cache.healthy())
