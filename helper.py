#!/usr/bin/env python3
r"""
helper.py - local download helper for the VidFetch extension.

VidFetch 1.2.0 adds: playlist/channel download, thumbnail+subtitle
saving, download history + open-folder, WAV/FLAC/M4A audio, and
floating buttons on Facebook / TikTok / Instagram / X.

Listens on 127.0.0.1:8766, accepts jobs from the browser extension, and runs
yt-dlp + ffmpeg to save audio (MP3) or video (MP4) into the inbox folder.

Run it, then click the button on any YouTube page.

    python helper.py              # default port 8766, inbox = ~\Music\VidFetch
    python helper.py --port 9000
    python helper.py --inbox "D:\\Music"

After running setup.bat once, the helper starts by itself with Windows and runs hidden.
"""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.4.4"

# --- background mode (pythonw.exe) -----------------------------------------
# Started at login by pythonw there is no console: stdout/stderr are None and
# child processes would each flash a window. So: log to a file instead, run
# yt-dlp with the console python.exe, and hide the child windows.
HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
BACKGROUND = sys.stdout is None or sys.stderr is None
if BACKGROUND:
    try:
        _lf = open(HERE / "helper.log", "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _lf
        if sys.stderr is None:
            sys.stderr = _lf
    except OSError:
        pass


def _python_exe():
    exe = sys.executable
    if IS_WIN and exe.lower().endswith("pythonw.exe"):
        cand = exe[: -len("pythonw.exe")] + "python.exe"
        if os.path.exists(cand):
            return cand
    return exe


PYEXE = _python_exe()
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0
ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")
LOOPBACK_PREFIXES = ("http://127.0.0.1:", "http://localhost:", "http://[::1]:")

JOBS = {}
JOBS_LOCK = threading.Lock()
# serialises the actual download+rename so two jobs never touch the same file
RUN_LOCK = threading.Lock()
UPDATE_LOCK = threading.Lock()
INBOX = None
PORT = 8766
MAX_JOBS = 200
OPEN_FOLDER = True
_open_state = {"opened": False, "saved": 0}
# Monotonic ticket so the popup can say "2 jobs ahead of you". Threads start in
# creation order, but they queue on RUN_LOCK, so the ticket is the real order.
_seq = {"next": 0}

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def default_inbox():
    return Path(os.environ.get("USERPROFILE", ".")) / "Music" / "VidFetch"


def load_config():
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as e:
            print(f"  (config.json unreadable: {e})", flush=True)
    return {}


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception as e:
        print(f"  (could not write config.json: {e})", flush=True)
        return False


HISTORY_PATH = Path(__file__).resolve().parent / "history.json"
HISTORY_LOCK = threading.Lock()
MAX_HISTORY = 100

def load_history():
    try:
        if HISTORY_PATH.exists():
            data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def add_history(entry):
    with HISTORY_LOCK:
        items = load_history()
        items.insert(0, entry)
        items = items[:MAX_HISTORY]
        try:
            HISTORY_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"  (could not write history: {e})", flush=True)

def log(msg):
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] {msg}", flush=True)


def refresh_windows_path():
    """A helper started at login can miss programs installed afterwards (e.g.
    ffmpeg via winget). Re-read PATH from the registry so they are found."""
    if not IS_WIN:
        return
    try:
        import winreg
        extra = []
        for hive, sub in (
            (winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
            (winreg.HKEY_CURRENT_USER, "Environment"),
        ):
            try:
                with winreg.OpenKey(hive, sub) as k:
                    val, _ = winreg.QueryValueEx(k, "Path")
                    extra.append(os.path.expandvars(val))
            except OSError:
                pass
        local = os.environ.get("LOCALAPPDATA")
        if local:
            extra.append(os.path.join(local, "Microsoft", "WinGet", "Links"))
        os.environ["PATH"] = os.environ.get("PATH", "") + ";" + ";".join(extra)
    except Exception:
        pass


# --- yt-dlp keeps itself current -------------------------------------------
# YouTube changes often and an old yt-dlp then fails with "unable to extract" /
# 403 / "sign in". Updating it by hand is exactly the chore this avoids.
STALE_RE = re.compile(
    r"unable to extract|nsig|sign in to confirm|http error 403|http error 400"
    r"|requested format is not available|only images are available"
    r"|player response|unable to download (video|webpage)|precondition check",
    re.I)
UPDATE_EVERY = 12 * 3600


def ytdlp_version():
    try:
        r = subprocess.run([PYEXE, "-m", "yt_dlp", "--version"],
                           stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, timeout=60, creationflags=NO_WINDOW)
        return (r.stdout or "").strip()
    except Exception:
        return ""


_last_update = {"t": 0.0}


def update_ytdlp(min_gap=0):
    """pip install -U yt-dlp. Returns True if the version changed.
    min_gap: skip (return False) if an update already ran this recently."""
    with UPDATE_LOCK:
        if min_gap and time.time() - _last_update["t"] < min_gap:
            return False
        _last_update["t"] = time.time()
        old = ytdlp_version()
        try:
            subprocess.run(
                [PYEXE, "-m", "pip", "install", "--quiet", "--upgrade",
                 "--disable-pip-version-check", "yt-dlp"],
                stdin=subprocess.DEVNULL, capture_output=True,
                timeout=300, creationflags=NO_WINDOW)
        except Exception as e:
            log(f"yt-dlp update failed: {e}")
            return False
        new = ytdlp_version()
        if new and new != old:
            log(f"yt-dlp updated {old or '?'} -> {new}")
            return True
        return False


def _update_loop():
    time.sleep(20)  # let the helper settle first
    while True:
        # never replace yt-dlp's files while a download is using them
        with RUN_LOCK:
            try:
                update_ytdlp()
            except Exception as e:
                log(f"update check error: {e}")
        time.sleep(UPDATE_EVERY)


def safe(name, limit=150):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:limit].rstrip(" .") or "untitled"


