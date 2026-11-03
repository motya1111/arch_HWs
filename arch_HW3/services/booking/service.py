import os
import hashlib
import json
import threading
from decimal import Decimal
from uuid import uuid4
from shared.db import operation_lock
from shared.log import event
from services.booking.models import ApiError


class Bookings:
    def __init__(self, pool, client):
        self.pool, self.client = pool, client
        self.stop = threading.Event()
        self.thread = None
        self.grace = float(os.getenv("RECOVERY_GRACE_SECONDS", "5"))
        self.faults = os.getenv("TEST_FAULTS_ENABLED") == "1"

    def get(self, booking_id):
        with self.pool.connection() as conn:
            row = conn.execute(
                "SELECT * FROM bookings WHERE id=%s", (booking_id,)
            ).fetchone()
        if not row:
            raise ApiError(404, "BOOKING_NOT_FOUND", "Booking not found")
        return row

    def list(self, user_id):
        with self.pool.connection() as conn:
            return conn.execute(
                "SELECT * FROM bookings WHERE user_id=%s ORDER BY created_at,id",
                (user_id,),
            ).fetchall()

    def _state(self, conn, booking_id, state, error=None):
        conn.execute(
            "UPDATE booking_operations SET state=%s,last_error=%s WHERE booking_id=%s",
            (state, str(error)[:500] if error else None, booking_id),
        )
        conn.commit()

    def create(self, request, booking_id=None, fault=None):
        booking_id = booking_id or uuid4()
        payload = request.model_dump(mode="json")
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        with self.pool.connection() as conn, operation_lock(conn, booking_id):
            op = conn.execute(
                "SELECT * FROM booking_operations WHERE booking_id=%s", (booking_id,)
            ).fetchone()
            if op:
                if op["request_hash"] != fingerprint:
                    raise ApiError(
                        409,
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key was used with another request",
                    )
                if op["state"] in ("CONFIRMED", "CANCELLED"):
                    return self.get(booking_id)
                raise ApiError(
                    409,
                    "BOOKING_OPERATION_PENDING"
                    if op["state"] != "FAILED"
                    else "BOOKING_OPERATION_FAILED",
                    "Use GET to inspect the booking, or a new Idempotency-Key after a failed operation",
                    {"booking_id": str(booking_id)},
                )
            conn.execute(
                "INSERT INTO booking_operations(booking_id,request_hash,state) VALUES(%s,%s,'CREATING')",
                (booking_id, fingerprint),
            )
            conn.commit()
            reserve_sent = False
            try:
                quote = self.client.get(request.flight_id)
                reserve_sent = True
                self.client.reserve(
                    request.flight_id,
                    request.seat_count,
                    booking_id,
                    quote.price,
                    fault
                    if self.faults and fault == "reserve-after-commit-once"
                    else None,
                )
                if self.faults and fault == "booking-after-reserve":
                    raise ApiError(
                        503,
                        "INJECTED_BOOKING_FAILURE",
                        "Injected failure before booking commit",
                    )
                total = Decimal(quote.price) * request.seat_count
                with conn.transaction():
                    row = conn.execute(
                        "INSERT INTO bookings(id,user_id,flight_id,passenger_name,passenger_email,seat_count,total_price,status) VALUES(%s,%s,%s,%s,%s,%s,%s,'CONFIRMED') RETURNING *",
                        (
                            booking_id,
                            request.user_id,
                            request.flight_id,
                            request.passenger_name,
                            str(request.passenger_email),
                            request.seat_count,
                            total,
                        ),
                    ).fetchone()
                    conn.execute(
                        "UPDATE booking_operations SET state='CONFIRMED',last_error=NULL WHERE booking_id=%s",
                        (booking_id,),
                    )
                event(
                    "booking_confirmed",
                    booking_id=booking_id,
                    seat_count=request.seat_count,
                    total_price=str(total),
                )
                return row
            except Exception as exc:
                conn.rollback()
                self._state(
                    conn,
                    booking_id,
                    "COMPENSATING" if reserve_sent else "FAILED",
                    type(exc).__name__,
                )
                if reserve_sent:
                    try:
                        self.client.release(booking_id)
                        self._state(conn, booking_id, "FAILED")
                        event("booking_compensated", booking_id=booking_id)
                    except Exception as release_error:
                        event(
                            "compensation_pending",
                            booking_id=booking_id,
                            reason=type(release_error).__name__,
                        )
                raise

    def cancel(self, booking_id):
        with self.pool.connection() as conn, operation_lock(conn, booking_id):
            row = conn.execute(
                "SELECT * FROM bookings WHERE id=%s FOR UPDATE", (booking_id,)
            ).fetchone()
            if not row:
                raise ApiError(404, "BOOKING_NOT_FOUND", "Booking not found")
            if row["status"] != "CONFIRMED":
                raise ApiError(
                    409,
                    "INVALID_BOOKING_STATE",
                    "Only CONFIRMED bookings can be cancelled",
                )
            self._state(conn, booking_id, "CANCELLING")
            self.client.release(booking_id)
            with conn.transaction():
                row = conn.execute(
                    "UPDATE bookings SET status='CANCELLED' WHERE id=%s RETURNING *",
                    (booking_id,),
                ).fetchone()
                conn.execute(
                    "UPDATE booking_operations SET state='CANCELLED',last_error=NULL WHERE booking_id=%s",
                    (booking_id,),
                )
            event("booking_cancelled", booking_id=booking_id)
            return row

    def recover_once(self):
        with self.pool.connection() as conn:
            candidates = conn.execute(
                "SELECT booking_id FROM booking_operations WHERE state IN ('COMPENSATING','CANCELLING') OR (state='CREATING' AND updated_at<clock_timestamp()-(%s * interval '1 second')) ORDER BY updated_at LIMIT 50",
                (self.grace,),
            ).fetchall()
        for item in candidates:
            booking_id = item["booking_id"]
            with (
                self.pool.connection() as conn,
                operation_lock(conn, booking_id, blocking=False) as acquired,
            ):
                if not acquired:
                    continue
                op = conn.execute(
                    "SELECT state FROM booking_operations WHERE booking_id=%s",
                    (booking_id,),
                ).fetchone()
                conn.commit()
                if not op or op["state"] not in (
                    "CREATING",
                    "COMPENSATING",
                    "CANCELLING",
                ):
                    continue
                try:
                    self.client.release(booking_id)
                    with conn.transaction():
                        target = "FAILED"
                        if op["state"] == "CANCELLING":
                            conn.execute(
                                "UPDATE bookings SET status='CANCELLED' WHERE id=%s",
                                (booking_id,),
                            )
                            target = "CANCELLED"
                        conn.execute(
                            "UPDATE booking_operations SET state=%s,last_error=NULL WHERE booking_id=%s",
                            (target, booking_id),
                        )
                    event("operation_recovered", booking_id=booking_id, state=target)
                except Exception as exc:
                    conn.rollback()
                    event(
                        "recovery_deferred",
                        booking_id=booking_id,
                        reason=type(exc).__name__,
                    )

    def start(self):
        def run():
            while not self.stop.wait(1):
                try:
                    self.recover_once()
                except Exception as exc:
                    event("recovery_worker_error", reason=type(exc).__name__)

        self.thread = threading.Thread(target=run, name="booking-recovery", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=40)
