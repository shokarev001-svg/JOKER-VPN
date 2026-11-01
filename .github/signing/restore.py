"""Restore an explicitly provisioned APK signing key; never generate one in CI."""
import base64
import json
import os
import re
from pathlib import Path


def restore(bundle_text, directory):
    if not bundle_text:
        raise ValueError('JOKER_SIGNING_JSON is missing; refusing temporary signing')
    try:
        bundle = json.loads(bundle_text)
        if not isinstance(bundle, dict) or not all(isinstance(bundle.get(k), str) for k in ('keystore_base64', 'password', 'certificate_sha256')):
            raise ValueError('Invalid signing bundle')
        key = base64.b64decode(bundle['keystore_base64'], validate=True)
        password = bundle['password']
        fingerprint = bundle['certificate_sha256'].lower().replace(':', '')
    except (KeyError, TypeError, ValueError):
        raise ValueError('Invalid signing bundle') from None
    if not key or not isinstance(password, str) or not password or '\n' in password or '\r' in password:
        raise ValueError('Invalid keystore or password')
    if not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise ValueError('Invalid signing certificate fingerprint')
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, data in [('key.p12', key), ('password', password.encode()), ('certificate.sha256', fingerprint.encode())]:
        path = directory / name
        with path.open('xb') as output:
            os.chmod(path, 0o600)
            output.write(data)


if __name__ == '__main__':
    try:
        restore(os.environ.get('JOKER_SIGNING_JSON', ''), Path(os.environ['RUNNER_TEMP']) / 'joker-signing')
    except (ValueError, OSError) as error:
        raise SystemExit('Signing setup failed: ' + str(error)) from None
