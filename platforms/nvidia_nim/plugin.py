"""NVIDIA NIM Platform plugin"""

from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class NvidiaNimPlatform(BasePlatform):
    name = "nvidia_nim"
    display_name = "NVIDIA NIM"
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
        from platforms.nvidia_nim.core import NvidiaNimRegister

        log_fn = getattr(self, "_log_fn", print)
        proxy = self.config.proxy
        requested_headless = (self.config.executor_type or "headless") != "headed"

        captcha_solver = self._make_captcha()
        reg = NvidiaNimRegister(proxy=proxy, headless=requested_headless, captcha_solver=captcha_solver)
        reg.log = lambda msg: log_fn(f"[NVIDIA NIM] {msg}")

        otp_timeout = self.get_mailbox_otp_timeout() or 180

        if self.mailbox:
            mailbox = self.mailbox
            mail_acct = mailbox.get_email()
            if not mail_acct:
                raise RuntimeError("No available email account found")
            email = email or mail_acct.email
            log_fn(f"Mail: {mail_acct.email}")
            _before = mailbox.get_current_ids(mail_acct)

            def otp_cb():
                log_fn(f"Wait for verification code (timeout: {otp_timeout}s)...")
                import time
                import re
                start_time = time.time()
                
                log_fn("Polling for NVIDIA account verification email...")
                
                # Wait for the email to arrive
                deadline = time.time() + otp_timeout
                code = None
                
                while time.time() < deadline and not code:
                    try:
                        # Get new emails
                        current_ids = mailbox.get_current_ids(mail_acct)
                        new_ids = current_ids - _before
                        
                        if new_ids:
                            log_fn(f"Found {len(new_ids)} new email(s)")
                            
                            # For IMAP, we need to manually check the emails
                            # Try to use the mailbox's internal method to get email content
                            if hasattr(mailbox, '_list_messages'):
                                try:
                                    messages = mailbox._list_messages(mail_acct.email)
                                    for msg in messages:
                                        msg_id = str(msg.get('id', ''))
                                        if msg_id not in _before:
                                            subject = str(msg.get('subject', ''))
                                            content = str(msg.get('content', '') or msg.get('text', '') or msg.get('body', ''))
                                            log_fn(f"Email subject: {subject[:100]}")
                                            log_fn(f"Email content preview: {content[:200]}")
                                            
                                            # Try multiple extraction patterns (including hyphenated ones like XXX-XXX)
                                            search_text = f"{subject} {content}"
                                            patterns = [
                                                r'(?i)verification[^0-9]{0,50}(\d{3}-\d{3})',
                                                r'(?i)code[^0-9]{0,50}(\d{3}-\d{3})',
                                                r'(?i)\b(\d{3}-\d{3})\b',
                                                r'(?i)verification[^0-9]{0,50}(\d{6})',
                                                r'(?i)code[^0-9]{0,50}(\d{6})',
                                                r'(?i)\b(\d{6})\b',
                                            ]
                                            
                                            for pattern in patterns:
                                                match = re.search(pattern, search_text)
                                                if match:
                                                    code = match.group(1).replace("-", "")
                                                    log_fn(f"Extracted code {code} using pattern: {pattern}")
                                                    break
                                            
                                            if code:
                                                break
                                except Exception as e:
                                    log_fn(f"Error reading email content: {e}")
                            
                            # If we have new emails but couldn't extract manually, use wait_for_code
                            if not code:
                                try:
                                    code = mailbox.wait_for_code(
                                        mail_acct,
                                        keyword="",
                                        timeout=5,
                                        before_ids=_before,
                                        code_pattern=r'\b(\d{3}-\d{3})\b|\b(\d{6})\b',
                                    )
                                    if code:
                                        code = code.replace("-", "")
                                except:
                                    pass
                        
                        if not code:
                            time.sleep(3)
                            
                    except Exception as e:
                        log_fn(f"Error in polling loop: {e}")
                        time.sleep(3)
                
                elapsed = int(time.time() - start_time)
                if code:
                    log_fn(f"Verification code received after {elapsed}s: {code}")
                else:
                    log_fn(f"No verification code received after {elapsed}s")
                return code
        else:
            otp_cb = None

        ok, info = reg.register(
            email=email,
            password=password,
            otp_callback=otp_cb,
        )

        if not ok:
            raise RuntimeError(f"NVIDIA NIM registration failed: {info.get('error')}")

        return Account(
            platform="nvidia_nim",
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