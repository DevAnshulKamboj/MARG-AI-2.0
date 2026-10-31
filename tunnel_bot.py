"""
tunnel_bot.py - keeps a Cloudflare quick tunnel alive and auto-updates your project.

What it does, in a loop:
  1. Starts `cloudflared tunnel --url http://localhost:PORT`
  2. Captures the generated https://xxxx.trycloudflare.com URL
  3. Replaces the old URL in your project files
  4. git add / commit / push
  5. Watches the tunnel; if it exits or stops responding, goes back to step 1

Requirements: Python 3.8+, cloudflared installed and on PATH, git configured
with push access (SSH key or credential manager) for your repo.

Run:  python tunnel_bot.py
Stop: Ctrl+C
"""

import queue
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# ----------------------------- CONFIG ---------------------------------------
PROJECT_DIR = Path(r"D:\PROJECT MARG-AI\Development\VERSION CONTROL\Version 5\Version 5")   # folder that is a git repo
LOCAL_PORT = 8000                                # port your backend listens on
FILE_EXTENSIONS = {".html", ".js", ".css", ".json", ".env", ".md"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv"}
HEALTH_PATH = "/"            # any HTTP response (even 404) counts as "alive"
CHECK_EVERY_SEC = 30
FAILS_BEFORE_RESTART = 3
URL_WAIT_SEC = 60
MIN_RESTART_DELAY_SEC = 10   # avoids hammering Cloudflare / GitHub
# -----------------------------------------------------------------------------

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def log(msg):
    print(time.strftime("[%H:%M:%S]"), msg, flush=True)


def start_tunnel():
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{LOCAL_PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines = queue.Queue()

    def reader():
        for line in proc.stdout:        # keeps draining so the pipe never fills
            lines.put(line)

    threading.Thread(target=reader, daemon=True).start()
    return proc, lines


def wait_for_url(proc, lines):
    deadline = time.time() + URL_WAIT_SEC
    while time.time() < deadline and proc.poll() is None:
        try:
            line = lines.get(timeout=1)
        except queue.Empty:
            continue
        match = URL_RE.search(line)
        if match:
            return match.group(0)
    return None


def update_files(new_url):
    changed = []
    for path in PROJECT_DIR.rglob("*"):
        if not path.is_file() or path.suffix not in FILE_EXTENSIONS:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new_text = URL_RE.sub(new_url, text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(path)
    return changed


def git(*args):
    return subprocess.run(
        ["git", "-C", str(PROJECT_DIR), *args],
        capture_output=True, text=True,
    )


def commit_and_push(new_url):
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode == 0:
        log("No file changes to commit.")
        return
    git("commit", "-m", f"Update tunnel URL to {new_url}")
    result = git("push")
    if result.returncode == 0:
        log("Pushed to GitHub.")
    else:
        log(f"Push failed: {result.stderr.strip()}")


def is_alive(url):
    try:
        urllib.request.urlopen(url + HEALTH_PATH, timeout=10)
        return True
    except urllib.error.HTTPError:
        return True          # server answered, tunnel is up
    except Exception:
        return False


def monitor(proc, url):
    fails = 0
    time.sleep(10)           # DNS for a new tunnel takes a few seconds
    while proc.poll() is None:
        if is_alive(url):
            fails = 0
        else:
            fails += 1
            log(f"Health check failed ({fails}/{FAILS_BEFORE_RESTART})")
            if fails >= FAILS_BEFORE_RESTART:
                return
        time.sleep(CHECK_EVERY_SEC)
    log("cloudflared exited.")


def main():
    while True:
        started = time.time()
        log("Starting tunnel...")
        proc, lines = start_tunnel()
        try:
            url = wait_for_url(proc, lines)
            if url:
                log(f"New URL: {url}")
                changed = update_files(url)
                log(f"Updated {len(changed)} file(s).")
                commit_and_push(url)
                monitor(proc, url)
            else:
                log("Could not get a tunnel URL.")
        except KeyboardInterrupt:
            proc.terminate()
            raise
        finally:
            if proc.poll() is None:
                proc.terminate()
        wait = max(0, MIN_RESTART_DELAY_SEC - (time.time() - started))
        log(f"Restarting in {wait:.0f}s...")
        time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")