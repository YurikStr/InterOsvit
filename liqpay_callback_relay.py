"""Callback-only local relay for sandbox LiqPay, NOT a public Flask tunnel.

Expose this small relay (port 5051) with a temporary HTTPS tunnel.
The InterOsvit Flask server stays on localhost:5000. No secrets logged.
"""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit
import os

from dotenv import load_dotenv
load_dotenv()

CALLBACK_PATH = '/premium-v2/liqpay/callback'
RETURN_PATH = '/premium-v2/return'
FLASK_BASE = 'http://127.0.0.1:5000'
MAX_BODY = 32768


def assert_sandbox() -> None:
    if os.getenv('APP_ENV', 'development').strip().lower() != 'development':
        raise RuntimeError('Relay працює лише при APP_ENV=development')
    if os.getenv('SUBSCRIPTIONS_TEST_MODE', '').lower() != 'true':
        raise RuntimeError('Потрібно SUBSCRIPTIONS_TEST_MODE=true')
    if os.getenv('SUBSCRIPTIONS_TEST_PROVIDER', '').lower() != 'liqpay':
        raise RuntimeError('Потрібно SUBSCRIPTIONS_TEST_PROVIDER=liqpay')
    from premium_v2_gateway import merchant_keys
    merchant_keys()  # Only sandbox_ keys; never print credentials


class CallbackOnlyHandler(BaseHTTPRequestHandler):
    server_version = 'InterOsvitSandboxRelay/1.0'
    sys_version = ''

    def log_message(self, format, *args):
        # No request body, tokens, or query strings in logs.
        pass

    def _reply(self, status: int, body: bytes = b''):
        self.send_response(status)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        # Browser-only return route. It NEVER confirms payment.
        if self.path != RETURN_PATH:
            return self._reply(404)
        self.send_response(302)
        self.send_header('Location', FLASK_BASE + RETURN_PATH)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_POST(self):
        if self.path != CALLBACK_PATH:
            return self._reply(404)
        content_type = self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
        if content_type != 'application/x-www-form-urlencoded':
            return self._reply(415)
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            return self._reply(411)
        if length < 1 or length > MAX_BODY:
            return self._reply(413)
        body = self.rfile.read(length)
        if len(body) != length:
            return self._reply(400)
        try:
            req = Request(FLASK_BASE + CALLBACK_PATH,
                          data=body,
                          headers={'Content-Type': 'application/x-www-form-urlencoded'},
                          method='POST')
            with urlopen(req, timeout=8) as response:
                code = response.status
        except HTTPError as error:
            code = error.code
            error.close()
        except (URLError, TimeoutError, OSError):
            code = 502
        print(f'Callback relay: HTTP {code} (вміст та ключі не виводяться)', flush=True)
        return self._reply(code if code in (200, 400, 403, 404, 413, 415) else 502)


def main() -> None:
    assert_sandbox()
    port = int(os.getenv('LIQPAY_CALLBACK_RELAY_PORT', '5051'))
    if not 1024 <= port <= 65535:
        raise ValueError('LIQPAY_CALLBACK_RELAY_PORT має бути 1024..65535')
    with ThreadingHTTPServer(('127.0.0.1', port), CallbackOnlyHandler) as server:
        print(f'LiqPay sandbox callback relay: http://127.0.0.1:{port}', flush=True)
        print('Публікуй через HTTPS-тунель лише цей порт, не Flask :5000', flush=True)
        server.serve_forever(poll_interval=0.2)


if __name__ == '__main__':
    main()
