"""Release boundaries: audio and collection data must never enter an AppImage."""
import hashlib
import io
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import urllib.error

spec = importlib.util.spec_from_file_location('check_appdir', Path(__file__).resolve().parents[1]/'packaging/check_appdir.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)
download_spec = importlib.util.spec_from_file_location(
    'fetch_inputs', Path(__file__).resolve().parents[1]/'packaging/fetch_inputs.py')
fetch_inputs = importlib.util.module_from_spec(download_spec)
download_spec.loader.exec_module(fetch_inputs)


class PackagingTests(unittest.TestCase):
    def test_pinned_download_retries_a_transient_server_error(self):
        content = b'checksum-pinned input'
        error = urllib.error.HTTPError('https://example.invalid/input', 500, 'temporary', {}, None)
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(fetch_inputs.urllib.request, 'urlopen',
                                  side_effect=[error, io.BytesIO(content)]) as request, \
                mock.patch.object(fetch_inputs.time, 'sleep') as sleep:
            destination = Path(directory)/'input'
            result = fetch_inputs.download('https://example.invalid/input', destination,
                                           hashlib.sha256(content).hexdigest())
            self.assertEqual(result.read_bytes(), content)
            self.assertEqual(request.call_count, 2)
            sleep.assert_called_once_with(1)

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
