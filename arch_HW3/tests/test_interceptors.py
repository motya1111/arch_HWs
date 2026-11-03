import grpc
import pytest
from types import SimpleNamespace
from services.booking.interceptors import (
    CircuitBreaker,
    CircuitOpen,
    CircuitInterceptor,
    RetryInterceptor,
)


class Failure(grpc.RpcError):
    def __init__(self, code):
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return "test failure"


class Call:
    def __init__(self, code=None):
        self.code = code

    def result(self):
        if self.code:
            raise Failure(self.code)
        return "ok"


def test_closed_open_single_probe_and_recovery():
    now = [0]
    breaker = CircuitBreaker(2, 30, 10, clock=lambda: now[0])
    breaker.after(breaker.before(), True)
    breaker.after(breaker.before(), True)
    assert breaker.state == "OPEN"
    with pytest.raises(CircuitOpen):
        breaker.before()
    now[0] = 10
    permit = breaker.before()
    assert breaker.state == "HALF_OPEN"
    with pytest.raises(CircuitOpen):
        breaker.before()
    breaker.after(permit, False)
    assert breaker.state == "CLOSED"


def test_failed_probe_reopens():
    now = [0]
    b = CircuitBreaker(1, 30, 1, clock=lambda: now[0])
    b.after(b.before(), True)
    now[0] = 1
    b.after(b.before(), True)
    assert b.state == "OPEN"


def test_old_inflight_success_cannot_close_new_open_generation():
    b = CircuitBreaker(1)
    old = b.before()
    b.after(b.before(), True)
    b.after(old, False)
    assert b.state == "OPEN"


def test_window_and_success_reset():
    now = [0]
    b = CircuitBreaker(2, 5, 10, clock=lambda: now[0])
    b.after(b.before(), True)
    now[0] = 6
    b.after(b.before(), True)
    assert b.state == "CLOSED"
    b.after(b.before(), False)
    assert not b.failures


@pytest.mark.parametrize(
    "status", [grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED]
)
def test_retry_exactly_three_attempts_exponential_backoff(status):
    calls = []
    delays = []

    def continuation(details, request):
        calls.append(1)
        return Call(status)

    RetryInterceptor(3, 0.1, delays.append).intercept_unary_unary(
        continuation, SimpleNamespace(method="/test"), object()
    )
    assert len(calls) == 3
    assert delays == [0.1, 0.2]


@pytest.mark.parametrize(
    "status",
    [
        grpc.StatusCode.INVALID_ARGUMENT,
        grpc.StatusCode.NOT_FOUND,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.StatusCode.FAILED_PRECONDITION,
        grpc.StatusCode.UNAUTHENTICATED,
    ],
)
def test_no_retry_for_business_errors(status):
    calls = []

    def continuation(details, request):
        calls.append(1)
        return Call(status)

    RetryInterceptor(
        3, 0.1, lambda _: pytest.fail("unexpected sleep")
    ).intercept_unary_unary(continuation, SimpleNamespace(method="/test"), object())
    assert len(calls) == 1


def test_retry_recovers_on_second_attempt():
    calls = []

    def continuation(details, request):
        calls.append(1)
        return Call(grpc.StatusCode.UNAVAILABLE if len(calls) == 1 else None)

    result = RetryInterceptor(3, 0, lambda _: None).intercept_unary_unary(
        continuation, SimpleNamespace(method="/test"), object()
    )
    assert result.result() == "ok" and len(calls) == 2


def test_open_interceptor_makes_no_network_call():
    b = CircuitBreaker(1)
    b.after(b.before(), True)
    with pytest.raises(CircuitOpen):
        CircuitInterceptor(b).intercept_unary_unary(
            lambda *_: pytest.fail("network call while OPEN"), None, None
        )


def test_business_error_does_not_open_circuit():
    b = CircuitBreaker(1)
    CircuitInterceptor(b).intercept_unary_unary(
        lambda *_: Call(grpc.StatusCode.RESOURCE_EXHAUSTED), None, None
    )
    assert b.state == "CLOSED"
