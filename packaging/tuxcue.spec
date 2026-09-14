from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root/'packaging/entry.py')], pathex=[str(root)],
    binaries=[('/opt/tuxcue-media/bin/ffmpeg','bin'),('/opt/tuxcue-media/bin/ffprobe','bin'),('/usr/bin/pactl','bin')],
    datas=[(str(root/'frontend/dist'),'frontend/dist'),(str(root/'LICENSE'),'.'),(str(root/'THIRD_PARTY_NOTICES.md'),'.')],
    hiddenimports=collect_submodules('Xlib')+[
        'uvicorn.logging','uvicorn.loops.asyncio','uvicorn.protocols.http.h11_impl','uvicorn.lifespan.on',
        'gi.repository.Gst','gi.repository.GObject','gi.repository.GLib',
        'gi.repository.Gtk','gi.repository.AyatanaAppIndicator3','qrcode.image.svg',
    ],
    runtime_hooks=[str(root/'packaging/pyi_rth_host_environment.py')],
    hooksconfig={'gstreamer':{'include_plugins':['coreelements','playback','audioconvert','audioresample','typefindfunctions','wavparse','volume','pulseaudio']},
                 'gi':{'languages':[],'icons':[],'themes':[]}},
    excludes=['tkinter','matplotlib','numpy','PIL'],
)
import json
(root/'native-files.json').write_text(json.dumps(sorted({entry[1] for entry in [*analysis.binaries, *analysis.datas, *analysis.pure] if entry[1]})))
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='tuxcue', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
bundle = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name='tuxcue')
