"""DevTools Inspector Process management - Automatically pull up when backend starts"""
import subprocess
import sys
import os
import time
import threading
import requests

_proc: subprocess.Popen = None
_log_file = None
_lock = threading.Lock()


def _devtools_enabled() -> bool:
    return os.getenv("APP_ENABLE_DEVTOOLS", "1").lower() not in {"0", "false", "no"}


def _devtools_port() -> int:
    return int(os.getenv("DEVTOOLS_PORT", "3005"))


def _devtools_url() -> str:
    return f"http://127.0.0.1:{_devtools_port()}"


def is_running() -> bool:
    try:
        r = requests.get(f"{_devtools_url()}/status", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _check_node_installed() -> bool:
    try:
        # Check if node is available in system PATH
        res = subprocess.run(["node", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
        return res.returncode == 0
    except Exception:
        return False


def start():
    global _proc, _log_file
    with _lock:
        if not _devtools_enabled():
            print("[DevTools] Disabled, skips autostart")
            return
        if is_running():
            print("[DevTools] Already running")
            return

        devtools_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "devtools_inspector"
        )
        if not os.path.isdir(devtools_dir):
            print(f"[DevTools] Directory not found at: {devtools_dir}")
            return

        if not _check_node_installed():
            print("[DevTools] Node.js not detected in PATH. Skipping devtools-bridge autostart.")
            return

        # Check if node_modules needs installation
        node_modules_dir = os.path.join(devtools_dir, "node_modules")
        if not os.path.isdir(node_modules_dir):
            print("[DevTools] node_modules not found, running npm install...")
            try:
                # Run npm install synchronously to ensure dependencies are resolved before starting the server
                subprocess.run(["npm", "install"], cwd=devtools_dir, check=True, shell=True)
                print("[DevTools] npm install completed successfully.")
            except Exception as e:
                print(f"[DevTools] npm install failed: {e}")
                return

        log_path = os.path.join(devtools_dir, "devtools-bridge.log")
        _log_file = open(log_path, "a", encoding="utf-8")
        
        env = os.environ.copy()
        env["API_PORT"] = str(_devtools_port())
        
        # Start node server
        # Running index.js directly, or via npm start. Executing index.js directly allows cleaner process tree tracking.
        entry_point = os.path.join(devtools_dir, "src", "index.js")
        _proc = subprocess.Popen(
            [
                "node",
                entry_point
            ],
            cwd=devtools_dir,
            stdout=_log_file,
            stderr=subprocess.STDOUT,
            env=env,
            shell=True
        )

        # Wait for the service to be ready (up to 15s)
        for _ in range(15):
            time.sleep(1)
            if is_running():
                print(f"[DevTools] Started PID={_proc.pid} on port {_devtools_port()}")
                return
            if _proc.poll() is not None:
                print(f"[DevTools] Startup failed, exit code={_proc.returncode}, log: {log_path}")
                _proc = None
                if _log_file:
                    _log_file.close()
                    _log_file = None
                return
        print(f"[DevTools] Startup timeout, log: {log_path}")


def stop():
    global _proc, _log_file
    with _lock:
        if _proc and _proc.poll() is None:
            # On Windows, terminating shell=True processes sometimes leaves children orphans.
            # So we try taskkill first if on Windows, otherwise standard terminate.
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/F", "/T", "/PID", str(_proc.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    _proc.terminate()
            else:
                _proc.terminate()
            _proc.wait(timeout=5)
            print("[DevTools] Stopped")
        _proc = None
        if _log_file:
            _log_file.close()
            _log_file = None


def start_async():
    """Start in a background thread without blocking the main process"""
    t = threading.Thread(target=start, daemon=True)
    t.start()
