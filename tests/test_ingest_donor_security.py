import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import URLError

from ingest import UrlSource
from ingest.adapters.base import AcquisitionFailed, PolicyRejected
from ingest.adapters.http import HttpAdapter
from ingest.policy import IngestPolicy


class SecurityTests(unittest.TestCase):
    def test_http_disabled_by_default(self):
        with self.assertRaises(PolicyRejected):
            HttpAdapter._check_url("http://example.com/data", IngestPolicy())

    def test_loopback_denied_even_when_plain_http_explicitly_enabled(self):
        with self.assertRaises(PolicyRejected):
            HttpAdapter._check_url(
                "http://127.0.0.1/data",
                IngestPolicy(allow_http=True),
            )

    def test_default_http_transport_connects_to_validated_ip_not_hostname(self):
        public_ip = "93.184.216.34"
        resolved = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (public_ip, 0))]
        attempted = []

        def fail_connect(address, *_args, **_kwargs):
            attempted.append(address)
            raise OSError("stop after address selection")

        with patch("ingest.adapters.http.socket.getaddrinfo", return_value=resolved), patch(
            "socket.create_connection", side_effect=fail_connect
        ):
            with self.assertRaises(AcquisitionFailed):
                HttpAdapter().acquire(
                    UrlSource("http://rebind.test/resource"),
                    IngestPolicy(allow_http=True),
                )

        self.assertTrue(attempted)
        self.assertEqual(attempted[0][0], public_ip)

    def test_default_http_transport_preserves_redirect_behavior(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/final")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"hello")

            def log_message(self, _format, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            acquisition = HttpAdapter().acquire(
                UrlSource(f"http://127.0.0.1:{port}/start"),
                IngestPolicy(allow_http=True, deny_private_networks=False),
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(acquisition.data, b"hello")
        self.assertEqual(acquisition.source.observed_metadata["redirects"], 1)

    def test_custom_opener_without_private_denial_keeps_its_own_resolution(self):
        class FailingOpener:
            def open(self, request, timeout):
                raise URLError("custom transport stop")

        with patch(
            "ingest.adapters.http._resolve_addresses",
            side_effect=AssertionError("custom opener should own resolution"),
        ):
            with self.assertRaises(AcquisitionFailed):
                HttpAdapter(opener=FailingOpener()).acquire(
                    UrlSource("http://custom.invalid/resource"),
                    IngestPolicy(allow_http=True, deny_private_networks=False),
                )


if __name__ == "__main__":
    unittest.main()
