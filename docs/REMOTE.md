# TuxCue 0.4.6: phone and tray controls

## Start TuxCue

Launch `TuxCue-0.4.6-x86_64.AppImage` directly. If FUSE mounting is unavailable, use its `--appimage-extract-and-run` option.

Open <http://127.0.0.1:8765> on your PC. If the page was already open, refresh it and check that the header says 0.4.6. Your collection stays in its existing location, normally `~/TuxCue`.

## Connect your phone

1. Connect your phone and PC to the same home network. The PC can use Ethernet while the phone uses Wi-Fi.
2. In the PC interface, select **Remote control** in the top bar, then turn on **Enable Remote control**.
3. Select your Wi-Fi or Ethernet address if more than one is shown. Avoid a Docker/container address.
4. Select **Pair a phone** and scan the QR code with your phone camera. Alternatively, open the displayed address in the phone's browser and enter the eight-digit code.
5. Tap a sound tile on the phone. The sound plays on the PC using its selected audio routing. Connect the virtual microphone in TuxCue and select **TuxCue Microphone** in Discord to let friends hear it.

The phone interface supports sound tiles, search, set switching, local preview and Stop all. Preview is heard only through the PC's selected headphones/speakers. Audio is not streamed to the phone. You can bookmark the remote address or use your browser's Add to Home Screen command.

Pairing links/codes expire after five minutes and can be used once. A paired browser stays remembered for up to 30 days. You can forget a phone in the PC's Remote control settings; turning remote access off forgets all paired phones. Remote access uses HTTP on your trusted local network, with port 8766 by default.

If the phone cannot open the page, check that remote access is on and that you selected the correct address. Guest Wi-Fi or client isolation can prevent devices from reaching each other. If your PC firewall blocks incoming traffic, allow the configured TCP port from your home network. Do not forward this port on your internet router. The displayed address may change when the PC joins another network.

## Change the phone grid

Tap **Layout** at the top of the phone interface, then select **Rows** and **Columns**. The controls affect only this phone browser. Portrait and landscape are saved separately: rotate the phone, open Layout and choose the grid you want for that orientation. Settings are kept after a reload when browser storage is available.

Try **3 rows × 8 columns** in landscape for 24 square buttons per page, or **2 × 6** for larger buttons. Turn on **Compact view** to hide set, search and preview controls and give the grid more room. Open Layout and turn it off to bring those controls back. Small buttons show names without the extra shortcut/duration text. Very dense grids scroll within the board so the buttons stay tappable.

Use the arrows below the board to switch pages. Search covers the whole active sound set and starts at the first results page. Stop all remains available at the top. Reset portrait/landscape restores only that orientation’s defaults.

From version 0.4.4 onward, launch the newer AppImage or its updated launcher directly: it shuts down the older running version and takes over automatically. Phone pairing is retained, and a connected virtual microphone is reconnected. Refresh the phone page to load interface changes. The tray’s Restart command still restarts the version already running.

## System tray

A TuxCue icon appears in Cinnamon's system tray near the clock while the app is running. Its menu has **Open TuxCue**, **Stop all sounds**, **Restart TuxCue** and **Quit TuxCue**.

Closing the browser keeps TuxCue and its shortcuts running. Use **Quit TuxCue** to stop the service and remove its virtual audio devices. **Restart TuxCue** restarts the service, retains paired phones, and reconnects the virtual microphone if it was connected. Launch with `--no-tray` if you prefer browser controls only.
