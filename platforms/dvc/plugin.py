from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class DVCPlatform(BasePlatform):
    name = "dvc"
    display_name = "Diablo Valley College"
    version = "1.0.0"
    supported_executors = ["headed", "headless"]

    def __init__(self, config: Optional[RegisterConfig] = None, mailbox: Optional[BaseMailbox] = None):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: str = None) -> Account:
      from pro_account_register import register_dvc
  
      import importlib
      importlib.reload(register_dvc)
  
      # Route print() calls through the task runner's log function so the UI
      # shows live progress instead of waiting until the script finishes.
      log_fn = getattr(self, "_log_fn", print)
      register_dvc._log_fn = log_fn
  
      old_argv = sys.argv
      try:
        argv = ["register_dvc.py"]
        extra = self.config.extra or {}
        for key in ("dataset", "line", "seed", "email_domain", "email", "phone", "bridge"):
          if key in extra and extra[key] not in (None, ""):
            argv.extend([f"--{key.replace('_', '-')}", str(extra[key])])
        smspool_keys = [
          "smspool_api_key", "smspool_country", "smspool_service",
          "smspool_pricing_option", "smspool_max_price",
          "smspool_max_attempts", "smspool_poll_interval", "smspool_poll_timeout",
        ]
        for key in smspool_keys:
          if key in extra and extra[key] not in (None, ""):
            argv.extend([f"--{key.replace('_', '-')}", str(extra[key])])
        if "capsolver_key" in extra and extra["capsolver_key"] not in (None, ""):
          argv.extend(["--capsolver-key", str(extra["capsolver_key"])])
        sys.argv = argv
        ret = register_dvc.main()
      finally:
        sys.argv = old_argv
  
      # register_dvc.main() generates an email internally; prefer that value
      # over the caller-supplied parameter so the DB record always has a real address.
      resolved_email = getattr(register_dvc, "_generated_email", None) or email or ""
  
      return Account(
        platform=self.name,
        email=resolved_email,
        password=password or "",
        status=AccountStatus.REGISTERED if ret == 0 else AccountStatus.INVALID,
        extra={},
      )

    def check_valid(self, account: Account) -> bool:
        return True
