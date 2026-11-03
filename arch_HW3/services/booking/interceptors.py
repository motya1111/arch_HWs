import collections
import threading
import time
import grpc
from shared.log import event

TRANSIENT = {grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED}


class CircuitOpen(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNAVAILABLE

    def details(self):
        return "Flight circuit is OPEN; retry after the recovery interval"


class CircuitBreaker:
    def __init__(self, threshold=5, window=30, reset=10, clock=time.monotonic):
        if threshold < 1 or window <= 0 or reset <= 0:
            raise ValueError("Circuit breaker parameters must be positive")
        self.threshold, self.window, self.reset, self.clock = (
            threshold,
            window,
            reset,
            clock,
        )
        self.state = "CLOSED"
        self.failures = collections.deque()
        self.opened = 0
        self.generation = 0
        self.lock = threading.Lock()

    def _transition(self, state):
        event("circuit_transition", previous=self.state, current=state)
        self.state = state
        self.generation += 1

    def before(self):
        with self.lock:
            if self.state == "OPEN":
                if self.clock() - self.opened < self.reset:
                    raise CircuitOpen()
                self._transition("HALF_OPEN")
                return self.generation, True
            if self.state == "HALF_OPEN":
                raise CircuitOpen()
            return self.generation, False

    def after(self, permit, failed):
        generation, probe = permit
        with self.lock:
            if generation != self.generation:
                return
            now = self.clock()
            if not failed:
                self.failures.clear()
                if probe:
                    self._transition("CLOSED")
                return
            if probe:
                self.opened = now
                self._transition("OPEN")
                return
            self.failures.append(now)
            while self.failures and self.failures[0] < now - self.window:
                self.failures.popleft()
            if len(self.failures) >= self.threshold:
                self.opened = now
                self._transition("OPEN")

    def snapshot(self):
        with self.lock:
            return {
                "state": self.state,
                "failure_count": len(self.failures),
                "threshold": self.threshold,
                "reset_seconds": self.reset,
            }


class CircuitInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, breaker):
        self.breaker = breaker

    def intercept_unary_unary(self, continuation, details, request):
        permit = self.breaker.before()
        try:
            call = continuation(details, request)
            call.result()
        except grpc.RpcError as exc:
            self.breaker.after(permit, exc.code() in TRANSIENT)
            if "call" in locals():
                return call
            raise
        except Exception:
            self.breaker.after(permit, True)
            raise
        self.breaker.after(permit, False)
        return call


class RetryInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, attempts=3, backoff=0.1, sleep=time.sleep):
        if not 1 <= attempts <= 3 or not 0 <= backoff <= 5:
            raise ValueError("Retry requires 1..3 attempts and backoff 0..5 seconds")
        self.attempts, self.backoff, self.sleep = attempts, backoff, sleep

    def intercept_unary_unary(self, continuation, details, request):
        for attempt in range(1, self.attempts + 1):
            call = continuation(details, request)
            try:
                call.result()
                return call
            except grpc.RpcError as exc:
                retry = exc.code() in TRANSIENT and attempt < self.attempts
                event(
                    "grpc_attempt",
                    method=details.method,
                    attempt=attempt,
                    status=exc.code().name,
                    retry=retry,
                )
                if not retry:
                    return call
                self.sleep(self.backoff * 2 ** (attempt - 1))


class CallDetails(
    collections.namedtuple(
        "CallDetails", "method timeout metadata credentials wait_for_ready compression"
    ),
    grpc.ClientCallDetails,
):
    pass


class ApiKeyInterceptor(grpc.UnaryUnaryClientInterceptor):
    def __init__(self, key):
        self.key = key

    def intercept_unary_unary(self, continuation, details, request):
        metadata = list(details.metadata or []) + [("x-api-key", self.key)]
        updated = CallDetails(
            details.method,
            details.timeout,
            metadata,
            details.credentials,
            getattr(details, "wait_for_ready", None),
            getattr(details, "compression", None),
        )
        return continuation(updated, request)
