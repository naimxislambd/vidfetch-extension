# VidFetch — GitHub Upload: A–Z Guide (English)

Repo: **https://github.com/naimxislambd/vidfetch-extension**

WhatsApp channel: **https://whatsapp.com/channel/0029VbDjJOH5kg75djXvbR0R** — updates, new versions and help.

Current version: **v1.4.4** — helper auto-start (native messaging), yt-dlp auto-update, fixed extension ID.

## A. What is GitHub?
GitHub is where the code lives. All VidFetch files are stored here — the extension, the helper, the setup files, and the README. Anyone can download them from any PC, and new versions can replace the old files.

## B. What was done
1. Your `VidFetch-1.4.4.zip` was checked — version 1.4.4, thumbnails only from the Thumbnail button.
2. The helper version was fixed (the ZIP said 1.4.0, corrected to 1.4.4).
3. A new **public** repo was created on GitHub: `vidfetch-extension`.
4. The ZIP was uploaded to the repo and published as Release v1.4.4.
5. The 4 icon PNG files are inside the ZIP. The GitHub API only accepts text files, so icons are uploaded through the web UI, not the API.

## C. How to upload to GitHub yourself (web, no software needed)
1. Open https://github.com/new and sign in.
2. Repository name: `vidfetch-extension`
3. Description: `One VidFetch icon beside the Like button on YouTube - Audio, Video or Thumbnail download.`
4. Tick **Public**, tick **Add a README file**, click **Create repository**.
5. Open the repo, click **Add file → Upload files**.
6. Drag all files from your PC `vidfetch-extension` folder, click **Commit changes**.
7. To upload a ZIP: **Releases → Create a new release** → tag `v1.4.4` → attach the ZIP → **Publish release**.

## D. How to upload with Git (if Git is installed on the PC)
1. Open cmd in the folder.
2. `git init`
3. `git add .`
4. `git commit -m "VidFetch 1.4.4"`
5. `git branch -M main`
6. `git remote add origin https://github.com/naimxislambd/vidfetch-extension.git`
7. `git push -u origin main`

## E. How to install from GitHub (for anyone you share it with)
1. Open the repo link: https://github.com/naimxislambd/vidfetch-extension
2. Click the green **Code** button → **Download ZIP**.
3. Extract the ZIP.
4. In Chrome open `chrome://extensions` → turn **Developer mode** ON → **Load unpacked** → select the `extension` folder.
5. Run `setup.bat` once (installs Python + ffmpeg + yt-dlp, and sets the helper to auto-start with Windows login).
6. No need to keep `start-helper.bat` open — clicking the icon starts the helper by itself. To see the black window, run `start-helper-console.bat`; to stop it, run `stop-helper.bat`.
7. Open a YouTube video — the blue VidFetch icon appears beside the Like button. Click it for the Audio / Video / Thumbnail menu.

## F. How to update to a new version
1. Increase the version number in `extension/manifest.json` and in `helper.py` (`VERSION`).
2. Write a "New in" line in the README.
3. Make a ZIP and publish it in **Releases** as `v1.4.5` (the next number).
4. To change an existing file, open it in the repo, click the **pencil icon (Edit)**, change it, and click **Commit changes**.

## G. File list — what each file does
| File | What it does |
|---|---|
| `extension/manifest.json` | Extension name, version, permissions |
| `extension/content.js` | Puts the icon beside the Like button + the menu |
| `extension/popup.js` / `popup.html` | The toolbar icon popup |
| `extension/background.js` | Sends download requests to the helper |
| `extension/style.css` | Icon + menu design |
| `extension/icons/*.png` | Extension icons (16/32/48/128) |
| `helper.py` | Downloads on the PC (yt-dlp + ffmpeg), port 8766 |
| `native_host.py` | Starts the helper automatically when the icon is clicked |
| `setup.bat` / `setup.ps1` | Installs Python + ffmpeg + yt-dlp |
| `start-helper.bat` | Starts the helper |
| `start-helper-console.bat` | Starts the helper with a visible console window |
| `stop-helper.bat` | Stops the helper |
| `uninstall.bat` | Uninstalls the helper |
| `README.md` | Install + usage instructions |
| `LICENSE` | MIT licence — Gugu Grab (Mustavi Rafid) credit |

## H. Things to remember
- If the helper is not running, downloads will not work — the icon will show, but it will say "helper not running".
- Audio/Video downloads do not include a thumbnail — click the separate **Thumbnail** button for the cover image.
- If "Full playlist / channel" is ticked, the whole playlist downloads — leave it off for a single video.
