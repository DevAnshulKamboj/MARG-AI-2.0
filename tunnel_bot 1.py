        log("No staged changes to commit.")
        return True

    commit = git("commit", "-m", f"Update tunnel URL to {new_url}")
    if commit.returncode:
        log(f"Git commit failed: {commit.stderr.strip()}")
        return False

    push = git("push")
    if push.returncode == 0:
        log("Pushed tunnel URL update to GitHub.")
        return True

    log("Push rejected. Fetching remote changes and attempting rebase...")
    fetch = git("fetch")
    if fetch.returncode:
        log(f"Git fetch failed: {fetch.stderr.strip()}")
        return False

    branch = git("branch", "--show-current").stdout.strip()
    if not branch:
        log("Cannot determine current Git branch.")
        return False

    rebase = git("rebase", f"origin/{branch}")
    if rebase.returncode:
        log("Git rebase conflict detected.")
        log((rebase.stderr or rebase.stdout).strip())
        log("Aborting rebase to leave the repository in a safe state.")
        git("rebase", "--abort")
        log("Resolve the conflict manually, then restart the bot.")
        return False

    push = git("push")
    if push.returncode:
        log(f"Push still failed: {push.stderr.strip()}")
        return False
    log("Rebased and pushed tunnel URL update to GitHub.")
    return True


def is_alive(url):
    try:
        urllib.request.urlopen(url + HEALTH_PATH, timeout=10)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def monitor(proc, url):
    failures = 0
    time.sleep(10)
    while proc.poll() is None:
        if is_alive(url):
            failures = 0
        else:
            failures += 1
            log(f"Health check failed ({failures}/{FAILS_BEFORE_RESTART})")
            if failures >= FAILS_BEFORE_RESTART:
                log("Tunnel is not responding; restarting.")
                return
        time.sleep(CHECK_EVERY_SEC)
    log("cloudflared exited.")


def main():
    if not check_repository():
        return

    while True:
        started = time.time()
        proc = None
        try:
            log(f"Using backend: http://127.0.0.1:{LOCAL_PORT}")
            if not sync_before_editing():
                return

            log("Starting Cloudflare Quick Tunnel...")
            proc, lines = start_tunnel()
            url = wait_for_url(proc, lines)
            if not url:
                log("Could not obtain a Cloudflare tunnel URL.")
            else:
                log(f"New URL: {url}")
                changed = update_files(url)
                log(f"Updated {len(changed)} file(s).")
                if not commit_and_push(changed, url):
                    log("Stopping so Git can be reviewed safely.")
                    return
                monitor(proc, url)

        except KeyboardInterrupt:
            log("Stopping tunnel bot...")
            raise
        except Exception as exc:
            log(f"Unexpected error: {exc}")
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()

        wait = max(0, MIN_RESTART_DELAY_SEC - (time.time() - started))
        log(f"Restarting in {wait:.0f}s...")
        time.sleep(wait)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")
