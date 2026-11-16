"""Administrator-only public endpoint setup and read-only profile diagnostics."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import tempfile
import time

from server import validate_endpoint
from vpn_sync import MANAGED, Xray, email_for


def public_endpoint(config, host, derive_public_key):
    inbounds = [item for item in config['inbounds'] if item.get('tag') == 'joker-vless']
    if len(inbounds) != 1:
        raise ValueError('Expected one subscription inbound')
    inbound = inbounds[0]
    stream = inbound['streamSettings']
    if inbound['protocol'] != 'vless' or inbound['port'] != 443 or stream.get('network', 'tcp') not in ('tcp', 'raw'):
        raise ValueError('Unexpected inbound')
    if stream.get('security') != 'reality':
        raise ValueError('Expected REALITY')
    reality = stream['realitySettings']
    flows = {item.get('flow', '') for item in inbound['settings']['clients']}
    if len(flows) != 1:
        raise ValueError('Ambiguous flow')
    return validate_endpoint({
        'host': host, 'port': inbound['port'], 'network': 'tcp', 'security': 'reality',
        'sni': reality['serverNames'][0], 'short_id': reality['shortIds'][0],
        'public_key': derive_public_key(reality['privateKey']), 'flow': flows.pop(),
    })


def derive_public_key(private_key):
    # Only this administrator command needs cryptography (already in the Certbot venv).
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    raw = base64.urlsafe_b64decode(private_key + '=' * (-len(private_key) % 4))
    public = X25519PrivateKey.from_private_bytes(raw).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.urlsafe_b64encode(public).decode().rstrip('=')


def profile_report(expected, saved, rows, runtime, now):
    """Compare secrets in memory; return only fixed labels, counts and booleans.

    Xray 26.7.28's common/reflect/marshal.go expands TypedMessage accounts into
    objects with _TypedMessage_. An unknown representation is a diagnostic error,
    never proof that the UUID/flow matches.
    """
    saved = validate_endpoint(saved)
    desired = {}
    expired = 0
    for expires, identity in rows:
        if type(expires) is not int:
            raise ValueError('Invalid expiry')
        email = email_for(identity)
        if expires > now:
            if email in desired:
                raise ValueError('Duplicate identity')
            desired[email] = identity
        else:
            expired += 1
    if not isinstance(runtime, dict) or set(runtime) - {'users'}:
        raise ValueError('Unexpected runtime response')
    users = runtime.get('users', [])
    if not isinstance(users, list):
        raise ValueError('Unexpected runtime users')
    managed = {}
    for user in users:
        if not isinstance(user, dict) or not isinstance(user.get('email'), str):
            raise ValueError('Unexpected runtime user')
        email = user['email']
        if not MANAGED.fullmatch(email):
            continue
        if email in managed:
            raise ValueError('Duplicate runtime user')
        account = user.get('account')
        if (not isinstance(account, dict)
                or account.get('_TypedMessage_') != 'xray.proxy.vless.Account'
                or not isinstance(account.get('id'), str)
                or not isinstance(account.get('flow', ''), str)):
            raise ValueError('Unsupported runtime account representation')
        managed[email] = account
    compared = desired.keys() & managed.keys()
    result = {
        'active': len(desired), 'expired': expired, 'xray_managed': len(managed),
        'missing': len(desired.keys() - managed.keys()),
        'unexpected': len(managed.keys() - desired.keys()),
        'uuid_mismatch': sum(managed[e]['id'] != desired[e] for e in compared),
        'flow_mismatch': sum(managed[e].get('flow', '') != expected['flow'] for e in compared),
    }
    for field in ('host', 'port', 'network', 'security', 'sni', 'public_key', 'short_id', 'flow'):
        result[field + '_matches'] = saved[field] == expected[field]
    mismatch = any(result[k] for k in ('missing', 'unexpected', 'uuid_mismatch', 'flow_mismatch'))
    mismatch = mismatch or not all(v for k, v in result.items() if k.endswith('_matches'))
    result['result'] = ('MISMATCH' if mismatch else
                        'NO_ACTIVE_SUBSCRIPTIONS' if not desired else 'PARAMETERS_MATCH')
    # PARAMETERS_MATCH does not test a handshake, device configuration or network.
    return result


def read_member_rows(database):
    # Diagnostics must not create, migrate, redeem or extend the production ledger.
    db = sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
    try:
        return db.execute('SELECT m.expires, v.uuid FROM members m '
                          'LEFT JOIN vpn_credentials v USING(token_hash)').fetchall()
    finally:
        db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--output', default='/etc/joker-activation/vpn-endpoint.json')
    parser.add_argument('--check', action='store_true', help='Read-only comparison; do not update the endpoint')
    parser.add_argument('--database', default='/var/lib/joker-activation/ledger.sqlite3')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error('Run as administrator')
    path = Path(args.output)
    temp = None
    try:
        result = subprocess.run(['docker', 'exec', 'amnezia-xray', 'cat', '/opt/amnezia/xray/server.json'],
                                check=True, text=True, capture_output=True, timeout=15)
        endpoint = public_endpoint(json.loads(result.stdout), args.host, derive_public_key)
        if args.check:
            report = profile_report(endpoint, json.loads(path.read_text()),
                read_member_rows(args.database),
                json.loads(Xray().api('inbounduser', ['-tag=joker-vless'])), int(time.time()))
            print('MODE=READ_ONLY')
            for key, value in report.items():
                display = str(value).lower() if isinstance(value, bool) else str(value)
                print(key.upper() + '=' + display)
            return 0
        path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as file:
            temp = Path(file.name)
            json.dump(endpoint, file)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
        print('ENDPOINT_READY')
    except Exception as error:
        # Neither the source configuration nor subprocess exception may be printed.
        print(('PROFILE_CHECK_FAILED: ' if args.check else 'ENDPOINT_FAILED: ') + type(error).__name__)
        return 1
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
