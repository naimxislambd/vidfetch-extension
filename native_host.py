"""VidFetch native-messaging host.

Chrome/Edge start this tiny program when the extension asks "is the helper
running?" and the answer is no. It launches the helper hidden and replies.
That is what makes setup a one-time job: if the helper ever stops (killed,
crashed, never started after a reboot) the next click on the VidFetch icon
brings it back.
"""
import json
import os
import struct
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8766


def read_message():
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    n = struct.unpack("<I", raw)[0]
    return json.loads(sys.stdin.buffer.read(n).decode("utf-8"))


def send(obj):
    data = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def alive():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def pythonw():
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        cand = exe[: -len("python.exe")] + "pythonw.exe"
        if os.path.exists(cand):
            return cand
    return exe


def start_helper():
    flags = 0
    if os.name == "nt":
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS
                 | subprocess.CREATE_NEW_PROCESS_GROUP)
    subprocess.Popen(
        [pythonw(), str(HERE / "helper.py")],
        cwd=str(HERE), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)


def main():
    read_message()  # the request itself carries nothing we need
    if alive():
        send({"ok": True, "started": False})
        return
    try:
        start_helper()
    except Exception as e:
        send({"ok": False, "error": str(e)})
        return
    for _ in range(24):
        time.sleep(0.5)
        if alive():
            send({"ok": True, "started": True})
            return
    send({"ok": False, "error": "helper did not start"})


if __name__ == "__main__":
    main()