MEDIA_EXT = (".mp3", ".mp4", ".m4a", ".webm", ".opus", ".flac", ".wav")
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
AUDIO_FORMATS = {"mp3", "wav", "flac", "m4a"}


QUALITY_HEIGHTS = {"best": None, "2160": 2160, "1440": 1440,
                   "1080": 1080, "720": 720, "480": 480,
                   # small sizes matter more than pixels when the point is to
                   # have the file now, so the low end is offered too
                   "360": 360, "240": 240, "144": 144}
# MP3 target bitrate in kbps. Re-encoding a 34 kbps source at 320 kbps only
# makes the file ten times bigger, so the low end is a real choice.
AUDIO_KBPS = {"320", "192", "128", "96"}


def build_cmd(url, fmt, quality="1080", box=None, playlist=False,
              audio_format="mp3", thumbnail=False, subtitles=False):
    box = box or INBOX
    # Playlist/channel: save inside a subfolder named after the playlist.
    if playlist:
        out_tmpl = str(box / "%(playlist_title).100B/%(title,id).140B [%(id)s].%(ext)s")
    else:
        # %(title,id) = title, falling back to the video id if the title is empty
        out_tmpl = str(box / "%(title,id).140B [%(id)s].%(ext)s")
    cmd = [
        PYEXE, "-m", "yt_dlp",
        "--newline",
        "--no-warnings",
        "--no-mtime",
        "--no-overwrites",
        "--continue",
        "--windows-filenames",
        # YouTube DASH streams arrive as thousands of small fragments. Fetching
        # them one at a time is the main reason a long MP4 crawls - four in
        # parallel is usually 3-5x faster on the same connection.
        "--concurrent-fragments", "4",
        "--retries", "10",
        "--fragment-retries", "10",
        # A dropped connection used to throw away everything downloaded so far
        # and start the file again - that is how one flaky minute turned into a
        # seven minute job. Fetching in 10 MB ranges means a reset costs one
        # range, not the whole transfer.
        "--http-chunk-size", "10M",
        # Fail a dead socket in 15s instead of 30s, and do not sit out long
        # sleeps between attempts.
        "--socket-timeout", "15",
        "--retry-sleep", "1",
        "--output", out_tmpl,
    ]
    if playlist:
        cmd += ["--yes-playlist"]
    else:
        cmd += ["--no-playlist"]
    # Thumbnails are ONLY saved when the user picks "Thumbnail". Audio/Video
    # downloads never write or embed a cover image.
    cmd += ["--no-write-thumbnail", "--no-embed-thumbnail"] if fmt != "thumb" else []
    if subtitles:
        cmd += ["--write-subs", "--write-auto-subs",
                "--sub-langs", "en,bn.*", "--convert-subs", "srt",
                "--embed-subs"]
    if fmt == "thumb":
        # Thumbnail only: no audio/video at all, just the cover image as .jpg.
        # --skip-download stops yt-dlp fetching the media stream, and the
        # output template keeps the .jpg next to where the video would go.
        cmd += [
            "--skip-download",
            "--write-thumbnail",
            "--convert-thumbnails", "jpg",
        ]
    elif fmt == "mp4":
        height = QUALITY_HEIGHTS.get(str(quality), 1080)
        if height is None:                      # best available, could be 4K/8K
            selector = "bv*+ba/b"
        else:
            selector = f"bv*[height<={height}]+ba/b[height<={height}]/b"
        cmd += [
            "--format", selector,
            "--merge-output-format", "mp4",
            "--embed-metadata",
        ]
    else:
        afmt = audio_format if audio_format in AUDIO_FORMATS else "mp3"
        cmd += [
            "--extract-audio",
            "--audio-format", afmt,
            "--embed-metadata",
        ]
        # WAV/FLAC are lossless - no bitrate to pick; MP3/M4A use the bitrate.
        if afmt in ("wav", "flac"):
            cmd += ["--audio-quality", "0"]
        else:
            kbps = str(quality) if str(quality) in AUDIO_KBPS else "320"
            cmd += ["--audio-quality", kbps + "K"]
    cmd.append(url)
    return cmd


PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")
SPEED_RE = re.compile(r"\bat\s+([\d.]+\s*[KMGT]?i?B/s)")
ETA_RE = re.compile(r"\bETA\s+([\d:]+)")
# "[download]  34.5% of  53.34MiB at ..." -> 53.34MiB
SIZE_RE = re.compile(r"\bof\s+~?\s*([\d.]+\s*[KMGT]?i?B)")


def read_progress(job_id, line):
    """Turn one yt-dlp output line into job state, so the browser can show a
    real percentage instead of an indefinite spinner."""
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if not j:
            return
        m = PROGRESS_RE.search(line)
        if m:
            j["stage"] = "downloading"
            j["percent"] = round(float(m.group(1)), 1)
            s = SPEED_RE.search(line)
            if s:
                j["speed"] = s.group(1).replace(" ", "")
            e = ETA_RE.search(line)
            if e:
                j["eta"] = e.group(1)
            z = SIZE_RE.search(line)
            if z:
                j["size"] = z.group(1).replace(" ", "")
            return
        if "Retrying (" in line or "Got error" in line:
            # The percentage stops climbing while yt-dlp backs off. Say so,
            # otherwise a retry looks exactly like a hang.
            j["stage"] = "retrying"
            return
        if line.startswith("[download]"):
            # Destination: / fragment chatter - the transfer has begun even
            # though no percentage has been printed yet.
            j["stage"] = "downloading"
            return
        if line.startswith("[Merger]") or "Merging formats" in line:
            j["stage"] = "merging"
            j["percent"] = 100.0
        elif line.startswith(("[ExtractAudio]", "[ffmpeg]", "[FixupM3u8]")):
            j["stage"] = "converting"
        elif line.startswith("[Metadata]") or "Embedding" in line:
            j["stage"] = "tagging"


def snapshot(box=None):
    """Map of filename -> size, so we can detect what a job produced without
    trusting subprocess stdout (which mangles non-ASCII on Windows consoles)."""
    box = box or INBOX
    try:
        return {p.name: p.stat().st_size for p in box.iterdir() if p.is_file()}
    except OSError:
        return {}


def tidy_name(name):
    """Strip the stray leading space you get when a title is empty."""
    return re.sub(r"^\s*\[\w[\w-]*\]", lambda m: m.group(0).lstrip(), name).strip()


def announce_saved(src):
    """Make a successful save impossible to miss in the console."""
    try:
        mb = src.stat().st_size / (1024 * 1024)
    except OSError:
        mb = 0.0
    _open_state["saved"] += 1
    n = _open_state["saved"]

    print("", flush=True)
    print("  " + "=" * 60, flush=True)
    print(f"    SAVED  #{n}      {mb:.1f} MB      {time.strftime('%H:%M:%S')}", flush=True)
    print(f"    {src.name}", flush=True)
    print(f"    -> {src.parent}", flush=True)
    print("  " + "=" * 60, flush=True)
    print("", flush=True)

    if OPEN_FOLDER and not _open_state["opened"]:
        _open_state["opened"] = True
        try:
            subprocess.Popen(["explorer", str(src.parent)], close_fds=True)
            print("  (opened the folder for you - only happens once)", flush=True)
        except Exception as e:
            print(f"  (could not open the folder: {e})", flush=True)


def run_job(job_id, url, fmt, quality="1080", playlist=False,
            audio_format="mp3", thumbnail=False, subtitles=False):
    # One download at a time. Two jobs for the same video write to the same
    # filenames, and Windows then refuses yt-dlp's rename with WinError 32.
    with RUN_LOCK:
        _run_locked(job_id, url, fmt, quality, playlist, audio_format, thumbnail, subtitles)
        with JOBS_LOCK:
            j = JOBS.get(job_id, {})
            stale = (j.get("status") == "error"
                     and STALE_RE.search(str(j.get("error_raw", "")) + " " + str(j.get("error", ""))))
        if stale:
            log(f"job {job_id[:8]} looks like an outdated yt-dlp - updating and retrying once")
            with JOBS_LOCK:
                orig = {k: JOBS[job_id].get(k, "") for k in ("error", "error_raw")}
                JOBS[job_id].update(status="running", stage="updating yt-dlp", error="")
            if update_ytdlp(min_gap=1800):
                _run_locked(job_id, url, fmt, quality, playlist, audio_format, thumbnail, subtitles)
            else:
                # nothing newer exists - keep the original failure
                with JOBS_LOCK:
                    JOBS[job_id].update(status="error", stage="", **orig)


