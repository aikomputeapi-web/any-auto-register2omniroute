"""Railway.com Platform plugin"""

import os
from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class RailwayPlatform(BasePlatform):
    name = "railway"
    display_name = "Railway"
    version = "1.0.0"
    supported_executors = ["headless", "headed"]

    def __init__(
        self,
        config: Optional[RegisterConfig] = None,
        mailbox: Optional[BaseMailbox] = None,
    ):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def _save_to_text_file(self, account: Account):
        """Save account details to a text file"""
        try:
            # Create accounts directory if it doesn't exist
            accounts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "accounts")
            os.makedirs(accounts_dir, exist_ok=True)

            # Create railway-specific file
            file_path = os.path.join(accounts_dir, "railway_accounts.txt")

            # Format: email:password:token
            line = f"{account.email}:{account.password}:{account.token}\n"

            # Append to file
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line)

            print(f"[RAILWAY] Account saved to {file_path}")
        except Exception as e:
            print(f"[RAILWAY] Warning: Failed to save account to text file: {e}")

    def register(self, email: str, password: Optional[str] = None) -> Account:
        from platforms.railway.core import RailwayRegister

        log_fn = getattr(self, "_log_fn", print)
        proxy = self.config.proxy
        requested_headless = (self.config.executor_type or "headless") != "headed"

        captcha_solver = self._make_captcha()
        reg = RailwayRegister(proxy=proxy, headless=requested_headless, captcha_solver=captcha_solver)
        reg.log = lambda msg: log_fn(f"[RAILWAY] {msg}")

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

                log_fn("Polling for Railway account verification email...")

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

                                            # Try multiple extraction patterns for Railway OTP
                                            search_text = f"{subject} {content}"
                                            patterns = [
                                                r'(?i)verification[^0-9]{0,50}(\d{6})',  # 6-digit code
                                                r'(?i)code[^0-9]{0,50}(\d{6})',
                                                r'(?i)\b(\d{6})\b',
                                                r'(?i)confirm[^0-9]{0,50}(\d{6})',
                                                r'(?i)railway[^0-9]{0,50}(\d{6})',
                                            ]

                                            for pattern in patterns:
                                                match = re.search(pattern, search_text)
                                                if match:
                                                    code = match.group(1)
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
                                        code_pattern=r'\b(\d{6})\b',
                                    )
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
            raise RuntimeError(f"Railway registration failed: {info.get('error')}")

        account = Account(
            platform="railway",
            email=info["email"],
            password=info["password"],
            status=AccountStatus.REGISTERED,
            token=info.get("token", ""),
            extra={
                "token": info.get("token", ""),
            },
        )

        # Save to text file as requested
        self._save_to_text_file(account)

        return account

    def check_valid(self, account: Account) -> bool:
        """Check if the account has a valid token"""
        return bool(account.extra.get("token") or account.token)