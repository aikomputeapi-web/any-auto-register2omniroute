"""OpenRouter Platform plugin"""
from typing import Optional
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class OpenRouterPlatform(BasePlatform):
    name = "openrouter"
    display_name = "OpenRouter"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]

    def __init__(self, config: Optional[RegisterConfig] = None, mailbox: Optional[BaseMailbox] = None):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        from platforms.openrouter.core import OpenRouterRegister

        log_fn = getattr(self, "_log_fn", print)
        proxy = self.config.proxy
        requested_headless = (self.config.executor_type or "headless") != "headed"

        # Warn if using CatchMail
        if email and "@catchmail.io" in email.lower():
            log_fn("⚠️  WARNING: OpenRouter may not send emails to @catchmail.io addresses")
            log_fn("⚠️  Consider using LuckMail or IMAP Catchall instead")
            log_fn("⚠️  See platforms/openrouter/EMAIL_COMPATIBILITY.md for details")

        captcha_solver = self._make_captcha()
        reg = OpenRouterRegister(proxy=proxy, headless=requested_headless, captcha_solver=captcha_solver)
        reg.log = lambda msg: log_fn(f"[OpenRouter] {msg}")

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
                log_fn("Wait for verification code or link...")
                code = mailbox.wait_for_code(
                    mail_acct,
                    keyword="",  # Don't filter by keyword - accept any email
                    timeout=otp_timeout,
                    before_ids=_before,
                    code_pattern=r"(https?://clerk\.[^\s<>\"']+/v1/verify[^\s<>\"']+|\b\d{6}\b)",
                )
                if code:
                    if code.startswith("http"):
                        log_fn(f"Verification magic link: {code[:50]}...")
                    else:
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
            raise RuntimeError(f"OpenRouter registration failed: {info.get('error')}")

        return Account(
            platform="openrouter",
            email=info["email"],
            password=info["password"],
            status=AccountStatus.REGISTERED,
            token=info.get("api_key", ""),
            extra={
                "api_key": info.get("api_key", ""),
            },
        )

    def check_valid(self, account: Account) -> bool:
        """Check if the account has a valid API key"""
        return bool(account.extra.get("api_key") or account.token)