def _run_locked(job_id, url, fmt, quality="1080", playlist=False,
              audio_format="mp3", thumbnail=False, subtitles=False):
    # pin the folder for this job: the user may change it at /setup while we
    # are downloading, and the before/after diff must span one directory only
    box = INBOX
    with JOBS_LOCK:
        # "starting" matters: yt-dlp can spend several seconds resolving the
        # link before it prints a single progress line. Without this the popup
        # sat at 0% with nothing to show and looked frozen.
        JOBS[job_id].update(status="running", started=time.time(),
                            stage="starting")
    log(f"job {job_id[:8]} start  fmt={fmt}  q={quality}  playlist={playlist}  audio={audio_format}  {url}")

    before = snapshot(box)
    # Popen + line streaming, not subprocess.run: yt-dlp prints progress as it
    # goes and we want to surface it. The finished file is still found by the
    # directory diff, never by parsing this output.
    chunks = []
    proc = subprocess.Popen(
        build_cmd(url, fmt, quality, box, playlist, audio_format, thumbnail, subtitles),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=NO_WINDOW,
    )
    try:
        for raw in proc.stdout:
            chunks.append(raw)
            read_progress(job_id, raw.strip())
    finally:
        proc.wait()
    after = snapshot(box)

    # Safety net: audio/video jobs must never leave a thumbnail behind.
    if fmt != "thumb":
        for n in list(after):
            if n not in before and n.lower().endswith(IMAGE_EXT):
                try:
                    (box / n).unlink()
                except OSError:
                    pass
                after.pop(n, None)

    # anything new on disk is a product of this job
    # Thumbnail-only jobs produce a .jpg, not media - count images for them.
    _exts = MEDIA_EXT + IMAGE_EXT if fmt == "thumb" else MEDIA_EXT
    new_media = [
        n for n in after
        if n not in before and n.lower().endswith(_exts)
    ]
    combined = "".join(chunks).strip()
    # Take the longest line that mentions ERROR: when a process is killed
    # mid-write the last line is often a truncated "ERROR:" with no message.
    err_lines = [ln.strip() for ln in combined.splitlines() if "ERROR" in ln]
    # A killed process leaves a bare "ERROR:" - that is not a message.
    err_lines = [ln for ln in err_lines if ln.strip(" :") != "ERROR"]
    err_line = max(err_lines, key=len) if err_lines else ""

    with JOBS_LOCK:
        j = JOBS[job_id]
        j["ended"] = time.time()

        if new_media:
            # newest file wins
            pick = max(new_media, key=lambda n: after.get(n, 0))
            src = box / pick
            clean = tidy_name(pick)
            if clean != pick and not (box / clean).exists():
                # antivirus scanners and media players hold files briefly
                for _ in range(6):
                    try:
                        src.rename(box / clean)
                        src = box / clean
                        break
                    except OSError:
                        time.sleep(0.5)
            try:
                size_bytes = src.stat().st_size
            except OSError:
                size_bytes = 0
            # VidFetch history: record every file this job produced.
            for n in new_media:
                try:
                    _p = box / n
                    add_history({"name": n, "file": str(_p),
                                 "bytes": _p.stat().st_size if _p.exists() else 0,
                                 "format": fmt, "url": url,
                                 "time": time.strftime("%Y-%m-%d %H:%M")})
                except Exception:
                    pass
            disp_name = src.name if len(new_media) == 1 else f"{src.name}  (+{len(new_media)-1} more)"
            j.update(status="done", file=str(src), name=disp_name, stage="",
                     bytes=size_bytes, files=len(new_media))
            announce_saved(src)
            return

        # nothing new: either it was already there, or it genuinely failed
        if proc.returncode == 0 or "has already been" in combined:
            j.update(status="done", file="", name="already in inbox", stage="")
            log(f"job {job_id[:8]} skip   already present")
            return

        err = err_line or combined[-400:] or f"yt-dlp exited {proc.returncode}"
        j.update(status="error", error=friendly_error(err, url),
                 error_raw=err, stage="")
        log(f"job {job_id[:8]} error  {err[:200]}")


