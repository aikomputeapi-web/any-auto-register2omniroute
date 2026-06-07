"""Turnstile Solver Process management - Automatically pull up when backend starts"""
import subprocess
import sys
import os
import time
import threading
import requests

_proc: subprocess.Popen = None
_log_file = None
_lock = threading.Lock()


def _solver_enabled() -> bool:
    return os.getenv("APP_ENABLE_SOLVER", "1").lower() not in {"0", "false", "no"}


def _solver_port() -> int:
    return int(os.getenv("SOLVER_PORT", "8889"))


def _solver_url() -> str:
    return (os.getenv("LOCAL_SOLVER_URL") or f"http://127.0.0.1:{_solver_port()}").rstrip("/")


def _solver_bind_host() -> str:
    return os.getenv("SOLVER_BIND_HOST", "0.0.0.0")


def _solver_browser_type() -> str:
    return os.getenv("SOLVER_BROWSER_TYPE", "camoufox")


def is_running() -> bool:
    try:
        r = requests.get(f"{_solver_url()}/", timeout=2)
        return r.status_code < 500
    except Exception:
        return False


def start():
    global _proc, _log_file
    with _lock:
        if not _solver_enabled():
            print("[Solver] Disabled, skips autostart")
            return
        if is_running():
            print("[Solver] Already running")
            return
        solver_script = os.path.join(
            os.path.dirname(__file__), "turnstile_solver", "start.py"
        )
        log_path = os.path.join(
            os.path.dirname(__file__), "turnstile_solver", "solver.log"
        )
        _log_file = open(log_path, "a", encoding="utf-8")
        _proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                solver_script,
                "--browser_type",
                _solver_browser_type(),
                "--host",
                _solver_bind_host(),
                "--port",
                str(_solver_port()),
            ],
            stdout=_log_file,
            stderr=subprocess.STDOUT,
        )
        # Wait for the service to be ready (up to30s)
        for _ in range(30):
            time.sleep(1)
            if is_running():
                print(f"[Solver] Started PID={_proc.pid}")
                return
            if _proc.poll() is not None:
                print(f"[Solver] Startup failed, exit code={_proc.returncode},log: {log_path}")
                _proc = None
                if _log_file:
                    _log_file.close()
                    _log_file = None
                return
        print(f"[Solver] startup timeout, log: {log_path}")


def stop():
    global _proc, _log_file
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
            _proc.wait(timeout=5)
            print("[Solver] Stopped")
        _proc = None
        if _log_file:
            _log_file.close()
            _log_file = None


def start_async():
    """Start in a background thread without blocking the main process"""
    t = threading.Thread(target=start, daemon=True)
    t.start()
