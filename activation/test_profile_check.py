import contextlib
import copy
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import configure_endpoint
from configure_endpoint import profile_report, read_member_rows
from test_profile import ENDPOINT
from vpn_sync import email_for

IDENTITY = 'fd78901e-fc9c-4c9d-a6f4-2a83a434590b'
OTHER = '086a7ee2-bf53-48e7-b01b-41ea39f90fe3'


def runtime_user(identity=IDENTITY):
    return {'email': email_for(IDENTITY), 'account': {
        '_TypedMessage_': 'xray.proxy.vless.Account', 'id': identity,
        'flow': ENDPOINT['flow']}}


class ProfileCheckTest(unittest.TestCase):
    def report(self, users=None, saved=None, rows=None):
        return profile_report(ENDPOINT, saved if saved is not None else ENDPOINT,
            [(200, IDENTITY)] if rows is None else rows,
            {'users': [runtime_user()]} if users is None else users, 100)

    def test_match_reports_parameters_only_without_credentials(self):
        result = self.report()
        self.assertEqual(result['result'], 'PARAMETERS_MATCH')
        self.assertEqual(result['active'], 1)
        self.assertEqual(result['xray_managed'], 1)
        self.assertTrue(all(v for k, v in result.items() if k.endswith('_matches')))
        text = json.dumps(result)
        for secret in (IDENTITY, email_for(IDENTITY), ENDPOINT['public_key'], ENDPOINT['sni']):
            self.assertNotIn(secret, text)

    def test_same_email_count_can_hide_wrong_uuid_or_flow(self):
        wrong = runtime_user(OTHER)
        wrong['account']['flow'] = ''
        result = self.report({'users': [wrong]})
        self.assertEqual(result['active'], result['xray_managed'])
        self.assertEqual(result['uuid_mismatch'], 1)
        self.assertEqual(result['flow_mismatch'], 1)
        self.assertEqual(result['result'], 'MISMATCH')
        result = self.report(saved=dict(ENDPOINT, short_id=''))
        self.assertFalse(result['short_id_matches'])
        self.assertEqual(result['result'], 'MISMATCH')

    def test_expired_access_and_missing_users_are_distinct(self):
        result = self.report({}, rows=[(100, IDENTITY)])
        self.assertEqual((result['active'], result['expired']), (0, 1))
        self.assertEqual(result['result'], 'NO_ACTIVE_SUBSCRIPTIONS')
        result = self.report(rows=[(100, IDENTITY)])
        self.assertEqual(result['unexpected'], 1)
        self.assertEqual(result['result'], 'MISMATCH')
        result = self.report({})
        self.assertEqual(result['missing'], 1)
        self.assertEqual(result['result'], 'MISMATCH')

    def test_unrecognized_runtime_format_does_not_pass(self):
        user = runtime_user()
        user['account'] = {'type': 'xray.proxy.vless.Account', 'value': 'secret'}
        for runtime in ({'error': 'secret'}, {'users': [user]},
                        {'users': [runtime_user(), runtime_user()]}):
            with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                self.report(runtime)
        # Unmanaged users are outside the subscription diagnostic.
        result = self.report({'users': [runtime_user(), {'email': 'legacy@example.invalid'}]})
        self.assertEqual(result['result'], 'PARAMETERS_MATCH')

    def test_read_only_db_never_creates_or_changes_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ledger.sqlite3'
            with self.assertRaises(sqlite3.OperationalError):
                read_member_rows(path)
            self.assertFalse(path.exists())
            with sqlite3.connect(path) as db:
                db.executescript('CREATE TABLE members(token_hash TEXT, expires INTEGER);'
                                 'CREATE TABLE vpn_credentials(token_hash TEXT, uuid TEXT);')
                db.execute('INSERT INTO members VALUES (?, ?)', ('private-token-hash', 200))
                db.execute('INSERT INTO vpn_credentials VALUES (?, ?)', ('private-token-hash', IDENTITY))
            before = path.read_bytes()
            self.assertEqual(read_member_rows(path), [(200, IDENTITY)])
            self.assertEqual(path.read_bytes(), before)

    def test_check_cli_uses_only_reads_and_sanitizes_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            endpoint_path = Path(tmp) / 'endpoint.json'
            endpoint_path.write_text(json.dumps(ENDPOINT))
            before = endpoint_path.read_bytes()
            output = io.StringIO()
            with patch.object(configure_endpoint.os, 'geteuid', return_value=0), \
                 patch.object(configure_endpoint.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{}')), \
                 patch.object(configure_endpoint, 'public_endpoint', return_value=copy.deepcopy(ENDPOINT)), \
                 patch.object(configure_endpoint, 'read_member_rows', return_value=[(200, IDENTITY)]), \
                 patch.object(configure_endpoint.time, 'time', return_value=100), \
                 patch.object(configure_endpoint.Xray, 'api', return_value=json.dumps({'users': [runtime_user()]})) as api, \
                 patch.object(configure_endpoint.tempfile, 'NamedTemporaryFile', side_effect=AssertionError('unexpected write')), \
                 contextlib.redirect_stdout(output):
                self.assertEqual(configure_endpoint.main(['--check', '--host', ENDPOINT['host'],
                    '--output', str(endpoint_path)]), 0)
                api.assert_called_once_with('inbounduser', ['-tag=joker-vless'])
                api.side_effect = ValueError('secret ' + IDENTITY)
                self.assertEqual(configure_endpoint.main(['--check', '--host', ENDPOINT['host'],
                    '--output', str(endpoint_path)]), 1)
            self.assertEqual(endpoint_path.read_bytes(), before)
            self.assertIn('RESULT=PARAMETERS_MATCH', output.getvalue())
            self.assertIn('PROFILE_CHECK_FAILED: ValueError', output.getvalue())
            self.assertNotIn(IDENTITY, output.getvalue())


if __name__ == '__main__':
    unittest.main()
