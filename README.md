# VidFetch — v1.4.4

**One-click audio / video from YouTube, Facebook, TikTok, Instagram, X and 1800+ other sites. No account, no ads, no cloud, nothing uploaded.**

VidFetch adds one blue icon beside the Like button on YouTube video pages only — nowhere else, no floating pill. Click one, the file is saved to a folder you pick. For everything else, paste a link into the toolbar popup and it goes through the same pipeline.

## WhatsApp Channel

Get VidFetch updates, new versions and help here:

**Join the WhatsApp channel: https://whatsapp.com/channel/0029VbDjJOH5kg75djXvbR0R**

New in 1.4.4 — **Ekbar setup, tarpor kokhono na:**
- `setup.bat` ekbar chalaleii VidFetch `%LOCALAPPDATA%\VidFetch`-e permanent hoye jay (download kora folder pore delete korle-o cholbe).
- Helper hidden background-e Windows-er sathe nijei start hoy. Kono window khola rakhte hoy na.
- Helper kono karone bondho thakle extension nijei seta abar chalu kore (native host).
- yt-dlp nijei update hoy (startup-e, 12 ghonta por por, ar YouTube change-er karone fail korle).
- ffmpeg na thakle setup winget diye install kore.
- Audio/Video download-e kokhono thumbnail save hoy na; Thumbnail shudhu Thumbnail button-e.

New in 1.4.0 — Icon sudhu YouTube Like button er pashe:

**VidFetch icon ekhon sudhu YouTube video page-e Like button er pashe ashe — ar kothao na.** Shorts-eo na, Facebook/TikTok/Instagram/X-eo na, channel page-eo na, screen-er kono konay vese thakbe na. Like button na thakle icon-o thakbe na. Onno site-er link download korte chaile toolbar-er VidFetch icon-e click kore popup-e link paste koro.

New in 1.3.0 — Audio, Video ar Thumbnail ekhon 3 ta alada download option:

**Like button er pasher menu-te ekhon 3 ta button — Audio / Video / Thumbnail.** Thumbnail chaple sudhu cover image (.jpg) download hobe, audio ba video download hobe na. Aki vabe Audio chaple sudhu audio, Video chaple sudhu video. Popup-eo eki 3 ta option ache. Agekar “Also save thumbnail” tick-ta ekhono ache — ota audio/video-r sathe thumbnail-o save kore.

New in 1.2.0 — Like button er pashe ekta icon, click korle sob option:

**On YouTube, a single blue VidFetch icon sits right beside the Like button.** Click it and a menu opens with Audio/Video, every quality (144p–4K, 96–320 kbps), audio format (MP3/M4A/WAV/FLAC), Playlist / Thumbnail / Subtitles, and Download. Shorts and Facebook/TikTok/Instagram/X keep the same icon as a floating pill with the same menu.

New in 1.1.0 (extras 1–5):
1. **Playlist / channel download** — tick “Full playlist / channel” in the popup, or the Playlist toggle next to the YouTube buttons. Every video in the playlist downloads into its own subfolder.
2. **Thumbnail + subtitles** — tick “Also save thumbnail” (.jpg) and “Also save subtitles” (English + Bangla .srt, when available).
3. **Download history + Open folder** — the popup shows your recent downloads, with an “Open folder” button and Clear.
4. **More audio formats** — MP3, M4A, WAV and FLAC. WAV/FLAC are lossless (no bitrate to pick); MP3/M4A use 96–320 kbps.
5. **Facebook / TikTok / Instagram / X buttons** — a floating VidFetch pill appears on video/Reel/status pages there, same audio/MP4 buttons.

It is a thin browser extension plus a small local helper that drives `yt-dlp` and `ffmpeg` on your own machine. Nothing leaves your computer. Port changed from the original 8765 to **8766**, so it will not clash if Gugu Grab is also installed.

```
YouTube / FB / TikTok page ──► extension ──► 127.0.0.1:8766 ──► yt-dlp + ffmpeg ──► your folder
```

## Install (Windows 10/11 + Chrome or Edge)

**1. Run the setup**
Double-click `setup.bat`. It finds Python, installs `yt-dlp`, checks for `ffmpeg`, and optionally sets the helper to start with Windows.

**2. Pick a save folder**
A browser tab opens at `http://127.0.0.1:8766/setup`. Choose a folder (default: `Music/VidFetch`) and click **Save**.

**3. Load the extension**
`setup.bat` prints the path. Then:
- open `chrome://extensions`
- turn on **Developer mode** (top right)
- click **Load unpacked**
- select the `extension` folder inside this one

