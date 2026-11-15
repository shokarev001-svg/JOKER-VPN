import base64
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from configure_endpoint import public_endpoint
from server import DAY, Ledger, ProfileUnavailable, validate_endpoint, handler

ENDPOINT = {'host': '8.8.8.8', 'port': 443, 'network': 'tcp', 'security': 'reality',
            'sni': 'www.example.com', 'short_id': '0123456789abcdef',
            'public_key': base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip('='),
            'flow': 'xtls-rprx-vision'}


class ProfileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = 1000000
        self.ledger = Ledger(Path(tmp.name) / 'ledger.sqlite3', lambda: self.now, ENDPOINT)
        self.token = 'a' * 64

    def test_profile_is_opt_in_and_bound_to_authenticated_member(self):
        key = self.ledger.issue(1)
        legacy = self.ledger.status(self.token, key)
        self.assertNotIn('vpn', legacy)
        self.assertIsNone(self.ledger.status('b'*64, include_profile=True)['vpn'])
        first = self.ledger.status(self.token, include_profile=True)
        self.assertEqual(first['vpn']['host'], ENDPOINT['host'])
        self.assertEqual(first['vpn']['schema'], 1)
        self.ledger.status('b'*64, self.ledger.issue(1))
        second = self.ledger.status('b'*64, include_profile=True)
        self.assertNotEqual(first['vpn']['id'], second['vpn']['id'])
        self.assertNotIn(self.token, json.dumps(first))
        self.assertNotIn(key, json.dumps(first))
        self.assertNotIn('privateKey', json.dumps(first))

    def test_expiry_hides_profile_and_renewal_retains_identity(self):
        self.ledger.status(self.token, self.ledger.issue(1))
        before = self.ledger.status(self.token, include_profile=True)['vpn']
        self.now += DAY
        self.assertIsNone(self.ledger.status(self.token, include_profile=True)['vpn'])
        self.ledger.status(self.token, self.ledger.issue(1))
        self.assertEqual(before, self.ledger.status(self.token, include_profile=True)['vpn'])

    def test_unconfigured_endpoint_keeps_legacy_activation_working(self):
        self.ledger.endpoint = None
        result = self.ledger.status(self.token, self.ledger.issue(1))
        self.assertEqual(result['status'], 'active')
        with self.assertRaises(ProfileUnavailable):
            self.ledger.status(self.token, include_profile=True)
        self.assertEqual(self.ledger.status(self.token), result)

    def test_rejects_private_and_malformed_endpoint_fields(self):
        for field, value in [('privateKey', 'secret'), ('host', '127.0.0.1'), ('host', 'example.com'),
                             ('port', True), ('port', 0), ('network', 'ws'), ('security', 'none'),
                             ('sni', 'bad/name'), ('public_key', 'secret'), ('short_id', '1'),
                             ('flow', 'unknown')]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_endpoint(dict(ENDPOINT, **{field: value}))

    def test_extractor_whitelists_parameters_and_rejects_ambiguity(self):
        config = {'inbounds': [{'tag': 'joker-vless', 'protocol': 'vless', 'port': 443,
            'settings': {'clients': [{'id': 'secret-user', 'flow': ENDPOINT['flow']}]},
            'streamSettings': {'network': 'tcp', 'security': 'reality', 'realitySettings': {
                'privateKey': 'secret-private-key', 'serverNames': [ENDPOINT['sni']],
                'shortIds': [ENDPOINT['short_id']]}}}]}
        calls = []
        def derive(key):
            calls.append(key)
            return ENDPOINT['public_key']
        self.assertEqual(public_endpoint(config, ENDPOINT['host'], derive), ENDPOINT)
        self.assertEqual(calls, ['secret-private-key'])
        malformed = copy.deepcopy(config)
        malformed['inbounds'].append(malformed['inbounds'][0])
        with self.assertRaises(ValueError):
            public_endpoint(malformed, ENDPOINT['host'], derive)

    def test_http_profile_contract_and_legacy_requests(self):
        self.ledger.status(self.token, self.ledger.issue(1))
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.ledger))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def request(payload, token=None, path='/v1/status'):
            conn = http.client.HTTPConnection(*server.server_address, timeout=2)
            headers = {'Content-Type': 'application/json'}
            if token is not None:
                headers['Authorization'] = 'Bearer ' + token
            conn.request('POST', path, json.dumps(payload), headers)
            response = conn.getresponse()
            result = response.status, json.loads(response.read())
            self.assertEqual(response.getheader('Cache-Control'), 'no-store')
            conn.close()
            return result
        try:
            self.assertEqual(request({'include_profile': True})[0], 401)
            self.assertNotIn('vpn', request({}, self.token)[1])
            self.assertEqual(request({'include_profile': True}, self.token)[1]['vpn']['schema'], 1)
            self.assertIsNone(request({'include_profile': True, 'token': self.token, 'id': self.token}, 'c'*64)[1]['vpn'])
            self.assertEqual(request({'include_profile': 'true'}, self.token)[0], 400)
            self.assertEqual(request({'include_profile': True}, self.token, '/v1/redeem')[0], 400)
            self.ledger.endpoint = None
            self.assertEqual(request({'include_profile': True}, self.token), (503, {'error': 'profile_unavailable'}))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
