"""Synthetic bundle and pinned public-asset checks; no runtime JAR or installation."""
import hashlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('packager', Path(__file__).with_name('package_toolbox_delivery.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class PackageChecks(unittest.TestCase):
    def test_path_exclusions(self):
        for name in ('../secret', '/root/key', 'docs/../key', 'docs/.env', 'client-mod/build/a.py',
                     'docs/secret.pem', 'docs/unreviewed.jar', 'docs/unreviewed.png', 'runtime/a.py', 'docs/a\\b', 'docs/C:secret'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                m.public_path(name)

    def test_deterministic_verified_bundle_and_hash_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            names = ['README.md', 'NOTICE.md', 'client-mod/mcp/mineclient-bridge-mcp.mjs',
                     'capability-runtime/mdc_toolbox/__main__.py', 'docs/TOOLBOX-QUICKSTART.md']
            inventory = ''
            for name in names:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b'SYNTHETIC PUBLIC FILE\n')
                inventory += f'{m.digest(p.read_bytes())}  {name}\n'
            jar = io.BytesIO()
            with zipfile.ZipFile(jar, 'w') as z:
                z.writestr('META-INF/neoforge.mods.toml', '# synthetic')
                z.writestr('Synthetic.class', b'not real bytecode')
            raw = jar.getvalue()
            args = (root, inventory, raw, m.digest(raw), 'a'*40)
            first = m.bundle_bytes(*args)
            self.assertEqual(first, m.bundle_bytes(*args))
            with zipfile.ZipFile(io.BytesIO(first)) as z:
                for line in z.read('SHA256SUMS.txt').decode().splitlines():
                    expected, name = line.split('  ', 1)
                    self.assertEqual(expected, m.digest(z.read(name)))
            (root / 'README.md').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                m.bundle_bytes(*args)
            with self.assertRaisesRegex(ValueError, 'JAR checksum mismatch'):
                m.bundle_bytes(root, inventory, raw, '0'*64, 'a'*40)

    def test_exact_existing_binary_assets_are_hash_pinned(self):
        source = Path(__file__).resolve().parents[1]
        self.assertEqual(len(m.PUBLIC_BINARY_SHA256), 2)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, expected in m.PUBLIC_BINARY_SHA256.items():
                data = m.checked_read(source, name)
                self.assertEqual(m.digest(data), expected)
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                self.assertEqual(m.checked_read(root, name), data)
                target.write_bytes(data + b'changed')
                with self.assertRaisesRegex(ValueError, 'Pinned public asset checksum mismatch'):
                    m.checked_read(root, name)
                target.unlink()
                target.symlink_to(source / name)
                with self.assertRaisesRegex(ValueError, 'Symlink'):
                    m.checked_read(root, name)

    def test_source_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'NOTICE.md').write_text('synthetic')
            (root / 'README.md').symlink_to(root / 'NOTICE.md')
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                m.checked_read(root, 'README.md')


if __name__ == '__main__':
    unittest.main()
