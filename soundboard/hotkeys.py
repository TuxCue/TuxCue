"""X11 passive key grabs. The browser does not need focus or remain open."""
import os
import queue
import select
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .boards import shortcut

KEY_NAMES = {'Backspace':'BackSpace','Space':'space','Enter':'Return','Escape':'Escape','PageUp':'Prior','PageDown':'Next',
             'Minus':'minus','Equal':'equal','Comma':'comma','Period':'period','Slash':'slash',
             'Backslash':'backslash','Semicolon':'semicolon','Apostrophe':'apostrophe',
             'BracketLeft':'bracketleft','BracketRight':'bracketright','Backquote':'grave'}


class Hotkeys:
    def __init__(self, callback, enabled=True):
        self.callback = callback
        self.commands = queue.Queue()
        self.available = False
        self.enabled = enabled
        self.error = None
        self.conflicts = []
        self.suspended_until = 0.0
        self._closed = threading.Event()
        self._ready = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='shortcut-action')
        self.thread = threading.Thread(target=self._run, name='x11-shortcuts', daemon=True)
        self.thread.start()
        self._ready.wait(2)

    def state(self):
        return {'available': self.available, 'enabled': self.enabled, 'error': self.error,
                'conflicts': list(self.conflicts), 'suspended': time.monotonic() < self.suspended_until}

    def _command(self, op, value):
        if not self.available:
            return
        done = threading.Event()
        self.commands.put((op, value, done))
        if not done.wait(3):
            self.error = 'The shortcut service did not respond. Restart the soundboard.'

    def configure(self, mapping, enabled=True):
        self.enabled = enabled
        self._command('configure', mapping if enabled else {})

    def suspend(self, seconds):
        self._command('suspend', seconds)

    def _run(self):
        connection = None
        try:
            if os.environ.get('XDG_SESSION_TYPE') != 'x11' or not os.environ.get('DISPLAY'):
                self.error = 'Global shortcuts currently require an X11 desktop session. Buttons still work.'
                return
            from Xlib import X, XK, display
            connection = display.Display()
            root = connection.screen().root
            mod_masks = {'Ctrl':X.ControlMask,'Alt':X.Mod1Mask,'Shift':X.ShiftMask,'Super':X.Mod4Mask}
            ignored = X.LockMask
            mapping = connection.get_modifier_mapping()
            for key_name in ('Num_Lock','Scroll_Lock'):
                code = connection.keysym_to_keycode(XK.string_to_keysym(key_name))
                for index, codes in enumerate(mapping):
                    if code and code in codes:
                        ignored |= 1 << index
            ignored_bits = [1 << i for i in range(8) if ignored & (1 << i)]
            variants = [0]
            for bit in ignored_bits:
                variants += [v | bit for v in list(variants)]
            registered, desired = {}, {}
            pressed, releases = set(), {}

            def clear():
                for code, mods in registered:
                    for extra in variants:
                        root.ungrab_key(code, mods | extra)
                connection.sync()
                registered.clear(); pressed.clear(); releases.clear()

            def bind():
                clear()
                errors = []
                for action, value in desired.items():
                    if not value:
                        continue
                    try:
                        normalized = shortcut(value)
                        parts = normalized.split('+')
                        name = parts[-1]
                        symbol = XK.string_to_keysym(KEY_NAMES.get(name, name.lower() if len(name)==1 else name))
                        code = connection.keysym_to_keycode(symbol)
                        mods = sum(mod_masks[p] for p in parts[:-1])
                        if not code:
                            raise ValueError(f'{value} is unavailable in this keyboard layout.')
                        failures = []
                        for extra in variants:
                            root.grab_key(code, mods | extra, False, X.GrabModeAsync, X.GrabModeAsync,
                                          onerror=lambda error, request: failures.append(error) or True)
                        connection.sync()
                        if failures:
                            for extra in variants:
                                root.ungrab_key(code, mods | extra)
                            errors.append(f'{value} is already used by another application.')
                        else:
                            registered[(code,mods)] = action
                    except ValueError as e:
                        errors.append(str(e))
                connection.sync()
                self.conflicts = errors

            self.available = True
            self._ready.set()
            paused = False
            while not self._closed.is_set():
                while True:
                    try:
                        op, value, done = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    try:
                        if op == 'configure':
                            desired = dict(value)
                            if not paused:
                                bind()
                        elif op == 'suspend':
                            self.suspended_until = time.monotonic() + value
                            if value > 0:
                                clear(); paused=True
                            else:
                                paused=False; bind()
                    finally:
                        done.set()
                if paused and time.monotonic() >= self.suspended_until:
                    paused=False; bind()
                while connection.pending_events():
                    event = connection.next_event()
                    if event.type == X.KeyRelease:
                        releases[event.detail] = event.time
                        pressed.discard(event.detail)
                    elif event.type == X.KeyPress:
                        repeating = event.detail in pressed or releases.get(event.detail) == event.time
                        pressed.add(event.detail)
                        action = registered.get((event.detail, event.state & ~ignored & 255))
                        if action and not repeating:
                            self._executor.submit(self.callback, action)
                select.select([connection.fileno()], [], [], .04)
            clear()
        except Exception:
            self.error = 'Could not connect to X11 for global shortcuts. Run the app from your desktop session.'
            self.available = False
        finally:
            self._ready.set()
            if connection:
                connection.close()

    def close(self):
        self._closed.set()
        self.thread.join(timeout=4)
        self._executor.shutdown(wait=True, cancel_futures=True)