Open any YouTube video — the blue VidFetch icon appears beside the Like button. Shorts, channel pages and other sites show no icon. For other sites, use the toolbar popup and paste the link.

## Usage

**On YouTube** — click the blue VidFetch icon beside Like. In the menu pick **Video**, **Audio** or **Thumbnail**, then the quality (Thumbnail-er kono quality lage na) — Video: Best / 4K / 1440p / 1080p / 720p / 480p / 360p / 240p / 144p; Audio: 320 / 192 / 128 / 96 kbps, format MP3 / M4A / WAV / FLAC. Tick Playlist / Thumbnail / Subtitles if you want them, then **Download**. The menu remembers your last choices.

**Anywhere else** — click the VidFetch icon in the toolbar, paste a link, pick Audio/Video + quality, tick Playlist / Thumbnail / Subtitles if you want them, hit **Grab**. The popup shows live progress (`47% · 2.3MiB/s · ETA 00:11`) and your recent downloads below.

**Playlist warning:** a big playlist is many files — it will take a while and use a lot of disk. Start with a small playlist first to check the folder layout.

Files are named after the video title plus the video ID, so re-downloading the same video is detected and skipped rather than duplicated. Playlist downloads go into a subfolder named after the playlist.

## Requirements

|  |  |
| --- | --- |
| OS | Windows 10 / 11 |
| Browser | Chrome, Edge, or any Chromium build (Manifest V3) |
| Python | 3.9+ — `setup.bat` finds an existing install or tells you what to get |
| ffmpeg | needed for audio conversion — `setup.bat` warns if missing (`winget install Gyan.FFmpeg`) |
| yt-dlp | installed automatically by `setup.bat` |

## How it works

- **`extension/`** — Manifest V3. Injects the buttons, sends the video URL to the helper, polls for progress, shows the toast. All network calls happen in the background worker, not the content script, so page CSP cannot block them.
- **`helper.py`** — a `ThreadingHTTPServer` on `127.0.0.1:8766`. Accepts jobs, runs `yt-dlp` in a thread, detects finished files by diffing a directory snapshot, and keeps `history.json` (last 100 downloads).
- **`setup.ps1` / `start-helper.bat` / `uninstall.bat`** — install, run, remove.

### Security model
- The helper binds to **loopback only**. Nothing on your network can reach it.
- `POST /download` accepts **only** `chrome-extension://` and `moz-extension://` origins — a random website cannot make your machine download something.
- `POST /config` additionally accepts the loopback setup page, so the folder picker works.
- Only one helper can hold the port; a second instance refuses and says so.

## Troubleshooting

**Buttons say "helper not running"** — the helper stopped. Run `start-helper.bat` and leave the window open.

**Buttons don't appear at all** — reload the extension at `chrome://extensions` (the card should read **1.4.4**), then hard-refresh the tab (Ctrl+Shift+R). Content scripts do not reinject into tabs that were already open.

**"This site is not supported"** — yt-dlp covers 1800+ sites but not all. Known gaps: WeChat Channels and anything that only exists inside a phone app, DRM-protected services (Netflix, Disney+, Spotify), and sites that need your logged-in session. VidFetch deliberately never touches your accounts, so those cannot be fixed by a patch.

**A download fails** — press F12 on the tab, open Console, and look for lines starting with `[VidFetch]`. The helper window also prints the exact error. In the popup, hover the red message to see yt-dlp's original wording.

**Playlist downloaded only some videos** — some videos in a playlist are private/deleted/geo-blocked. Those are skipped by yt-dlp; the rest still save.

**Audio format shows MP3 but I picked WAV** — the YouTube button label updates from the popup setting. Change it in the popup (Audio format dropdown), then refresh the YouTube tab.

## Legal

This is a UI over `yt-dlp`. It does not bypass DRM, paywalls or access controls, and it runs entirely on your machine with no server component.

**You are responsible for what you download.** Downloading copyrighted material without permission may be illegal where you live, and it breaks the terms of service of most platforms — YouTube, Facebook, Instagram, TikTok and the rest. Use it for content you own, content licensed for reuse (Creative Commons, public domain), or content you have explicit permission to copy.

## Credit

VidFetch 1.4.4 is built from [Gugu Grab](https://github.com/mustavirafid-dev/gugu-grab) by Mustavi Rafid (MIT licence) — rebranded to VidFetch with playlist, thumbnail/subtitle, history, WAV/FLAC/M4A and social-site buttons added. Original MIT licence kept in `LICENSE`.

## Licence

MIT — see `LICENSE`.