# yt-dlp's errors are written for people who already know yt-dlp. The popup
# has one line to work with, so the common ones get translated into something
# that says what happened and what to do about it.
ERROR_HINTS = [
    # Site-specific first: "Unsupported URL" is also what a known-but-blocked
    # site produces, and the generic line would bury the useful one.
    (r"weixin\.qq\.com|channels\.weixin\.qq\.com",
     "WeChat Channels (视频号) is not supported by the engine. Its videos are "
     "locked inside the WeChat app, so there is no link to download. Screen-record "
     "it instead."),
    (r"Unsupported URL",
     "This site is not supported. The engine covers 1800+ sites, but not this one."),
    (r"Private video|This video is private",
     "This video is private. Only the owner can download it."),
    (r"Video unavailable|has been removed|no longer available",
     "This video is unavailable. It was deleted, made private, or blocked."),
    (r"members[- ]only|Join this channel",
     "This video is members-only. The engine has no access to your paid account."),
    (r"Sign in to confirm|login required|requires authentication|cookies",
     "The site wants a logged-in session. VidFetch does not touch your accounts, "
     "so this one cannot be fetched."),
    (r"not available in your country|geo[- ]?restrict|blocked it in your country",
     "This video is geo-blocked in your region."),
    (r"DRM|digital rights management|protected by",
     "This video is DRM-protected. It cannot be downloaded by any tool."),
    (r"HTTP Error 404",
     "The page does not exist (404). The link may be wrong or the video was deleted."),
    (r"HTTP Error 403",
     "The site refused the request (403). It usually means the link expired or "
     "needs a login."),
    (r"HTTP Error 429|Too Many Requests",
     "The site is rate-limiting you (429). Wait a few minutes and try again."),
    (r"timed out|timeout|Connection reset|Temporary failure",
     "The connection dropped. Check your internet and try again."),
    (r"Unable to download webpage|Failed to resolve",
     "Could not reach that page. Check the link opens in a normal browser tab."),
    (r"Requested format is not available",
     "That quality is not offered for this video. Try 1080p or Best available."),
]


def friendly_error(raw, url=""):
    """Map a yt-dlp error to one readable line, keeping the raw text as detail."""
    blob = f"{raw} {url}"
    for pattern, message in ERROR_HINTS:
        if re.search(pattern, blob, re.I):
            return message
    return raw



def prune_jobs():
    with JOBS_LOCK:
        if len(JOBS) <= MAX_JOBS:
            return
        finished = sorted(
            (j for j in JOBS.values() if j["status"] in ("done", "error")),
            key=lambda j: j.get("ended", 0),
        )
        for j in finished[: len(JOBS) - MAX_JOBS]:
            JOBS.pop(j["id"], None)


