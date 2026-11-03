import time
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated
from uuid import UUID, uuid4
import grpc
from fastapi import FastAPI, Query, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from google.protobuf.json_format import MessageToDict
from services.booking.models import (
    BookingCreate,
    BookingResponse,
    FlightResponse,
    ErrorResponse,
    ApiError,
)
from services.booking.client import FlightClient
from services.booking.service import Bookings
from services.booking.interceptors import CircuitOpen
from shared.db import pool
from shared.log import event


@asynccontextmanager
async def lifespan(app):
    app.state.pool = pool()
    app.state.client = FlightClient()
    app.state.bookings = Bookings(app.state.pool, app.state.client)
    app.state.bookings.start()
    event("booking_started", port=8080)
    yield
    app.state.bookings.close()
    app.state.client.channel.close()
    app.state.pool.close()


ERRORS = {code: {"model": ErrorResponse} for code in (400, 404, 409, 503, 500)}
app = FastAPI(
    title="Flight Booking — REST → gRPC",
    version="1.0.0",
    lifespan=lifespan,
    responses=ERRORS,
    description="Two independent databases. Money is encoded as decimal strings. Service API-key protects gRPC; user_id is supplied by the client, not end-user authentication. Idempotency-Key on POST /bookings is an optional UUID. Transient failures can require durable compensation; details/operation logs identify the booking.",
)


@app.middleware("http")
async def logs(request, call_next):
    request_id = str(uuid4())
    start = time.monotonic()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    event(
        "http_request",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=round((time.monotonic() - start) * 1000, 2),
    )
    return response


@app.exception_handler(ApiError)
async def api_error(request, error):
    return JSONResponse(
        status_code=error.status,
        content={
            "error_code": error.code,
            "message": error.message,
            "details": error.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation(request, error):
    fields = [
        {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
        for e in error.errors()
    ]
    return JSONResponse(
        status_code=400,
        content={
            "error_code": "VALIDATION_ERROR",
            "message": "Request validation failed",
            "details": {"violations": fields},
        },
    )


@app.exception_handler(grpc.RpcError)
async def grpc_error(request, error):
    codes = {
        grpc.StatusCode.NOT_FOUND: (404, "FLIGHT_NOT_FOUND"),
        grpc.StatusCode.RESOURCE_EXHAUSTED: (409, "INSUFFICIENT_SEATS"),
        grpc.StatusCode.INVALID_ARGUMENT: (400, "VALIDATION_ERROR"),
        grpc.StatusCode.FAILED_PRECONDITION: (409, "FLIGHT_CONFLICT"),
        grpc.StatusCode.ALREADY_EXISTS: (409, "RESERVATION_CONFLICT"),
        grpc.StatusCode.UNAUTHENTICATED: (503, "UPSTREAM_AUTHENTICATION_FAILED"),
        grpc.StatusCode.UNAVAILABLE: (503, "FLIGHT_UNAVAILABLE"),
        grpc.StatusCode.DEADLINE_EXCEEDED: (503, "FLIGHT_TIMEOUT"),
    }
    status, code = codes.get(error.code(), (503, "FLIGHT_SERVICE_ERROR"))
    if isinstance(error, CircuitOpen):
        code = "CIRCUIT_OPEN"
    return JSONResponse(
        status_code=status,
        content={
            "error_code": code,
            "message": error.details(),
            "details": {"grpc_code": error.code().name},
        },
    )


@app.exception_handler(Exception)
async def unexpected(request, error):
    event("http_internal_error", reason=type(error).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": "Internal booking service error",
            "details": None,
        },
    )


def to_dict(message):
    return MessageToDict(
        message,
        preserving_proto_field_name=True,
        always_print_fields_with_no_presence=True,
    )


@app.get("/health")
def health(request: Request):
    with request.app.state.pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok", "service": "booking"}


@app.get("/diagnostics")
def diagnostics(request: Request):
    return {"circuit_breaker": request.app.state.client.breaker.snapshot()}


@app.get("/flights", response_model=list[FlightResponse])
def search(
    request: Request,
    origin: Annotated[str, Query(pattern="^[A-Z]{3}$")],
    destination: Annotated[str, Query(pattern="^[A-Z]{3}$")],
    date: date | None = None,
):
    response = request.app.state.client.search(origin, destination, date)
    return [to_dict(f) for f in response.flights]


@app.get("/flights/{flight_id}", response_model=FlightResponse)
def get_flight(flight_id: UUID, request: Request):
    return to_dict(request.app.state.client.get(flight_id))


@app.post("/bookings", response_model=BookingResponse, status_code=201)
def create(
    body: BookingCreate,
    request: Request,
    idempotency_key: Annotated[UUID | None, Header()] = None,
    x_test_fault: Annotated[str | None, Header(include_in_schema=False)] = None,
):
    return request.app.state.bookings.create(body, idempotency_key, x_test_fault)


@app.get("/bookings", response_model=list[BookingResponse])
def list_bookings(user_id: UUID, request: Request):
    return request.app.state.bookings.list(user_id)


@app.get("/bookings/{booking_id}", response_model=BookingResponse)
def get_booking(booking_id: UUID, request: Request):
    return request.app.state.bookings.get(booking_id)


@app.post("/bookings/{booking_id}/cancel", response_model=BookingResponse)
def cancel(booking_id: UUID, request: Request):
    return request.app.state.bookings.cancel(booking_id)


def openapi():
    if app.openapi_schema is None:
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        for path in schema["paths"].values():
            for operation in path.values():
                if isinstance(operation, dict):
                    operation.get("responses", {}).pop("422", None)
        app.openapi_schema = schema
    return app.openapi_schema


app.openapi = openapi
