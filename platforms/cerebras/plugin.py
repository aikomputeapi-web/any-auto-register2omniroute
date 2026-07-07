"""Cerebras Platform plugin"""
from typing import Optional
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class CerebrasPlatform(BasePlatform):
    name = "cerebras"
    display_name = "Cerebras"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]

    def __init__(self, config: Optional[RegisterConfig] = None, mailbox: Optional[BaseMailbox] = None):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        from platforms.cerebras.core import CerebrasRegister

        log_fn = getattr(self, "_log_fn", print)
        proxy = self.config.proxy
        requested_headless = (self.config.executor_type or "headless") != "headed"

        captcha_solver = self._make_captcha()
        reg = CerebrasRegister(proxy=proxy, headless=requested_headless, captcha_solver=captcha_solver)
        reg.log = lambda msg: log_fn(f"[Cerebras] {msg}")

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
                    keyword="",  # Accept any verification email from Cerebras/Clerk
                    timeout=otp_timeout,
                    before_ids=_before,
                    code_pattern=r"https?://[^\s\"\'><]*(?:clerk|cerebras)[^\s\"\'><]*(?:magic-link|token|accept|verify|ticket)[^\s\"\'><]*",
                )
                if code:
                    if code.startswith("http"):
                        log_fn(f"Verification magic link received: {code[:30]}...")
                    else:
                        log_fn(f"Verification code: {code}")
                return code
        else:
            otp_cb = None

        ok, info = reg.register(
            email=email,
            otp_callback=otp_cb,
        )

        if not ok:
            raise RuntimeError(f"Cerebras registration failed: {info.get('error')}")

        return Account(
            platform="cerebras",
            email=info["email"],
            password=info.get("password", ""),
            status=AccountStatus.REGISTERED,
            token=info.get("api_key", ""),
            extra={
                "api_key": info.get("api_key", ""),
            },
        )

    def check_valid(self, account: Account) -> bool:
        """Check if the account has a valid API key"""
        return bool(account.extra.get("api_key") or account.token)
