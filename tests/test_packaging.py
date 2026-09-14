"""Release boundaries: audio and collection data must never enter an AppImage."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('check_appdir', Path(__file__).resolve().parents[1]/'packaging/check_appdir.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class PackagingTests(unittest.TestCase):
    def test_rejects_named_audio_hidden_audio_and_collection_state(self):
        for name, content in [('clip.mp3', b'not decoded'), ('renamed.bin', b'RIFF0000WAVE'),
                              ('remote-settings.json', b'{}')]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/name).write_bytes(content)
                with self.assertRaises(ValueError):
                    checker.check(root)

    def test_requires_notices_and_accepts_an_empty_library_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                checker.check(root)
            for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md', 'licenses/components.json', 'licenses/common/GPL-3'):
                path = root/'usr/bin/_internal'/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('test notice')
            checker.check(root)
