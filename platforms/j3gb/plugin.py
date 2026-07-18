"""J3GB (VIP) Platform plugin"""

from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class J3gbPlatform(BasePlatform):
    name = "j3gb"
    display_name = "J3GB VIP"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]

    def __init__(
        self,
        config: Optional[RegisterConfig] = None,
        mailbox: Optional[BaseMailbox] = None,
    ):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        from platforms.j3gb.core import J3gbRegister, GmailDotTrickMailbox

        log_fn = getattr(self, "_log_fn", print)
        proxy = self.config.proxy
        requested_headless = (self.config.executor_type or "headless") != "headed"

        captcha_solver = self._make_captcha()
        reg = J3gbRegister(proxy=proxy, headless=requested_headless, captcha_solver=captcha_solver)
        reg.log = lambda msg: log_fn(f"[J3GB] {msg}")

        otp_timeout = self.get_mailbox_otp_timeout(default=180)

        # Determine if we should use the gmail dot trick
        extra = getattr(self.config, "extra", {}) or {}
        gmail_base_email = extra.get("j3gb_gmail_base_email", "") or extra.get("gmail_base_email", "")
        gmail_app_password = extra.get("j3gb_gmail_app_password", "") or extra.get("gmail_app_password", "")

        # Fall back to config_store / environment variables
        if not gmail_base_email or not gmail_app_password:
            try:
                from core.config_store import config_store
                if not gmail_base_email:
                    gmail_base_email = config_store.get("j3gb_gmail_base_email", "") or config_store.get("gmail_base_email", "")
                if not gmail_app_password:
                    gmail_app_password = config_store.get("j3gb_gmail_app_password", "") or config_store.get("gmail_app_password", "")
            except Exception:
                pass

        # If a gmail base email is configured, use the dot trick mailbox
        if gmail_base_email and gmail_app_password and not self.mailbox:
            log_fn(f"Using Gmail dot trick with base email: {gmail_base_email}")
            dot_trick_mb = GmailDotTrickMailbox(
                base_email=gmail_base_email,
                app_password=gmail_app_password,
                proxy=proxy,
            )
            dot_trick_mb._log_fn = log_fn
            dot_trick_mb._task_control = getattr(self, "_task_control", None)
            dot_trick_mb._task_attempt_token = getattr(self, "_task_attempt_token", None)

            mail_acct = dot_trick_mb.get_email()
            if not mail_acct:
                raise RuntimeError("No available email account found")
            email = email or mail_acct.email
            log_fn(f"Mail (dot trick): {mail_acct.email}")
            _before = dot_trick_mb.get_current_ids(mail_acct)

            def otp_cb():
                log_fn(f"Waiting for verification code (timeout: {otp_timeout}s)...")
                code = dot_trick_mb.wait_for_code(
                    mail_acct,
                    keyword="",
                    timeout=otp_timeout,
                    before_ids=_before,
                    code_pattern=r"(?is)(?:verification\s+code|code|验证码|認証コード)[^0-9]{0,30}(\d{6})",
                )
                if code:
                    log_fn(f"Verification code: {code}")
                return code

        elif self.mailbox:
            mailbox = self.mailbox
            mail_acct = mailbox.get_email()
            if not mail_acct:
                raise RuntimeError("No available email account found")
            email = email or mail_acct.email
            log_fn(f"Mail: {mail_acct.email}")
            _before = mailbox.get_current_ids(mail_acct)

            def otp_cb():
                log_fn(f"Waiting for verification code (timeout: {otp_timeout}s)...")
                code = mailbox.wait_for_code(
                    mail_acct,
                    keyword="",
                    timeout=otp_timeout,
                    before_ids=_before,
                    code_pattern=r"(?is)(?:verification\s+code|code|验证码|認証コード)[^0-9]{0,30}(\d{6})",
                )
                if code:
                    log_fn(f"Verification code: {code}")
                return code
        else:
            otp_cb = None

        ok, info = reg.register(
            email=email,
            password=password,
            otp_callback=otp_cb,
        )

        if not ok:
            raise RuntimeError(f"J3GB registration failed: {info.get('error')}")

        return Account(
            platform="j3gb",
            email=info["email"],
            password=info["password"],
            status=AccountStatus.REGISTERED,
            token=info.get("api_key", ""),
            extra={
                "api_key": info.get("api_key", ""),
                "username": info.get("username", ""),
                "federation": "dc.hhhl.cc",
            },
        )

    def check_valid(self, account: Account) -> bool:
        """Check if the account has a valid API key"""
        return bool(account.extra.get("api_key") or account.token)
