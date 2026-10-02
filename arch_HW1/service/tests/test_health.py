"""Exercise the HTTP parser and handler with in-memory transport."""

import io
import json
import unittest
from http.client import HTTPResponse

from service.main import HealthHandler


class MemoryConnection:
    """Supply the stream methods used by the standard-library HTTP classes."""

    def __init__(self, incoming: bytes) -> None:
        self.incoming = io.BytesIO(incoming)
        self.outgoing = bytearray()

    def makefile(self, mode: str, buffering: int = -1) -> io.BytesIO:
        return self.incoming

    def sendall(self, data: bytes) -> None:
        self.outgoing.extend(data)


class HealthContractTest(unittest.TestCase):
    def request(self, path: str) -> tuple[int, str, bytes]:
        request = f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode("ascii")
        connection = MemoryConnection(request)
        HealthHandler(connection, ("127.0.0.1", 12345), None)
        response = HTTPResponse(MemoryConnection(bytes(connection.outgoing)))
        response.begin()
        return response.status, response.getheader("Content-Type"), response.read()

    def test_health_returns_200_and_service_identity(self) -> None:
        status, content_type, payload = self.request("/health")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json")
        self.assertEqual(json.loads(payload), {"status": "ok", "service": "orders-service"})

    def test_unknown_routes_are_not_implemented(self) -> None:
        for path in ("/", "/orders", "/health/", "/missing"):
            with self.subTest(path=path):
                status, content_type, payload = self.request(path)
                self.assertEqual(status, 404)
                self.assertEqual(content_type, "application/json")
                self.assertEqual(json.loads(payload), {"error": "not_found"})


if __name__ == "__main__":
    unittest.main()
