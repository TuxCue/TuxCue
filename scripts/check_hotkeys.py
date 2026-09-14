#!/usr/bin/env python3
"""Check X11 shortcut ownership without sending key events to the desktop."""
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from soundboard.hotkeys import Hotkeys


def main():
    first,second=Hotkeys(lambda _:None),Hotkeys(lambda _:None)
    try:
        assert first.state()['available'],first.state()['error']
        assert second.state()['available'],second.state()['error']
        key=None
        for number in (9,10,11,12,8,7):
            candidate=f'Ctrl+Alt+Super+F{number}'
            first.configure({'test':candidate})
            if not first.state()['conflicts']:
                key=candidate;break
        assert key,'No unused test shortcut was available'
        second.configure({'test':key})
        assert second.state()['conflicts'],'Duplicate X11 ownership was not reported'
        first.suspend(.3)
        second.configure({'test':key})
        assert not second.state()['conflicts'],'Opening an editor did not release its keys'
        second.suspend(60)
        time.sleep(.5)
        assert not first.state()['suspended'],'Expired editor suspension did not recover'
        second.suspend(0)
        assert second.state()['conflicts'],'Automatic resume did not restore the original grab'
        first.configure({},enabled=False)
        second.configure({'test':key})
        assert not second.state()['conflicts'],'Disabling shortcuts did not release grabs'
        second.close();second=None
        first.configure({'test':key})
        assert not first.state()['conflicts'],'Closing the shortcut service left a grab behind'
        print('Passed: X11 registration, conflict reporting, editor suspension, automatic resume, disable, and shutdown cleanup.')
        print('No keypresses were generated. Actual key activation with a game focused needs a manual check.')
    finally:
        first.close()
        if second:second.close()

if __name__=='__main__':main()
