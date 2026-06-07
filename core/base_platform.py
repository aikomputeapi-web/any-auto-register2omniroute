"""Platform plug-in base class"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
import os
import time


class AccountStatus(str, Enum):
    REGISTERED   = "registered"
    TRIAL        = "trial"
    SUBSCRIBED   = "subscribed"
    EXPIRED      = "expired"
    INVALID      = "invalid"


@dataclass
class Account:
    platform: str
    email: str
    password: str
    user_id: str = ""
    region: str = ""
    token: str = ""
    status: AccountStatus = AccountStatus.REGISTERED
    trial_end_time: int = 0       # unix timestamp
    extra: dict = field(default_factory=dict)  # Platform custom fields
    created_at: int = field(default_factory=lambda: int(time.time()))


@dataclass
class RegisterConfig:
    """Register task configuration"""
    executor_type: str = "protocol"   # protocol | headless | headed
    captcha_solver: str = "yescaptcha"  # yescaptcha | 2captcha | manual
    proxy: Optional[str] = None
    extra: dict = field(default_factory=dict)


class BasePlatform(ABC):
    # Subclasses must be defined
    name: str = ""
    display_name: str = ""
    version: str = "1.0.0"
    # Executor types supported by subclass declarations, those not listed are automatically downgraded to protocol
    supported_executors: list = ["protocol", "headless", "headed"]

    def __init__(self, config: RegisterConfig = None):
        self.config = config or RegisterConfig()
        self._task_control = None
        requested_executor = str(self.config.executor_type or "").strip() or "protocol"
        if requested_executor not in self.supported_executors:
            fallback = (
                "protocol"
                if "protocol" in self.supported_executors
                else (self.supported_executors[0] if self.supported_executors else "protocol")
            )
            print(
                f"[{self.display_name or self.name}] actuator '{requested_executor}' not supported,"
                f"Automatically switch to '{fallback}' (support: {self.supported_executors})"
            )
            self.config.executor_type = fallback
        else:
            self.config.executor_type = requested_executor

    @abstractmethod
    def register(self, email: str, password: str = None) -> Account:
        """Execute the registration process and return Account"""
        ...

    @abstractmethod
    def check_valid(self, account: Account) -> bool:
        """Check if the account is valid"""
        ...

    def get_trial_url(self, account: Account) -> Optional[str]:
        """Generate trial activation link (optional implementation)"""
        return None

    def get_platform_actions(self) -> list:
        """
        Returns a list of additional operations supported by the platform, for each format:
        {"id": str, "label": str, "params": [{"key": str, "label": str, "type": str}]}
        """
        return []

    def execute_action(self, action_id: str, account: Account, params: dict) -> dict:
        """
        Perform platform-specific operations and return {"ok": bool, "data": any, "error": str}
        """
        raise NotImplementedError(f"platform {self.name} Operation not supported: {action_id}")

    def get_quota(self, account: Account) -> dict:
        """Query account quota (optional implementation)"""
        return {}

    def bind_task_control(self, task_control) -> None:
        """Bind collaborative task controller for mailbox to wait/Scene reuse such as manual skipping."""
        self._task_control = task_control
        mailbox = getattr(self, "mailbox", None)
        if mailbox is not None:
            mailbox._task_control = task_control

    def get_mailbox_otp_timeout(self, default: int = 120) -> int:
        """Unified analysis of mailboxes OTP Wait a few seconds to avoid scattering mana on the platform."""
        extra = getattr(self.config, "extra", {}) or {}
        candidates = (
            extra.get("mailbox_otp_timeout_seconds"),
            extra.get("email_otp_timeout_seconds"),
            extra.get("otp_timeout"),
            default,
        )
        for value in candidates:
            if value in (None, ""):
                continue
            try:
                resolved = int(value)
            except (TypeError, ValueError):
                continue
            if resolved > 0:
                return resolved
        return default

    def _make_executor(self):
        """according to config Create executor"""
        from .executors.protocol import ProtocolExecutor
        t = self.config.executor_type
        if t == "protocol":
            return ProtocolExecutor(proxy=self.config.proxy)
        elif t == "headless":
            from .executors.playwright import PlaywrightExecutor
            return PlaywrightExecutor(proxy=self.config.proxy, headless=True)
        elif t == "headed":
            from .executors.playwright import PlaywrightExecutor
            return PlaywrightExecutor(proxy=self.config.proxy, headless=False)
        raise ValueError(f"Unknown executor type: {t}")

    def _make_captcha(self, **kwargs):
        """according to config Create a captcha solver"""
        from .base_captcha import YesCaptcha, ManualCaptcha, LocalSolverCaptcha, CapSolver
        from core.config_store import config_store
        t = self.config.captcha_solver
        if t == "yescaptcha":
            key = (
                kwargs.get("key")
                or self.config.extra.get("yescaptcha_key")
                or config_store.get("yescaptcha_key", "")
            )
            return YesCaptcha(key)
        elif t == "capsolver":
            key = (
                kwargs.get("key")
                or self.config.extra.get("capsolver_key")
                or config_store.get("capsolver_key", "")
            )
            return CapSolver(key)
        elif t == "manual":
            return ManualCaptcha()
        elif t == "local_solver":
            url = (
                self.config.extra.get("solver_url")
                or os.getenv("LOCAL_SOLVER_URL")
                or f"http://127.0.0.1:{os.getenv('SOLVER_PORT', '8889')}"
            )
            return LocalSolverCaptcha(url)
        raise ValueError(f"Unknown captcha solver: {t}")
