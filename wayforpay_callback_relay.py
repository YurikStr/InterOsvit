"""Public-facing callback-only WayForPay relay on 127.0.0.1:5051 (ngrok tunnel).

Replaces, not runs alongside, liqpay_callback_relay.py. Never forwards any
other routes, cookies or browser session. Returns provider's signed JSON ACK.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from urllib.parse import parse_qsl
import json
import os
from dotenv import load_dotenv
from wayforpay_test_gateway import sandbox_guard,public_base

load_dotenv()
CALLBACK='/wayforpay-test/callback'
RETURN='/wayforpay-test/return'
FLASK_BASE='http://127.0.0.1:5000'

# WayForPay form-urlencoded callback support (v2)
def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _strict_json_object(raw):
    try:
        obj = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError('invalid JSON callback') from exc
    if not isinstance(obj, dict) or not obj:
        raise ValueError('JSON callback must be a nonempty object')
    return obj


def normalize_callback_body(media_type: str, raw: bytes) -> bytes:
    """Decode the wire format only. Flask still verifies signature/order/amount.

    Some providers send URL-encoded fields (or JSON wrapped as a form field).
    Never log the body; reject duplicate/ambiguous fields rather than guess.
    """
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 32768:
        raise ValueError('invalid callback size')
    if media_type == 'application/json':
        _strict_json_object(raw)
        return raw
    if media_type != 'application/x-www-form-urlencoded':
        raise ValueError('unsupported callback type')

    # Some callbacks contain a JSON object despite a form content type.
    if raw.lstrip().startswith(b'{'):
        data = _strict_json_object(raw)
    else:
        try:
            fields = parse_qsl(raw.decode('utf-8'), keep_blank_values=True,
                               strict_parsing=True, max_num_fields=64,
                               encoding='utf-8', errors='strict')
        except (ValueError, UnicodeError) as exc:
            raise ValueError('invalid form callback') from exc
        if not fields:
            raise ValueError('empty callback form')
        form = _unique_object(fields)
        if '' in form:
            raise ValueError('empty form key')
        if len(form) == 1 and next(iter(form)) in ('data', 'payload', 'json'):
            data = _strict_json_object(next(iter(form.values())))
        else:
            data = form
    # Normalize to JSON for the existing Flask endpoint. The existing HMAC,
    # merchant, order, currency and amount checks remain mandatory.
    return json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')



class Handler(BaseHTTPRequestHandler):
    server_version='InterOsvitWayForPayRelay/1.0'
    sys_version=''
    def log_message(self,*args): pass
    def reply(self,code,body=b'',content_type='text/plain; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type',content_type)
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        if body: self.wfile.write(body)
    def do_GET(self):
        if self.path != RETURN: return self.reply(404)
        self.send_response(302)
        self.send_header('Location',FLASK_BASE+RETURN)
        self.send_header('Content-Length','0')
        self.send_header('Cache-Control','no-store')
        self.end_headers()
    def do_POST(self):
        if self.path == RETURN:
            # PSP may POST its browser return; it is NEVER payment confirmation.
            self.send_response(303)
            self.send_header('Location',FLASK_BASE+RETURN)
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length','0')
            self.end_headers()
            return
        if self.path != CALLBACK: return self.reply(404)
        media_type = self.headers.get('Content-Type','').split(';')[0].strip().lower()
        if media_type not in ('application/json','application/x-www-form-urlencoded'):
            return self.reply(415)
        try: n=int(self.headers.get('Content-Length',''))
        except ValueError: return self.reply(411)
        if not 1<=n<=32768: return self.reply(413)
        body=self.rfile.read(n)
        if len(body)!=n: return self.reply(400)
        try:
            normalized = normalize_callback_body(media_type,body)
        except (ValueError, UnicodeError, TypeError):
            return self.reply(400)
        try:
            req=Request(FLASK_BASE+CALLBACK,data=normalized,method='POST',headers={'Content-Type':'application/json'})
            with urlopen(req,timeout=8) as resp:
                code=resp.status
                out=resp.read(4096)
        except HTTPError as ex:
            code=ex.code
            out=b''
            ex.close()
        except (URLError,TimeoutError,OSError):
            code=502
            out=b''
        print(f'WayForPay callback relay: HTTP {code} (no payment information logged)',flush=True)
        if code!=200: out=b''
        return self.reply(code if code in (200,400,403,404,413,415) else 502,
                          out, 'application/json; charset=utf-8' if code==200 else 'text/plain; charset=utf-8')


def main():
    sandbox_guard()
    public_base()
    port=int(os.getenv('WAYFORPAY_RELAY_PORT','5051'))
    if not 1024<=port<=65535: raise RuntimeError('Invalid relay port')
    with ThreadingHTTPServer(('127.0.0.1',port),Handler) as server:
        print(f'WayForPay test callback relay: http://127.0.0.1:{port}',flush=True)
        print('Expose only port 5051 with ngrok, NOT Flask port 5000',flush=True)
        server.serve_forever(poll_interval=0.2)

if __name__=='__main__': main()
