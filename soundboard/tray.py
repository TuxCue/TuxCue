"""Desktop tray companion; GTK runs separately from the audio service."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import urllib.request

from .runtime import open_browser


def start_tray(port):
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        return None
    command = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, '-m', 'soundboard']
    return subprocess.Popen(command + ['--tray-worker', '--port', str(port), '--parent-pid', str(os.getpid())])


def send_action(port, action):
    if action not in ('stop', 'restart', 'shutdown'):
        raise ValueError('Unknown tray action.')
    request = urllib.request.Request(f'http://127.0.0.1:{port}/api/{action}', data=b'{}',
                                    headers={'Content-Type': 'application/json', 'X-Soundboard-Request': '1'})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status == 200


def run_tray(port, parent_pid):
    parent_pid = parent_pid or os.getppid()
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, GLib
        ready, _ = Gtk.init_check(None)
        if not ready:
            print('TuxCue: no desktop display is available for the tray icon.', file=sys.stderr)
            return 0
    except (ImportError, ValueError) as error:
        print(f'TuxCue: tray support is unavailable ({error}). The soundboard remains usable in your browser.', file=sys.stderr)
        return 0

    url = f'http://127.0.0.1:{port}'
    icon_path = str(Path(__file__).resolve().parent.parent/'frontend/dist/tuxcue-logo.png')
    menu = Gtk.Menu()
    status = Gtk.MenuItem.new_with_label('TuxCue is running')
    status.set_sensitive(False)
    menu.append(status)
    menu.append(Gtk.SeparatorMenuItem())
    items = []

    def action(name):
        for item in items:
            item.set_sensitive(False)
        status.set_label('Restarting TuxCue…' if name == 'restart' else 'Stopping TuxCue…' if name == 'shutdown' else 'Stopping sounds…')
        def work():
            try:
                send_action(port, name)
                message = 'TuxCue is running' if name != 'shutdown' else 'TuxCue is closing…'
            except Exception:
                message = 'Service unavailable — open TuxCue to check'
            def finished():
                status.set_label(message)
                for item in items:
                    item.set_sensitive(True)
                return False
            GLib.idle_add(finished)
        threading.Thread(target=work, name='tray-action', daemon=True).start()

    def open_from_tray(*_):
        status.set_label('Opening your browser…')
        def result(opened, error):
            def finished():
                status.set_label('TuxCue is running' if opened else f'Browser could not open — {url}')
                return False
            GLib.idle_add(finished)
        open_browser(url, on_result=result)

    for label, callback in [('Open TuxCue', open_from_tray),
                            ('Stop all sounds', lambda *_: action('stop')),
                            ('Restart TuxCue', lambda *_: action('restart')),
                            ('Quit TuxCue', lambda *_: action('shutdown'))]:
        item = Gtk.MenuItem.new_with_label(label)
        item.connect('activate', callback)
        menu.append(item)
        items.append(item)
    menu.show_all()

    try:
        gi.require_version('AyatanaAppIndicator3', '0.1')
        from gi.repository import AyatanaAppIndicator3 as Indicator
        icon = Indicator.Indicator.new(f'tuxcue-{port}', icon_path, Indicator.IndicatorCategory.APPLICATION_STATUS)
        icon.set_title('TuxCue')
        icon.set_menu(menu)
        icon.set_status(Indicator.IndicatorStatus.ACTIVE)
        print('TuxCue: system-tray icon ready (Ayatana).', flush=True)
    except (ImportError, ValueError):
        icon = Gtk.StatusIcon.new_from_file(icon_path)
        icon.set_title('TuxCue')
        icon.set_tooltip_text('TuxCue — click to open; right-click for controls')
        icon.connect('activate', open_from_tray)
        icon.connect('popup-menu', lambda _, button, when: menu.popup(None, None, None, None, button, when))
        icon.set_visible(True)
        print('TuxCue: system-tray icon ready (X11).', flush=True)

    def watch_parent():
        if parent_pid and os.getppid() != parent_pid:
            Gtk.main_quit()
            return False
        return True
    GLib.timeout_add_seconds(1, watch_parent)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    Gtk.main()
    return 0
