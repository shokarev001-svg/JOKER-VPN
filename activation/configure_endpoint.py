"""Administrator-only extraction of public REALITY parameters; no credentials printed."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile

from server import validate_endpoint


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--output', default='/etc/joker-activation/vpn-endpoint.json')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run as administrator')
    path = Path(args.output)
    temp = None
    try:
        result = subprocess.run(['docker', 'exec', 'amnezia-xray', 'cat', '/opt/amnezia/xray/server.json'],
                                check=True, text=True, capture_output=True, timeout=15)
        endpoint = public_endpoint(json.loads(result.stdout), args.host, derive_public_key)
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
        print('ENDPOINT_FAILED: ' + type(error).__name__)
        return 1
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
