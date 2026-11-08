"""Subscription ledger. Run behind a TLS proxy; administration is local CLI only."""
import argparse
import hashlib
import json
import math
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DAY = 86400
TOKEN = re.compile(r"[0-9a-f]{64}")
KEY = re.compile(r"JOKER-[A-F0-9]{48}")


class Rejected(Exception):
    pass


class Ledger:
    def __init__(self, path, clock=time.time):
        self.path, self.clock = str(path), clock
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS members (
                    token_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS vouchers (
                    key_hash TEXT PRIMARY KEY, days INTEGER NOT NULL,
                    redeem_before INTEGER NOT NULL, owner TEXT, redeemed INTEGER);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode('ascii')).hexdigest()

    def issue(self, days, valid_days=90):
        if not 1 <= days <= 365 or not 1 <= valid_days <= 365:
            raise ValueError('Duration must be 1..365 days')
        key = 'JOKER-' + secrets.token_hex(24).upper()
        with self.connect() as db:
            db.execute('INSERT INTO vouchers VALUES (?, ?, ?, NULL, NULL)',
                       (self.digest(key), days, int(self.clock()) + valid_days * DAY))
        return key

    def status(self, token, key=None):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise Rejected('invalid_token')
        if key is not None and (not isinstance(key, str) or not KEY.fullmatch(key)):
            raise Rejected('invalid_key')
        owner = self.digest(token)
        with self.connect() as db:
            # One transaction prevents concurrent redemption and lost extensions.
            db.execute('BEGIN IMMEDIATE')
            now = int(self.clock())
            row = db.execute('SELECT expires FROM members WHERE token_hash=?', (owner,)).fetchone()
            expires = row[0] if row else 0
            if key is not None:
                voucher = db.execute('SELECT days, redeem_before, owner FROM vouchers WHERE key_hash=?',
                                     (self.digest(key),)).fetchone()
                if not voucher:
                    raise Rejected('invalid_key')
                days, redeem_before, used_by = voucher
                if used_by is not None and used_by != owner:
                    raise Rejected('used_key')
                if used_by is None:
                    if redeem_before <= now:
                        raise Rejected('expired_key')
                    expires = max(now, expires) + days * DAY
                    db.execute('INSERT INTO members VALUES (?, ?) ON CONFLICT(token_hash) DO UPDATE SET expires=excluded.expires',
                               (owner, expires))
                    db.execute('UPDATE vouchers SET owner=?, redeemed=? WHERE key_hash=?',
                               (owner, now, self.digest(key)))
                # Retrying after a lost response never grants the days twice.
            return {'server_time': now, 'expires_at': expires,
                    'remaining_days': math.ceil(max(0, expires - now) / DAY),
                    'status': 'active' if expires > now else ('expired' if expires else 'inactive')}


def handler(ledger):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_args):
            pass  # Never log credentials, request bodies or URLs.

        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path not in ('/v1/status', '/v1/redeem'):
                return self.reply(404, {'error': 'not_found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024 or self.headers.get('Transfer-Encoding'):
                    return self.reply(400, {'error': 'invalid_request'})
                auth = self.headers.get('Authorization', '')
                if not auth.startswith('Bearer '):
                    return self.reply(401, {'error': 'invalid_token'})
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError()
                key = payload.get('key', '') if self.path == '/v1/redeem' else None
                return self.reply(200, ledger.status(auth[7:], key))
            except Rejected as error:
                return self.reply(400, {'error': str(error)})
            except (ValueError, UnicodeError):
                return self.reply(400, {'error': 'invalid_request'})
            except sqlite3.Error:
                return self.reply(503, {'error': 'temporarily_unavailable'})
    return Handler


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', default='/var/lib/joker-activation/ledger.sqlite3')
    sub = parser.add_subparsers(dest='command', required=True)
    issue = sub.add_parser('issue')
    issue.add_argument('--days', type=int, required=True)
    issue.add_argument('--valid-days', type=int, default=90)
    serve = sub.add_parser('serve')
    serve.add_argument('--port', type=int, default=8088)
    args = parser.parse_args()
    Path(args.database).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    ledger = Ledger(args.database)
    if args.command == 'issue':
        print(ledger.issue(args.days, args.valid_days))
    else:
        ThreadingHTTPServer(('127.0.0.1', args.port), handler(ledger)).serve_forever()


if __name__ == '__main__':
    main()
