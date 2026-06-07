import sys
import os
import time
import threading
import random
from typing import Optional
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register

_task_start_lines = {}
_lock = threading.Lock()

def _get_task_start_line(task_id: str, line_count: int) -> int:
    with _lock:
        if task_id not in _task_start_lines:
            _task_start_lines[task_id] = random.randint(1, line_count)
        return _task_start_lines[task_id]

@register
class USBankPlatform(BasePlatform):
    name = "usbank"
    display_name = "U.S. Bank"
    version = "1.0.0"
    supported_executors = ["headed"]

    def __init__(self, config: Optional[RegisterConfig] = None, mailbox: Optional[BaseMailbox] = None):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        extra = self.config.extra or {}
        phone = str(extra.get("phone", "6692506085"))
        from core.config_store import config_store
        dataset = str(extra.get("dataset") or config_store.get("pro_dataset_path", "pointclickcare data.txt"))
        
        # Count lines in dataset
        line_count = 1
        if os.path.exists(dataset):
            try:
                with open(dataset, "r", encoding="utf-8", errors="ignore") as f:
                    line_count = len([l for l in f if l.strip()])
            except Exception:
                pass
        if line_count < 1:
            line_count = 1
            
        task_id = extra.get("task_id", "default_task")
        task_index = int(extra.get("task_index", 0))
        
        # Determine randomized starting line or follow configured line
        if "line" in extra:
            try:
                start_line = int(extra["line"])
            except ValueError:
                start_line = 1
            target_line = ((start_line - 1 + task_index) % line_count) + 1
        else:
            start_line = _get_task_start_line(task_id, line_count)
            target_line = ((start_line - 1 + task_index) % line_count) + 1
            
        line_str = str(target_line)
        
        old_argv = sys.argv
        sys.argv = [
            "register_usbank.py",
            "--line", line_str,
            "--phone", phone,
            "--dataset", dataset
        ]
        if email:
            sys.argv.extend(["--email", email])
            
        log = getattr(self, "_log_fn", print)
        log(f"Starting U.S. Bank registration for line {line_str} (start line: {start_line}, task index: {task_index}) with phone {phone}...")
        
        try:
            from pro_account_register import register_usbank
            import importlib
            importlib.reload(register_usbank)
            
            register_usbank.main()
        except Exception as e:
            log(f"Error executing U.S. Bank script: {e}")
            raise e
        finally:
            sys.argv = old_argv
            
        return Account(
            platform="usbank",
            email=email or "",
            password=password or "",
            status=AccountStatus.REGISTERED,
            extra={}
        )

    def check_valid(self, account: Account) -> bool:
        return True
