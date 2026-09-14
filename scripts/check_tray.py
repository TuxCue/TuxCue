#!/usr/bin/env python3
"""Verify packaged tray registration, menu and cleanup in the desktop session."""
import os
import json
import sys
from pathlib import Path
import socket
import subprocess
import time
from gi.repository import Gio,GLib

project=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(project))
from soundboard.runtime import HOST_ENVIRONMENT_KEYS
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
def call(name,path,interface,method,signature,args):
 return bus.call_sync(name,path,interface,method,GLib.Variant(signature,args),None,Gio.DBusCallFlags.NONE,2000,None).unpack()
def registered():
 return call('org.kde.StatusNotifierWatcher','/StatusNotifierWatcher','org.freedesktop.DBus.Properties','Get','(ss)',('org.kde.StatusNotifierWatcher','RegisteredStatusNotifierItems'))[0]
def alive(name):
 return call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','NameHasOwner','(s)',(name,))[0]
name=None
import tempfile
with tempfile.TemporaryDirectory(prefix='tuxcue-tray-') as folder, tempfile.TemporaryFile(mode='w+') as log:
 root=Path(folder);launchers=root/'bin';launchers.mkdir();capture=root/'opened.json'
 opener=launchers/'xdg-open'
 opener.write_text('#!/usr/bin/python3\nimport os,sys,json\nfrom pathlib import Path\nPath(os.environ["TUXCUE_TRAY_CAPTURE"]).write_text(json.dumps({"url":sys.argv[1],"environment":{key:os.environ.get(key) for key in '+repr(HOST_ENVIRONMENT_KEYS)+'}}))\n')
 opener.chmod(0o755)
 env={**os.environ,'PATH':str(launchers)+os.pathsep+os.environ['PATH'],'TUXCUE_TRAY_CAPTURE':str(capture)}
 expected={key:env.get(key) for key in HOST_ENVIRONMENT_KEYS}
 proc=subprocess.Popen([str(Path(os.environ['TUXCUE_APPIMAGE'])),'--appimage-extract-and-run','--tray-worker','--port',str(port)],env=env,stdout=log,stderr=subprocess.STDOUT)
 try:
  for _ in range(100):
   matches=[item for item in registered() if item.endswith('/tuxcue_'+str(port))]
   if matches:break
   if proc.poll() is not None:log.seek(0);raise AssertionError(log.read())
   time.sleep(.05)
  else:raise AssertionError('Tray icon did not register')
  name,path=matches[0].split('/',1);path='/'+path
  properties=call(name,path,'org.freedesktop.DBus.Properties','GetAll','(s)',('org.kde.StatusNotifierItem',))[0]
  assert properties['Status']=='Active' and properties['Title']=='TuxCue'
  assert Path(properties['IconName']).is_file(),'The desktop cannot read the icon'
  layout=call(name,properties['Menu'],'com.canonical.dbusmenu','GetLayout','(iias)',(0,-1,['label']))[1]
  labels={item[1].get('label') for item in layout[2]}
  assert {'Open TuxCue','Stop all sounds','Restart TuxCue','Quit TuxCue'}<=labels,labels
  open_item=next(item[0] for item in layout[2] if item[1].get('label')=='Open TuxCue')
  call(name,properties['Menu'],'com.canonical.dbusmenu','Event','(isvu)',(open_item,'clicked',GLib.Variant('i',0),0))
  for _ in range(100):
   if capture.exists():break
   time.sleep(.05)
  else:raise AssertionError('Open TuxCue did not call the browser launcher')
  opened=json.loads(capture.read_text())
  assert opened['url']==f'http://127.0.0.1:{port}'
  assert opened['environment']==expected,'Tray leaked bundled paths into the browser environment'
  proc.terminate();proc.wait(timeout=5)
  for _ in range(100):
   if not alive(name):break
   time.sleep(.05)
  else:raise AssertionError('Tray companion did not exit when its launcher closed')
  print('PASS: packaged tray icon is active and readable; all four controls are present; Open TuxCue calls the browser with the restored host environment; companion exits with launcher.')
 finally:
  if proc.poll() is None:proc.terminate();proc.wait(timeout=5)
