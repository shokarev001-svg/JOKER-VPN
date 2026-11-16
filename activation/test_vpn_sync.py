import concurrent.futures
import json
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

from server import DAY, Ledger
from vpn_sync import SyncError, Xray, desired_users, email_for, reconcile


class FakeXray:
    def __init__(self):
        self.current = {'legacy@example.invalid'}
        self.events = []
        self.ignore_add = False
        self.ignore_remove = False
        self.on_add = lambda: None

    def flow(self):
        return 'xtls-rprx-vision'

    def users(self):
        return set(self.current)

    def add(self, email, identity, flow):
        self.events.append(('add', email))
        if not self.ignore_add:
            self.current.add(email)
        self.on_add()

    def remove(self, email):
        self.events.append(('remove', email))
        if not self.ignore_remove:
            self.current.discard(email)


class AccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'ledger.db'
        self.now = 1000000
        self.ledger = Ledger(self.path, lambda: self.now)
        self.xray = FakeXray()
        self.token = 'a' * 64

    def redeem(self, token=None):
        return self.ledger.status(token or self.token, self.ledger.issue(1))

    def sync(self, apply=True):
        return reconcile(self.path, self.xray, apply, lambda: self.now)

    def test_old_schema_migration_preserves_dates_and_vouchers(self):
        self.path.unlink()
        with sqlite3.connect(self.path) as db:
            db.executescript('CREATE TABLE members(token_hash TEXT PRIMARY KEY, expires INTEGER NOT NULL); CREATE TABLE vouchers(key_hash TEXT PRIMARY KEY, days INTEGER NOT NULL, redeem_before INTEGER NOT NULL, owner TEXT, redeemed INTEGER);')
            owner = Ledger.digest(self.token)
            db.execute('INSERT INTO members VALUES (?, ?)', (owner, self.now + DAY))
            db.execute('INSERT INTO vouchers VALUES (?, 1, ?, ?, ?)', ('voucher-hash', self.now + DAY, owner, self.now))
        Ledger(self.path)
        with sqlite3.connect(self.path) as db:
            identity = db.execute('SELECT uuid FROM vpn_credentials').fetchone()[0]
            self.assertEqual(db.execute('SELECT expires FROM members').fetchone()[0], self.now + DAY)
            self.assertEqual(db.execute('SELECT owner FROM vouchers').fetchone()[0], owner)
        Ledger(self.path)
        self.assertEqual(list(desired_users(self.path, self.now).values()), [identity])

    def test_retry_renewal_and_reopen_keep_identity(self):
        key = self.ledger.issue(1)
        self.ledger.status(self.token, key)
        first = desired_users(self.path, self.now)
        self.ledger.status(self.token, key)
        self.now += DAY + 1
        self.redeem()
        Ledger(self.path)
        self.assertEqual(first, desired_users(self.path, self.now))

    def test_concurrent_activations_get_one_identity_per_member(self):
        keys = [self.ledger.issue(1) for _ in range(6)]
        with concurrent.futures.ThreadPoolExecutor() as pool:
            list(pool.map(lambda key: self.ledger.status(self.token, key), keys))
        self.assertEqual(len(desired_users(self.path, self.now)), 1)
        self.redeem('b' * 64)
        self.assertEqual(len(set(desired_users(self.path, self.now).values())), 2)

    def test_preview_does_not_change_xray_or_emit_secrets(self):
        self.redeem()
        desired = desired_users(self.path, self.now)
        result = self.sync(False)
        self.assertEqual(result['add'], 1)
        self.assertEqual(self.xray.events, [])
        for email, identity in desired.items():
            self.assertNotIn(email, json.dumps(result))
            self.assertNotIn(identity, json.dumps(result))

    def test_expiry_removes_only_managed_user(self):
        self.redeem()
        self.sync()
        self.assertEqual(len(self.xray.current), 2)
        self.now += DAY
        self.sync()
        self.assertEqual(self.xray.current, {'legacy@example.invalid'})
        self.assertEqual(self.xray.events[-1][0], 'remove')

    def test_restart_recreates_only_active_accounts(self):
        self.redeem()
        self.sync()
        self.xray.current = {'legacy@example.invalid'}
        self.sync()
        self.assertEqual(len(self.xray.current), 2)
        self.now += DAY
        self.xray.current = {'legacy@example.invalid'}
        self.sync()
        self.assertEqual(len(self.xray.current), 1)

    def test_zero_exit_but_failed_add_is_not_success(self):
        self.redeem()
        self.xray.ignore_add = True
        with self.assertRaises(SyncError):
            self.sync()

    def test_failed_removal_blocks_new_additions(self):
        self.redeem()
        self.sync()
        self.now += DAY
        self.redeem('b' * 64)
        self.xray.ignore_remove = True
        before = len(self.xray.events)
        with self.assertRaises(SyncError):
            self.sync()
        self.assertTrue(all(event[0] == 'remove' for event in self.xray.events[before:]))

    def test_expiry_during_add_is_cleaned_up(self):
        self.redeem()
        self.xray.on_add = lambda: setattr(self, 'now', self.now + DAY)
        self.sync()
        self.assertEqual(self.xray.current, {'legacy@example.invalid'})

    def test_missing_or_corrupt_ledger_does_not_revoke_anyone(self):
        self.redeem()
        self.sync()
        before = list(self.xray.events)
        self.path.unlink()
        with self.assertRaises(sqlite3.Error):
            self.sync()
        self.assertFalse(self.path.exists())
        self.assertEqual(before, self.xray.events)

    def test_orphaned_managed_user_is_removed(self):
        self.xray.current.add(email_for('fd78901e-fc9c-4c9d-a6f4-2a83a434590b'))
        self.sync()
        self.assertEqual(self.xray.current, {'legacy@example.invalid'})


class AdapterTest(unittest.TestCase):
    def test_api_arguments_and_uuid_are_passed_without_shell(self):
        calls = []
        def run(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, '{}', '')
        xray = Xray(run)
        identity = 'fd78901e-fc9c-4c9d-a6f4-2a83a434590b'
        email = email_for(identity)
        xray.add(email, identity, 'xtls-rprx-vision')
        args, kwargs = calls[-1]
        self.assertNotIn(identity, args)
        self.assertNotIn('shell', kwargs)
        payload = json.loads(kwargs['input'])
        self.assertEqual(payload['inbounds'][0]['settings']['clients'][0]['id'], identity)
        self.assertEqual(xray.users(), set())
        with self.assertRaises(SyncError):
            xray.remove('legacy@example.invalid')

    def test_subprocess_error_does_not_expose_output(self):
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, 'SECRET', 'SECRET')
        with self.assertRaises(SyncError) as ctx:
            Xray(run).users()
        self.assertNotIn('SECRET', str(ctx.exception))

    def test_malformed_api_response_is_not_treated_as_empty(self):
        def run(args, **kwargs):
            return subprocess.CompletedProcess(args, 0, '{"error":"failed"}', '')
        with self.assertRaises(SyncError):
            Xray(run).users()


if __name__ == '__main__':
    unittest.main()
