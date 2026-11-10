"""Stage-one Xray reconciliation. Preview by default; not a hard session cutoff.

This local administrator process owns Docker access. The HTTP ledger service must
never receive Docker socket access. Managed users exist only in Xray memory;
a container restart removes them until the next successful reconciliation.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid

MANAGED = re.compile(r'joker-sub-[0-9a-f]{32}@vpn\.invalid')
OWNER = re.compile(r'[0-9a-f]{64}')
CONTAINER = 'amnezia-xray'
TAG = 'joker-vless'
ADDRESS = '127.0.0.1:10085'


class SyncError(Exception):
    pass


def email_for(identity):
    parsed = uuid.UUID(identity)
    if str(parsed) != identity or parsed.version != 4:
        raise SyncError('Invalid stored VPN identity')
    return 'joker-sub-' + parsed.hex + '@vpn.invalid'


def desired_users(database, now):
    # mode=ro prevents silently creating an empty ledger after a path typo.
    db = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    try:
        rows = db.execute('SELECT m.token_hash, m.expires, v.uuid FROM members m LEFT JOIN vpn_credentials v USING(token_hash)').fetchall()
        desired = {}
        for owner, expires, identity in rows:
            if not isinstance(owner, str) or not OWNER.fullmatch(owner) or type(expires) is not int or not identity:
                raise SyncError('Invalid or unmigrated ledger; no Xray changes made')
            email = email_for(identity)
            if expires > now:
                desired[email] = identity
        return desired
    finally:
        db.close()


class Xray:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def run(self, args, data=None):
        try:
            result = self.runner(['docker', 'exec', '-i', CONTAINER] + args,
                                 input=data, capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            raise SyncError('Xray command unavailable or timed out') from None
        if result.returncode:
            # CLI stderr can contain identifiers; do not put it into journals.
            raise SyncError('Xray command failed; no success confirmed')
        return result.stdout

    def api(self, command, extra=(), data=None):
        return self.run(['xray', 'api', command, '--server=' + ADDRESS] + list(extra), data)

    def flow(self):
        config = json.loads(self.run(['cat', '/opt/amnezia/xray/server.json']))
        inbounds = [i for i in config.get('inbounds', []) if i.get('tag') == TAG]
        if len(inbounds) != 1:
            raise SyncError('Expected one managed inbound')
        inbound = inbounds[0]
        stream = inbound.get('streamSettings', {})
        if inbound.get('protocol') != 'vless' or inbound.get('port') != 443 or stream.get('security') != 'reality':
            raise SyncError('Unexpected inbound configuration')
        clients = inbound.get('settings', {}).get('clients', [])
        # Dynamic subscription accounts must never be baked into startup config:
        # doing so could resurrect an expired account on container restart.
        if any(MANAGED.fullmatch(c.get('email', '')) for c in clients):
            raise SyncError('Managed accounts found in static config; review required')
        flows = {c.get('flow', '') for c in clients}
        if len(flows) != 1 or not flows <= {'', 'xtls-rprx-vision'}:
            raise SyncError('Ambiguous VLESS flow; review required')
        return flows.pop()

    def users(self):
        body = json.loads(self.api('inbounduser', ['-tag=' + TAG]))
        if not isinstance(body, dict) or set(body) - {'users'}:
            raise SyncError('Unexpected Xray user response')
        users = body.get('users', [])
        if not isinstance(users, list) or any(not isinstance(u, dict) or not isinstance(u.get('email'), str) for u in users):
            raise SyncError('Invalid Xray user response')
        return {u['email'] for u in users}

    def add(self, email, identity, flow):
        user = {'id': identity, 'email': email, 'flow': flow}
        payload = {'inbounds': [{'tag': TAG, 'port': 443, 'protocol': 'vless',
                                'settings': {'decryption': 'none', 'clients': [user]}}]}
        self.api('adu', ['stdin:'], json.dumps(payload))

    def remove(self, email):
        if not MANAGED.fullmatch(email):
            raise SyncError('Refusing to remove an unmanaged account')
        self.api('rmu', ['-tag=' + TAG, email])


def reconcile(database, xray, apply=False, clock=time.time):
    desired = desired_users(database, int(clock()))
    flow = xray.flow()
    actual = {e for e in xray.users() if MANAGED.fullmatch(e)}
    remove = actual - desired.keys()
    add = desired.keys() - actual
    summary = {'mode': 'apply' if apply else 'preview', 'active_subscriptions': len(desired),
               'managed_in_xray': len(actual), 'add': len(add), 'remove': len(remove)}
    if not apply:
        return summary
    for email in sorted(remove):
        xray.remove(email)
    if remove & xray.users():
        raise SyncError('Removal not confirmed; additions skipped')
    # Re-read after revocations; subscriptions can expire while API calls run.
    desired = desired_users(database, int(clock()))
    actual = {e for e in xray.users() if MANAGED.fullmatch(e)}
    for email in sorted(desired.keys() - actual):
        fresh = desired_users(database, int(clock()))
        if email in fresh:
            xray.add(email, fresh[email], flow)
    final_desired = desired_users(database, int(clock()))
    final_actual = {e for e in xray.users() if MANAGED.fullmatch(e)}
    # Catch expiry during addition, and refuse a false successful result from CLI
    # commands that can return exit code zero after an individual API failure.
    for email in sorted(final_actual - final_desired.keys()):
        xray.remove(email)
    if {e for e in xray.users() if MANAGED.fullmatch(e)} != set(final_desired):
        raise SyncError('Reconciliation not confirmed; retry required')
    summary['verified'] = True
    return summary


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default='/var/lib/joker-activation/ledger.sqlite3')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--acknowledge-session-cutoff-pending', action='store_true')
    args = parser.parse_args()
    if args.apply and not args.acknowledge_session_cutoff_pending:
        parser.error('Existing sessions are not forcibly terminated. Hard expiry is not implemented.')
    try:
        with open('/run/joker-vpn-sync.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            print(json.dumps(reconcile(args.database, Xray(), args.apply)))
    except (SyncError, sqlite3.Error, ValueError, TypeError, KeyError, OSError) as error:
        # Never print raw DB rows, Xray configs, UUIDs, or subprocess exceptions.
        print('VPN_SYNC_FAILED: ' + type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
