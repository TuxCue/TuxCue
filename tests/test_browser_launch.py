import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

from soundboard import runtime


class BrowserLaunchTests(unittest.TestCase):
    def test_frozen_browser_restores_host_paths_and_preserves_desktop_session(self):
        host = {'PATH': '/custom/bin:/usr/bin:/bin', 'LD_LIBRARY_PATH_ORIG': '/host/lib',
                'LD_LIBRARY_PATH': '/bundle:/host/lib', 'GTK_PATH': '/host/gtk',
                'XDG_DATA_DIRS': '/custom/share:/var/lib/flatpak/exports/share:/usr/share',
                'DISPLAY': ':0', 'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/run/user/test/bus'}
        with patch.dict(os.environ, host, clear=True), patch.object(runtime.sys, 'frozen', True, create=True):
            runtime.capture_host_environment()
            for key in runtime.HOST_ENVIRONMENT_KEYS:
                os.environ[key] = '/bundle/contamination'
            os.environ['_PYI_ARCHIVE_FILE'] = '/bundle/tuxcue'
            os.environ['TUXCUE_ORIGINAL_PATH'] = '/bundle/bin:/usr/bin'
            polluted = dict(os.environ)
            clean = runtime.browser_environment()
            self.assertEqual(os.environ, polluted, 'Do not change the running audio/tray environment')
            self.assertEqual(clean['PATH'], host['PATH'])
            self.assertEqual(clean['LD_LIBRARY_PATH'], '/host/lib')
            for key in ('GTK_PATH', 'XDG_DATA_DIRS', 'DISPLAY', 'DBUS_SESSION_BUS_ADDRESS'):
                self.assertEqual(clean[key], host[key])
            for key in ('GIO_MODULE_DIR', 'GTK_EXE_PREFIX', 'PANGO_LIBDIR', 'GDK_PIXBUF_MODULE_FILE',
                        'GST_PLUGIN_PATH', 'LD_LIBRARY_PATH_ORIG', '_PYI_ARCHIVE_FILE', runtime.HOST_ENVIRONMENT_KEY):
                self.assertNotIn(key, clean)

    def test_nested_tray_keeps_original_snapshot_and_unset_library_path(self):
        with patch.dict(os.environ, {'PATH': '/usr/bin:/bin'}, clear=True), patch.object(runtime.sys, 'frozen', True, create=True):
            runtime.capture_host_environment()
            snapshot = os.environ[runtime.HOST_ENVIRONMENT_KEY]
            os.environ.update(GTK_PATH='/bundle', GIO_MODULE_DIR='/bundle/gio_modules',
                              LD_LIBRARY_PATH='/bundle', LD_LIBRARY_PATH_ORIG='/bundle')
            runtime.capture_host_environment()
            self.assertEqual(os.environ[runtime.HOST_ENVIRONMENT_KEY], snapshot)
            clean = runtime.browser_environment()
            self.assertNotIn('LD_LIBRARY_PATH', clean)
            self.assertNotIn('GTK_PATH', clean)
            self.assertNotIn('GIO_MODULE_DIR', clean)

    def test_source_launch_keeps_existing_environment(self):
        with patch.dict(os.environ, {'GTK_PATH': '/user/gtk', 'GIO_MODULE_DIR': '/user/gio'}), patch.object(runtime.sys, 'frozen', False, create=True):
            self.assertEqual(runtime.browser_environment(), dict(os.environ))

    def test_real_launcher_receives_url_and_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            launcher = path/'xdg-open'
            launcher.write_text('#!/bin/sh\nprintf "%s" "$1" > "$TUXCUE_TEST_URL"\nprintf "test browser failure" >&2\nexit 3\n')
            launcher.chmod(0o755)
            env = dict(os.environ, PATH=folder, TUXCUE_TEST_URL=str(path/'url'))
            results = []
            output = io.StringIO()
            with patch.object(runtime, 'browser_environment', return_value=env), contextlib.redirect_stderr(output):
                worker = runtime.open_browser('http://127.0.0.1:8765', lambda *args: results.append(args))
                worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            self.assertEqual((path/'url').read_text(), 'http://127.0.0.1:8765')
            self.assertFalse(results[0][0])
            self.assertIn('test browser failure', results[0][1])
            self.assertIn('Open http://127.0.0.1:8765', output.getvalue())

    def test_success_missing_launcher_and_long_running_browser(self):
        for mode in ('success', 'missing', 'running'):
            with self.subTest(mode=mode):
                results = []
                with patch.object(runtime.subprocess, 'Popen') as popen, contextlib.redirect_stderr(io.StringIO()):
                    if mode == 'missing':
                        popen.side_effect = FileNotFoundError('xdg-open unavailable')
                    elif mode == 'running':
                        popen.return_value.wait.side_effect = subprocess.TimeoutExpired('xdg-open', 8)
                    else:
                        popen.return_value.wait.return_value = 0
                    worker = runtime.open_browser('http://127.0.0.1:8765', lambda *args: results.append(args))
                    worker.join(timeout=3)
                    self.assertEqual(results[0][0], mode != 'missing')
                    popen.return_value.kill.assert_not_called()
                    popen.return_value.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
