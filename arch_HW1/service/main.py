"""A minimal HTTP process exposing only its liveness endpoint."""

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


LOGGER = logging.getLogger("orders-service")


class HealthHandler(BaseHTTPRequestHandler):
    """Return health status without connecting to any external dependencies."""

    def do_GET(self) -> None:
        if self.path == "/health":
            status = 200
            body = {"status": "ok", "service": "orders-service"}
        else:
            status = 404
            body = {"error": "not_found"}

        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.info("%s - %s", self.client_address[0], format % args)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    with ThreadingHTTPServer((host, port), HealthHandler) as server:
        LOGGER.info("orders-service listening on %s:%s", host, port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            LOGGER.info("orders-service stopped")


if __name__ == "__main__":
    main()
