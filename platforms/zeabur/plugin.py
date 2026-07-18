"""Zeabur.com Platform plugin"""

import os
from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class ZeaburPlatform(BasePlatform):
    name = "zeabur"
    display_name = "Zeabur"
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

            # Create zeabur-specific file
            file_path = os.path.join(accounts_dir, "zeabur_accounts.txt")

            # Format: email:password:token
            line = f"{account.email}:{account.password}:{account.token}\n"

            # Append to file
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(line)

            print(f"[ZEABUR] Account saved to {file_path}")
        except Exception as e:
            print(f"[ZEABUR] Warning: Failed to save account to text file: {e}")

    def register(self, email: str, password: Optional[str] = None) -> Account:
        from platforms.zeabur.core import ZeaburRegister

        log_fn = getattr(self, "_log_fn", print)
        proxy = self.config.proxy
        requested_headless = (self.config.executor_type or "headless") != "headed"

        captcha_solver = self._make_captcha()
        reg = ZeaburRegister(proxy=proxy, headless=requested_headless, captcha_solver=captcha_solver)
        reg.log = lambda msg: log_fn(f"[ZEABUR] {msg}")

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

                log_fn("Polling for Zeabur account verification email...")

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

                                            # Try multiple extraction patterns for Zeabur OTP/magic link
                                            search_text = f"{subject} {content}"
                                            patterns = [
                                                r'(?i)verification[^0-9]{0,50}(\d{6})',  # 6-digit code
                                                r'(?i)code[^0-9]{0,50}(\d{6})',
                                                r'(?i)\b(\d{6})\b',
                                                r'(?i)confirm[^0-9]{0,50}(\d{6})',
                                                r'(?i)zeabur[^0-9]{0,50}(\d{6})',
                                                r'(https?://[^\s<>\""]+zeabur[^\s<>\""]+)',  # Magic link
                                            ]

                                            for pattern in patterns:
                                                match = re.search(pattern, search_text)
                                                if match:
                                                    if match.group(0).startswith('http'):
                                                        # Return the full URL for magic link
                                                        code = match.group(0)
                                                        log_fn(f"Found magic link: {code[:50]}...")
                                                    else:
                                                        # Return just the code
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
                                    # Try to get either a 6-digit code or a magic link
                                    code = mailbox.wait_for_code(
                                        mail_acct,
                                        keyword="",
                                        timeout=5,
                                        before_ids=_before,
                                        code_pattern=r'\b(\d{6})\b|(https?://[^\s<>"""]+zeabur[^\s<>"""]+)',
                                    )
                                    if code and code.startswith('http'):
                                        # It's a magic link - return as-is
                                        pass
                                    elif code:
                                        # It's a code - extract just the digits if needed
                                        code_match = re.search(r'\b(\d{6})\b', code)
                                        if code_match:
                                            code = code_match.group(1)
                                except:
                                    pass

                        if not code:
                            time.sleep(3)

                    except Exception as e:
                        log_fn(f"Error in polling loop: {e}")
                        time.sleep(3)

                elapsed = int(time.time() - start_time)
                if code:
                    if code.startswith('http'):
                        log_fn(f"Magic link received after {elapsed}s: {code[:50]}...")
                    else:
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
            raise RuntimeError(f"Zeabur registration failed: {info.get('error')}")

        account = Account(
            platform="zeabur",
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