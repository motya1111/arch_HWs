import hmac
import os
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import grpc
import psycopg
from psycopg_pool import PoolTimeout
from flights.v1 import flight_pb2_grpc as rpc
from services.flight.domain import Fault
from services.flight.service import FlightService
from services.flight.cache import Cache
from shared.db import pool
from shared.log import event


class Middleware(grpc.ServerInterceptor):
    def __init__(self):
        self.key = os.environ["GRPC_API_KEY"]
        if len(self.key) < 16:
            raise ValueError("GRPC_API_KEY must contain at least 16 characters")
        self.faults = os.getenv("TEST_FAULTS_ENABLED") == "1"
        self.once = set()
        self.lock = threading.Lock()

    def intercept_service(self, continuation, details):
        handler = continuation(details)
        if handler is None or handler.unary_unary is None:
            return handler

        def invoke(request, context):
            metadata = list(context.invocation_metadata())
            keys = [v for k, v in metadata if k == "x-api-key"]
            if len(keys) != 1 or not hmac.compare_digest(keys[0], self.key):
                event("grpc_rejected", method=details.method, status="UNAUTHENTICATED")
                context.abort(
                    grpc.StatusCode.UNAUTHENTICATED, "Valid service API key required"
                )
            fault = dict(metadata).get("x-test-fault", "") if self.faults else ""
            started = time.monotonic()
            try:
                if fault == "unavailable":
                    raise Fault(
                        grpc.StatusCode.UNAVAILABLE, "Injected transport outage"
                    )
                if fault == "deadline-once" and details.method.endswith("/GetFlight"):
                    token = "deadline:" + request.flight_id
                    with self.lock:
                        inject = token not in self.once
                        self.once.add(token)
                    if inject:
                        time.sleep(0.25)
                result = handler.unary_unary(request, context)
                if fault == "reserve-after-commit-once" and details.method.endswith(
                    "/ReserveSeats"
                ):
                    with self.lock:
                        inject = request.booking_id not in self.once
                        self.once.add(request.booking_id)
                    if inject:
                        event("fault_after_commit", booking_id=request.booking_id)
                        raise Fault(
                            grpc.StatusCode.UNAVAILABLE,
                            "Injected lost response after commit",
                        )
                event(
                    "grpc_request",
                    method=details.method,
                    status="OK",
                    duration_ms=round((time.monotonic() - started) * 1000, 2),
                )
                return result
            except Fault as exc:
                event(
                    "grpc_request",
                    method=details.method,
                    status=exc.code.name,
                    message=exc.message,
                )
                context.abort(exc.code, exc.message)
            except psycopg.errors.UniqueViolation:
                context.abort(
                    grpc.StatusCode.ALREADY_EXISTS,
                    "Flight number and UTC departure day must be unique",
                )
            except (psycopg.OperationalError, PoolTimeout) as exc:
                event("database_unavailable", reason=type(exc).__name__)
                context.abort(
                    grpc.StatusCode.UNAVAILABLE, "Flight database is unavailable"
                )
            except Exception as exc:
                event(
                    "grpc_internal_error",
                    method=details.method,
                    reason=type(exc).__name__,
                )
                context.abort(grpc.StatusCode.INTERNAL, "Internal flight service error")

        return grpc.unary_unary_rpc_method_handler(
            invoke,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


def main():
    database = pool()
    server = grpc.server(
        ThreadPoolExecutor(max_workers=24), interceptors=[Middleware()]
    )
    rpc.add_FlightServiceServicer_to_server(FlightService(database, Cache()), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    event("flight_started", port=50051)

    def stop(*_):
        server.stop(5).wait()
        database.close()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    server.wait_for_termination()


if __name__ == "__main__":
    main()
