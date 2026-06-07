"""
Cursor Account switching —— Write to local configuration file,Cursor IDE automatic recognition
support macOS / Windows / Linux
"""

import os
import json
import logging
import tempfile
import platform
import subprocess
import time
from typing import Tuple

logger = logging.getLogger(__name__)


def _get_cursor_config_dir() -> str:
    """get Cursor Configuration directory path"""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        home = os.path.expanduser("~")
        return os.path.join(home, "Library", "Application Support", "Cursor", "User")
    
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "Cursor", "User")
    
    else:  # Linux
        home = os.path.expanduser("~")
        config_home = os.environ.get("XDG_CONFIG_HOME", os.path.join(home, ".config"))
        return os.path.join(config_home, "Cursor", "User")


def _get_cursor_storage_path() -> str:
    """get Cursor storage.json path"""
    config_dir = _get_cursor_config_dir()
    return os.path.join(config_dir, "globalStorage", "storage.json")


def _atomic_write(filepath: str, content: str):
    """Atomic write: write to temporary file first, then rename"""
    dir_path = os.path.dirname(filepath)
    os.makedirs(dir_path, exist_ok=True)
    
    fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp_path, filepath)
    except Exception:
        try:
            os.close(fd)
        except:
            pass
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def switch_cursor_account(token: str) -> Tuple[bool, str]:
    """
    switch Cursor Account number (write storage.json, need to restart Cursor)
    
    Args:
        token: WorkosCursorSessionToken
    
    Returns:
        (success, message)
    """
    try:
        storage_path = _get_cursor_storage_path()
        
        # Read existing configuration
        storage_data = {}
        if os.path.exists(storage_path):
            try:
                with open(storage_path, "r", encoding="utf-8") as f:
                    storage_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read existing configuration, new configuration will be created: {e}")
        
        # renew token
        storage_data["workos.sessionToken"] = token
        
        # Atomic writes
        content = json.dumps(storage_data, indent=2, ensure_ascii=False)
        _atomic_write(storage_path, content)
        
        return True, "Switching successful, please restart Cursor IDE Make the new account effective"
    
    except Exception as e:
        logger.error(f"Cursor Account switching failed: {e}")
        return False, f"Switch failed: {str(e)}"


def restart_cursor_ide() -> Tuple[bool, str]:
    """Shut down and restart Cursor IDE"""
    system = platform.system()
    
    try:
        if system == "Darwin":  # macOS
            # closure Cursor
            subprocess.run(
                ["osascript", "-e", 'quit app "Cursor"'],
                capture_output=True,
                timeout=5
            )
            time.sleep(2.0)
            
            # start up Cursor
            cursor_app = "/Applications/Cursor.app"
            if os.path.exists(cursor_app):
                subprocess.Popen(["open", "-a", "Cursor"])
                return True, "Cursor IDE Restarted"
            return True, "Closed Cursor IDE(Application path not found, please start manually)"
        
        elif system == "Windows":
            # closure Cursor
            subprocess.run(
                ["taskkill", "/IM", "Cursor.exe", "/F"],
                capture_output=True,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
                timeout=5
            )
            time.sleep(1.5)
            
            # start up Cursor
            localappdata = os.environ.get("LOCALAPPDATA", "")
            cursor_exe = os.path.join(localappdata, "Programs", "Cursor", "Cursor.exe")
            if os.path.exists(cursor_exe):
                subprocess.Popen([cursor_exe])
                return True, "Cursor IDE Restarted"
            return True, "Closed Cursor IDE(Application path not found, please start manually)"
        
        else:  # Linux
            # closure Cursor
            subprocess.run(["pkill", "-f", "cursor"], capture_output=True, timeout=5)
            time.sleep(1.5)
            
            # start up Cursor
            for path in ["/usr/bin/cursor", os.path.expanduser("~/.local/bin/cursor")]:
                if os.path.exists(path):
                    subprocess.Popen([path])
                    return True, "Cursor IDE Restarted"
            
            try:
                subprocess.Popen(["cursor"])
                return True, "Cursor IDE Restarted"
            except FileNotFoundError:
                return True, "Closed Cursor IDE(Application path not found, please start manually)"
    
    except Exception as e:
        logger.error(f"Cursor IDE Restart failed: {e}")
        return False, f"Restart failed: {str(e)}"


def read_current_cursor_account() -> dict | None:
    """Read current Cursor IDE Account in use token"""
    storage_path = _get_cursor_storage_path()
    
    if not os.path.exists(storage_path):
        return None
    
    try:
        with open(storage_path, "r", encoding="utf-8") as f:
            storage_data = json.load(f)
        
        token = storage_data.get("workos.sessionToken")
        if token:
            return {"token": token}
        return None
    
    except Exception as e:
        logger.error(f"read Cursor Configuration failed: {e}")
        return None


def get_cursor_user_info(token: str) -> dict | None:
    """pass token Get user information"""
    from curl_cffi import requests as curl_req
    
    try:
        r = curl_req.get(
            "https://cursor.com/api/auth/me",
            headers={
                "Cookie": f"WorkosCursorSessionToken={token}",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/145.0.0.0 Safari/537.36"
            },
            impersonate="chrome124",
            timeout=15,
        )
        
        if r.status_code == 200:
            return r.json()
        return None
    
    except Exception as e:
        logger.error(f"get Cursor User information failed: {e}")
        return None
