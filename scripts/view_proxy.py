"""Loopback proxy for SSH dashboards with a different browser port."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def make_proxy(port, tunnel_port, remote_port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def forward(self):
            allowed = {f'127.0.0.1:{self.server.server_port}',
                       f'localhost:{self.server.server_port}'}
            origin = self.headers.get('Origin')
            if (self.headers.get('Host') not in allowed
                    or (origin and origin not in {'http://' + host for host in allowed})
                    or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                self.send_error(403)
                return
            if not self.path.startswith('/') or self.path.startswith('//'):
                self.send_error(400)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
            except ValueError:
                self.send_error(400)
                return
            if not 0 <= length <= 16384 or self.headers.get('Transfer-Encoding'):
                self.send_error(413)
                return
            headers = {name: self.headers[name] for name in (
                'Content-Type', 'X-Kebnekaise-Token', 'Sec-Fetch-Site') if name in self.headers}
            headers['Host'] = f'127.0.0.1:{remote_port}'
            if origin:
                headers['Origin'] = f'http://127.0.0.1:{remote_port}'
            upstream = http.client.HTTPConnection('127.0.0.1', tunnel_port, timeout=10)
            try:
                upstream.request(self.command, self.path, self.rfile.read(length), headers)
                response = upstream.getresponse()
                body = response.read()
                self.send_response(response.status)
                for name, value in response.getheaders():
                    if name.lower() not in {'connection', 'transfer-encoding', 'content-length', 'server', 'date'}:
                        self.send_header(name, value)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                self.send_error(502)
            finally:
                upstream.close()

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        do_GET = forward
        do_POST = forward

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)
