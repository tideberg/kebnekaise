import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest

from scripts.view_proxy import make_proxy


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        requests = self.requests

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                requests.append((self.headers, self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'ok')

        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        self.proxy = make_proxy(0, self.upstream.server_port, 8840)
        for server in (self.upstream, self.proxy):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def tearDown(self):
        for server in (self.proxy, self.upstream):
            server.shutdown()
            server.server_close()

    def request(self, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.proxy.server_port)
        try:
            connection.request('POST', '/api/events', b'{}', headers)
            response = connection.getresponse()
            response.read()
            return response.status
        finally:
            connection.close()

    def test_local_origin_and_token_are_forwarded(self):
        self.assertEqual(self.request(**{
            'Origin': f'http://127.0.0.1:{self.proxy.server_port}',
            'X-Kebnekaise-Token': 'test-token', 'Content-Type': 'application/json'}), 200)
        headers, body = self.requests[0]
        self.assertEqual(headers['Host'], '127.0.0.1:8840')
        self.assertEqual(headers['Origin'], 'http://127.0.0.1:8840')
        self.assertEqual(headers['X-Kebnekaise-Token'], 'test-token')
        self.assertEqual(body, b'{}')

    def test_external_requests_never_reach_upstream(self):
        for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request(**headers), 403)
        self.assertEqual(self.requests, [])
