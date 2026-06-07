"""Cloudflare Platform plugin"""
from typing import Optional
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class CloudflarePlatform(BasePlatform):
    name = "cloudflare"
    display_name = "Cloudflare"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]

    def __init__(self, config: Optional[RegisterConfig] = None, mailbox: Optional[BaseMailbox] = None):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        from platforms.cloudflare.core import CloudflareRegister

        log_fn = getattr(self, "_log_fn", print)
        proxy = self.config.proxy
        requested_headless = (self.config.executor_type or "headless") != "headed"

        reg = CloudflareRegister(proxy=proxy, headless=requested_headless)
        reg.log = lambda msg: log_fn(f"[Cloudflare] {msg}")

        otp_timeout = self.get_mailbox_otp_timeout()

        if self.mailbox:
            mailbox = self.mailbox
            mail_acct = mailbox.get_email()
            if not mail_acct:
                raise RuntimeError("No available email account found")
            email = email or mail_acct.email
            log_fn(f"Mail: {mail_acct.email}")
            _before = mailbox.get_current_ids(mail_acct)

            def otp_cb():
                log_fn("Wait for verification code...")
                code = mailbox.wait_for_code(
                    mail_acct,
                    keyword="",
                    timeout=otp_timeout,
                    before_ids=_before,
                    code_pattern=r"(?is)(?:verification\s+code|code|verify)[^0-9]{0,50}(\d{6})",
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
            raise RuntimeError(f"Cloudflare registration failed: {info.get('error')}")

        return Account(
            platform="cloudflare",
            email=info["email"],
            password=info["password"],
            status=AccountStatus.REGISTERED,
            token=info.get("api_token", ""),
            extra={
                "api_token": info.get("api_token", ""),
            },
        )

    def check_valid(self, account: Account) -> bool:
        """Check if the account has a valid API token"""
        return bool(account.extra.get("api_token") or account.token)
