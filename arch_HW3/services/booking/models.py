from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class BookingCreate(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "user_id": "00000000-0000-0000-0000-000000000101",
                "flight_id": "00000000-0000-0000-0000-000000000001",
                "passenger_name": "Ivan Petrov",
                "passenger_email": "ivan@example.com",
                "seat_count": 2,
            }
        },
    )
    user_id: UUID
    flight_id: UUID
    passenger_name: Annotated[str, Field(min_length=1, max_length=255)]
    passenger_email: Annotated[EmailStr, Field(max_length=254)]
    seat_count: Annotated[int, Field(strict=True, ge=1, le=1000)]

    @field_validator("passenger_name")
    @classmethod
    def name(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError(
                "passenger_name must be nonblank and contain no null character"
            )
        return value


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class BookingResponse(BaseModel):
    id: UUID
    user_id: UUID
    flight_id: UUID
    passenger_name: str
    passenger_email: EmailStr
    seat_count: int
    total_price: Decimal
    status: BookingStatus
    created_at: datetime
    updated_at: datetime


class ErrorResponse(BaseModel):
    error_code: str
    message: str
    details: dict | None = None


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        self.status, self.code, self.message, self.details = (
            status,
            code,
            message,
            details,
        )


class FlightResponse(BaseModel):
    id: UUID
    airline_code: str
    airline_name: str
    flight_number: str
    origin: str
    destination: str
    departure_time: datetime
    arrival_time: datetime
    total_seats: int
    available_seats: int
    price: Decimal
    status: str
