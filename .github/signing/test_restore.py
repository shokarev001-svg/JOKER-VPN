import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('restore', Path(__file__).with_name('restore.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RestoreSigningTests(unittest.TestCase):
    def bundle(self, **changes):
        result = dict(keystore_base64=base64.b64encode(b'test-only-placeholder').decode(),
                      password='test-only-password', certificate_sha256='a' * 64)
        result.update(changes)
        return json.dumps(result)

    def test_restore_exact_bytes_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            module.restore(self.bundle(), Path(d) / 'signing')
            p = Path(d) / 'signing'
            self.assertEqual((p / 'key.p12').read_bytes(), b'test-only-placeholder')
            self.assertEqual((p / 'password').read_text(), 'test-only-password')
            self.assertEqual((p / 'certificate.sha256').read_text(), 'a' * 64)
            for f in p.iterdir():
                self.assertEqual(f.stat().st_mode & 0o777, 0o600)

    def test_invalid_or_missing_secret_never_creates_key(self):
        cases = ['', '{}', '[]', 'null', '{', self.bundle(keystore_base64='not base64'),
                 self.bundle(password=''), self.bundle(password='line\nbreak'),
                 self.bundle(certificate_sha256='invalid'), self.bundle(certificate_sha256=12)]
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):
                    module.restore(case, Path(d) / 'signing')
                self.assertFalse((Path(d) / 'signing/key.p12').exists())

    def test_does_not_overwrite_existing_key(self):
        with tempfile.TemporaryDirectory() as d:
            module.restore(self.bundle(), d)
            with self.assertRaises(FileExistsError):
                module.restore(self.bundle(password='different'), d)
            self.assertEqual((Path(d) / 'password').read_text(), 'test-only-password')


if __name__ == '__main__':
    unittest.main()
