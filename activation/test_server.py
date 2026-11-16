import concurrent.futures
import tempfile
import unittest
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from server import DAY, Ledger, Rejected, handler


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1000000
        self.ledger = Ledger(Path(self.tmp.name) / 'test.db', lambda: self.now)
        self.token = 'a' * 64

    def test_new_member_and_server_expiry(self):
        self.assertEqual(self.ledger.status(self.token)['status'], 'inactive')
        key = self.ledger.issue(30)
        result = self.ledger.status(self.token, key)
        self.assertEqual(result['remaining_days'], 30)
        self.now += 30 * DAY
        self.assertEqual(self.ledger.status(self.token)['status'], 'expired')
        self.assertEqual(self.ledger.status(self.token)['remaining_days'], 0)

    def test_retry_and_extension(self):
        key = self.ledger.issue(30)
        first = self.ledger.status(self.token, key)
        self.assertEqual(first, self.ledger.status(self.token, key))
        second = self.ledger.status(self.token, self.ledger.issue(7))
        self.assertEqual(second['expires_at'], first['expires_at'] + 7 * DAY)
        with self.assertRaises(Rejected):
            self.ledger.status('b' * 64, key)

    def test_expired_member_renews_from_now(self):
        self.ledger.status(self.token, self.ledger.issue(1))
        self.now += 5 * DAY
        self.assertEqual(self.ledger.status(self.token, self.ledger.issue(7))['remaining_days'], 7)

    def test_invalid_and_expired_vouchers_do_not_change_membership(self):
        for key in ('', 'bad', 'JOKER-' + 'A' * 48):
            with self.assertRaises(Rejected):
                self.ledger.status(self.token, key)
        key = self.ledger.issue(7, valid_days=1)
        self.now += DAY
        with self.assertRaises(Rejected):
            self.ledger.status(self.token, key)
        self.assertEqual(self.ledger.status(self.token)['status'], 'inactive')

    def test_concurrent_redemption_has_one_owner(self):
        key = self.ledger.issue(30)
        def redeem(token):
            try:
                self.ledger.status(token, key)
                return True
            except Rejected:
                return False
        with concurrent.futures.ThreadPoolExecutor() as pool:
            self.assertEqual(sum(pool.map(redeem, ['a'*64, 'b'*64])), 1)

    def test_concurrent_extensions_are_not_lost(self):
        keys = [self.ledger.issue(7), self.ledger.issue(30)]
        with concurrent.futures.ThreadPoolExecutor() as pool:
            list(pool.map(lambda key: self.ledger.status(self.token, key), keys))
        self.assertEqual(self.ledger.status(self.token)['remaining_days'], 37)

    def test_secrets_not_stored(self):
        key = self.ledger.issue(7)
        self.ledger.status(self.token, key)
        data = Path(self.ledger.path).read_bytes()
        self.assertNotIn(key.encode(), data)
        self.assertNotIn(self.token.encode(), data)

    def test_http_contract_and_lost_response_retry(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.ledger))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(path, body, auth=True):
            conn = http.client.HTTPConnection(*server.server_address, timeout=2)
            headers = {'Content-Type': 'application/json'}
            if auth:
                headers['Authorization'] = 'Bearer ' + self.token
            conn.request('POST', path, json.dumps(body), headers)
            response = conn.getresponse()
            result = response.status, json.loads(response.read())
            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
            conn.close()
            return result
        try:
            self.assertEqual(request('/v1/status', {}, False)[0], 401)
            self.assertEqual(request('/v1/status', [])[0], 400)
            self.assertEqual(request('/unknown', {})[0], 404)
            self.assertEqual(request('/v1/status', {})[1]['status'], 'inactive')
            body = {'key': self.ledger.issue(30)}
            first = request('/v1/redeem', body)
            self.assertEqual(first[0], 200)
            self.assertEqual(first, request('/v1/redeem', body))
            self.assertEqual(request('/v1/status', {})[1]['remaining_days'], 30)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