def setup_page(current: Path) -> str:
    """Tiny local page so a new user only has to pick a folder."""
    home = Path(os.environ.get("USERPROFILE", "."))
    picks = []
    for label, p in [
        ("Music / VidFetch", home / "Music" / "VidFetch"),
        ("Music", home / "Music"),
        ("Downloads", home / "Downloads"),
        ("Desktop", home / "Desktop"),
        ("Videos", home / "Videos"),
    ]:
        if p.parent.exists():
            picks.append((label, str(p)))

    buttons = "".join(
        f'<button class="pick" data-path="{p}">{label}<span>{p}</span></button>'
        for label, p in picks
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>VidFetch - choose a folder</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; padding:40px 20px; font-family:-apple-system,"Segoe UI",Roboto,sans-serif;
         background:#f6f7f9; color:#111; }}
  .card {{ max-width:640px; margin:0 auto; background:#fff; border-radius:14px;
           padding:32px; box-shadow:0 2px 20px rgba(0,0,0,.08); }}
  h1 {{ font-size:21px; margin:0 0 6px; }}
  .sub {{ color:#666; font-size:14px; margin-bottom:24px; }}
  .label {{ font-size:12px; text-transform:uppercase; letter-spacing:.6px;
            color:#888; margin:22px 0 8px; font-weight:600; }}
  .pick {{ display:block; width:100%; text-align:left; padding:12px 14px; margin-bottom:8px;
           border:1px solid #e2e4e8; border-radius:9px; background:#fafbfc; cursor:pointer;
           font-size:14px; font-family:inherit; }}
  .pick:hover {{ background:#f0f4ff; border-color:#b9c8ff; }}
  .pick span {{ display:block; color:#8a8f98; font-size:12px; margin-top:3px;
                word-break:break-all; }}
  input[type=text] {{ width:100%; padding:11px 13px; border:1px solid #d9dce1;
                      border-radius:9px; font-size:14px; font-family:inherit; }}
  .row {{ display:flex; gap:10px; margin-top:12px; }}
  .save {{ flex:0 0 auto; padding:11px 22px; border:0; border-radius:9px;
           background:#2563eb; color:#fff; font-size:14px; font-weight:600; cursor:pointer; }}
  .save:hover {{ background:#1d4ed8; }}
  .cur {{ background:#eef7ee; border:1px solid #cfe6cf; padding:12px 14px;
          border-radius:9px; font-size:13px; word-break:break-all; }}
  .ok {{ color:#1a7f37; font-weight:600; }}
  .note {{ margin-top:26px; padding-top:18px; border-top:1px solid #eee;
           font-size:12.5px; color:#777; line-height:1.6; }}
</style></head>
<body><div class="card">
  <h1>VidFetch</h1>
  <div class="sub">Choose where your downloads should be saved. That's the only setting.</div>

  <div class="label">Currently saving to</div>
  <div class="cur" id="cur">{current}</div>

  <div class="label">Pick a folder</div>
  {buttons}

  <div class="label">Or type any path</div>
  <div class="row">
    <input type="text" id="custom" placeholder="D:\\Music\\VidFetch">
    <button class="save" id="save">Save</button>
  </div>

  <div class="note">
    You can close this tab after saving. The browser buttons work immediately -
    no restart needed. To change the folder later, open
    <b>http://127.0.0.1:8766/setup</b> again.
  </div>
</div>
<script>
  const cur = document.getElementById('cur');
  const custom = document.getElementById('custom');

  async function apply(path) {{
    if (!path) return;
    cur.textContent = 'saving...';
    try {{
      const r = await fetch('/config', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ folder: path }})
      }});
      const j = await r.json();
      if (r.ok) {{
        cur.textContent = j.inbox;
        cur.className = 'cur ok';
      }} else {{
        cur.textContent = 'error: ' + (j.error || r.status);
        cur.className = 'cur';
      }}
    }} catch (e) {{
      cur.textContent = 'error: ' + e.message;
    }}
  }}

  document.querySelectorAll('.pick').forEach(b => {{
    b.addEventListener('click', () => apply(b.dataset.path));
  }});
  document.getElementById('save').addEventListener('click', () => apply(custom.value.trim()));
  custom.addEventListener('keydown', e => {{ if (e.key === 'Enter') apply(custom.value.trim()); }});
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = f"VidFetchHelper/{VERSION}"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep the console clean; we log our own lines

    # ---- helpers -------------------------------------------------------
    def origin_ok(self, allow_loopback=False):
        origin = self.headers.get("Origin", "")
        if not origin:
            return True                      # curl / local scripts
        if origin.startswith(ALLOWED_ORIGIN_PREFIXES):
            return True
        if allow_loopback and origin.startswith(LOOPBACK_PREFIXES):
            return True                      # the /setup page itself
        return False

    def cors(self):
        origin = self.headers.get("Origin", "")
        if origin.startswith(ALLOWED_ORIGIN_PREFIXES):
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")

    def reply(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def body_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def handle_config(self):
        """Called from the /setup page - this is the only setting a new user touches."""
        global INBOX
        data = self.body_json()
        folder = (data.get("folder") or "").strip().strip('"').strip("'")
        if not folder:
            self.reply(400, {"error": "folder is required"})
            return

        folder = os.path.expandvars(os.path.expanduser(folder))
        target = Path(folder)
        if not target.is_absolute():
            self.reply(400, {"error": "give a full path, like D:\\Music\\VidFetch"})
            return
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.reply(400, {"error": f"cannot create that folder: {e}"})
            return

        INBOX = target
        cfg = load_config()
        cfg["inbox"] = str(target)
        save_config(cfg)
        log(f"folder set  -> {target}")
        self.reply(200, {"ok": True, "inbox": str(target)})

    # ---- routes --------------------------------------------------------
    def do_OPTIONS(self):
        if not self.origin_ok(allow_loopback=True):
            self.reply(403, {"error": "origin not allowed"})
            return
        self.send_response(204)
        self.cors()
        # Chrome Private Network Access: extension -> loopback needs an explicit opt-in
        if (self.headers.get("Access-Control-Request-Private-Network") or "").lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self.origin_ok():
            self.reply(403, {"error": "origin not allowed"})
            return

        if self.path in ("/setup", "/setup/"):
            body = setup_page(INBOX).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/health":
            self.reply(200, {
                "ok": True, "version": VERSION,
                "inbox": str(INBOX), "jobs": len(JOBS),
            })
            return

        if self.path == "/history":
            self.reply(200, {"history": load_history(), "inbox": str(INBOX)})
            return

        if self.path == "/jobs":
            now = time.time()
            with JOBS_LOCK:
                items = sorted(JOBS.values(), key=lambda j: j.get("started", 0),
                               reverse=True)[:50]
                out = []
                for j in items:
                    row = dict(j)
                    row["elapsed"] = round(
                        (j.get("ended") or now) - j.get("started", now), 1)
                    row["ahead"] = sum(
                        1 for o in JOBS.values()
                        if o["status"] in ("pending", "running")
                        and o.get("seq", 0) < j.get("seq", 0)
                    )
                    out.append(row)
            self.reply(200, {"jobs": out})
            return

        m = re.match(r"^/jobs/([0-9a-f\-]+)$", self.path)
        if m:
            with JOBS_LOCK:
                job = JOBS.get(m.group(1))
            if not job:
                self.reply(404, {"error": "no such job"})
            else:
                # elapsed lets the popup prove it is alive even at 0%: yt-dlp
                # can chew on a long playlist or a slow host for a while
                # before the first progress line appears.
                out = dict(job)
                end = job.get("ended") or time.time()
                out["elapsed"] = round(end - job.get("started", end), 1)
                # how many unfinished jobs are in front of this one in the queue
                mine = job.get("seq", 0)
                out["ahead"] = sum(
                    1 for j in JOBS.values()
                    if j["status"] in ("pending", "running")
                    and j.get("seq", 0) < mine
                )
                self.reply(200, out)
            return

        self.reply(404, {"error": "not found"})

    def do_POST(self):
        # /config is called by the local /setup page, so loopback is fine here.
        if self.path == "/config":
            if not self.origin_ok(allow_loopback=True):
                self.reply(403, {"error": "origin not allowed"})
                return
            self.handle_config()
            return

        # /download is extension-only - no web page may trigger a download.
        if not self.origin_ok():
            self.reply(403, {"error": "origin not allowed"})
            return

        if self.path == "/open-folder":
            try:
                if os.name == "nt":
                    subprocess.Popen(["explorer", str(INBOX)], close_fds=True)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", str(INBOX)], close_fds=True)
                else:
                    subprocess.Popen(["xdg-open", str(INBOX)], close_fds=True)
                self.reply(200, {"ok": True, "inbox": str(INBOX)})
            except Exception as e:
                self.reply(500, {"error": str(e)})
            return

        if self.path == "/history/clear":
            try:
                HISTORY_PATH.write_text("[]", encoding="utf-8")
            except Exception:
                pass
            self.reply(200, {"ok": True})
            return

        if self.path != "/download":
            self.reply(404, {"error": "not found"})
            return

        data = self.body_json()
        url = (data.get("url") or "").strip()
        fmt = data.get("format", "mp3")

        if not re.match(r"^https?://", url):
            self.reply(400, {"error": "url must start with http(s)://"})
            return
        if fmt not in ("mp3", "mp4", "thumb"):
            fmt = "mp3"
        quality = str(data.get("quality") or "")
        # Video asks for a height, audio asks for a bitrate - validate against
        # the right list so "1080" cannot end up as an MP3 bitrate.
        # Thumbnail has no quality at all.
        if fmt == "mp4":
            if quality not in QUALITY_HEIGHTS:
                quality = "1080"
        elif fmt == "thumb":
            quality = ""
        else:
            if quality not in AUDIO_KBPS:
                quality = "320"
        # VidFetch 1.2.0 options
        playlist = bool(data.get("playlist"))
        audio_format = str(data.get("audio_format") or "mp3").lower()
        if audio_format not in AUDIO_FORMATS:
            audio_format = "mp3"
        # Audio downloads are always "mp3" format in the old sense; the real
        # container lives in audio_format. Keep fmt="mp3" for audio jobs.
        thumbnail = bool(data.get("thumbnail"))
        subtitles = bool(data.get("subtitles"))

        with JOBS_LOCK:
            # same video + same format + same quality already queued? reuse it
            # instead of starting a second download that fights over the files.
            for existing in JOBS.values():
                if (existing["url"] == url and existing["format"] == fmt
                        and existing.get("quality") == quality
                        and existing.get("playlist") == playlist
                        and existing.get("audio_format", "mp3") == audio_format
                        and existing["status"] in ("pending", "running")):
                    self.reply(200, {"id": existing["id"],
                                     "status": existing["status"],
                                     "duplicate": True})
                    return
            job_id = str(uuid.uuid4())
            _seq["next"] += 1
            JOBS[job_id] = {
                "id": job_id, "url": url, "format": fmt, "quality": quality,
                "playlist": playlist, "audio_format": audio_format,
                "thumbnail": thumbnail, "subtitles": subtitles,
                "status": "pending", "file": "", "name": "",
                "error": "", "started": time.time(), "ended": 0,
                "percent": 0.0, "speed": "", "eta": "", "stage": "",
                "size": "", "bytes": 0, "files": 0,
                "seq": _seq["next"],
            }
        threading.Thread(target=run_job,
                         args=(job_id, url, fmt, quality, playlist, audio_format, thumbnail, subtitles),
                         daemon=True).start()
        prune_jobs()
        self.reply(202, {"id": job_id, "status": "pending"})


class QuietServer(ThreadingHTTPServer):
    """Browsers drop keep-alive sockets constantly; that is not an error and
    must not print a traceback or look like a crash."""

    daemon_threads = True
    # Must stay False. On Windows SO_REUSEADDR lets a second process bind the
    # SAME port, which silently gives you two helpers fighting over requests.
    allow_reuse_address = False

    def server_bind(self):
        # allow_reuse_address=False is not enough on Windows. Without
        # SO_EXCLUSIVEADDRUSE a second process can still bind 8766 and the OS
        # splits incoming requests between the two. That is how two yt-dlp
        # downloads ended up writing the same output file and deadlocking at
        # 0% - each helper had its own RUN_LOCK and its own JOBS dict, so the
        # "one download at a time" guarantee did not hold across processes.
        if os.name == "nt":
            try:
                self.socket.setsockopt(
                    socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
                )
            except (AttributeError, OSError):
                pass
        super().server_bind()

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def probe_existing(port):
    """Is another helper already answering on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1.5) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def main():
    refresh_windows_path()
    global INBOX, PORT, OPEN_FOLDER

    ap = argparse.ArgumentParser(description="Local helper for VidFetch")
    ap.add_argument("--port", type=int, default=int(os.environ.get("VIDFETCH_PORT", os.environ.get("YTG_PORT", 8766))))
    ap.add_argument("--inbox", default=None,
                    help="override the save folder (otherwise config.json is used)")
    ap.add_argument("--no-open-folder", action="store_true",
                    help="do not pop the folder open after the first save")
    ap.add_argument("--no-browser", action="store_true",
                    help="do not open the folder-picker page on first run")
    ap.add_argument("--setup", action="store_true",
                    help="open the folder-picker page even if a folder is configured")
    args = ap.parse_args()

    PORT = args.port
    OPEN_FOLDER = not args.no_open_folder

    cfg = load_config()
    first_run = not CONFIG_PATH.exists()

    if args.inbox:
        INBOX = Path(os.path.expandvars(args.inbox))
    elif cfg.get("inbox"):
        INBOX = Path(cfg["inbox"])
    else:
        INBOX = default_inbox()
    INBOX.mkdir(parents=True, exist_ok=True)

    try:
        subprocess.run([PYEXE, "-m", "yt_dlp", "--version"],
                       stdin=subprocess.DEVNULL, capture_output=True,
                       check=True, timeout=30, creationflags=NO_WINDOW)
    except subprocess.TimeoutExpired:
        sys.exit("yt-dlp did not answer within 30s. Try: python -m yt_dlp --version")
    except Exception:
        sys.exit("yt-dlp is not installed for this Python. Run: python -m pip install -U yt-dlp")

    # Refuse to start twice. A silent second instance is worse than an error.
    existing = probe_existing(PORT)
    if existing:
        print("")
        print(f"  A helper is ALREADY running on port {PORT}.", flush=True)
        print(f"  version {existing.get('version')}  ->  {existing.get('inbox')}", flush=True)
        print("")
        print("  Nothing to do - just use the browser buttons.", flush=True)
        print(f"  To change the folder: http://127.0.0.1:{PORT}/setup", flush=True)
        print("")
        sys.exit(0)

    try:
        srv = QuietServer(("127.0.0.1", PORT), Handler)
    except OSError as e:
        print("")
        print(f"  Cannot listen on port {PORT}: {e}", flush=True)
        print("  Something else is using it. Try a different port:", flush=True)
        print(f"    python helper.py --port {PORT + 1}", flush=True)
        print("")
        sys.exit(1)
    print("=" * 62)
    print(f"  VidFetch helper v{VERSION}")
    print(f"  listening   http://127.0.0.1:{PORT}")
    print(f"  saving to   {INBOX}")
    print(f"  change it   http://127.0.0.1:{PORT}/setup")
    print("  every finished download prints a big SAVED block below")
    print("  running in the background - no window needed" if BACKGROUND else "  keep this window open - Ctrl+C to stop")
    print("=" * 62)

    if (first_run or args.setup) and not args.no_browser:
        def _open_picker():
            time.sleep(1.2)
            try:
                webbrowser.open(f"http://127.0.0.1:{PORT}/setup")
                print("  (opened the folder picker in your browser)", flush=True)
            except Exception:
                print(f"  open http://127.0.0.1:{PORT}/setup to choose a folder", flush=True)
        threading.Thread(target=_open_picker, daemon=True).start()

    threading.Thread(target=_update_loop, daemon=True).start()

    # Keep serving even if something unexpected escapes: a helper that quietly
    # dies is what would otherwise force a re-setup.
    while True:
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped.")
            break
        except Exception as e:
            log(f"server error, continuing: {e}")
            time.sleep(1)
    srv.server_close()


if __name__ == "__main__":
    main()
