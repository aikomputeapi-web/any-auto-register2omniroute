"""CatchMail.io temporary email service integration"""

from typing import Optional
from .base_mailbox import BaseMailbox, MailboxAccount
from .proxy_utils import build_requests_proxy_config


class CatchMailMailbox(BaseMailbox):
    """CatchMail.io temporary email service - Free temporary email with API access"""

    def __init__(
        self,
        api_url: str = "https://api.catchmail.io",
        proxy: str = None,
        first_name: str = None,
        last_name: str = None,
    ):
        self.api = (api_url or "https://api.catchmail.io").rstrip("/")
        self.proxy = build_requests_proxy_config(proxy)
        self._email = None
        self._first_name = first_name
        self._last_name = last_name

    def get_email(self) -> MailboxAccount:
        import requests
        import random
        import string

        # Generate email address @catchmail.io using firstname+lastname if provided
        # CatchMail.io accepts any address, no need to call an API to create it
        if self._first_name and self._last_name:
            # Use firstname+lastname format
            prefix = f"{self._first_name.lower()}{self._last_name.lower()}"
        else:
            # Fallback to random generation
            prefix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))
        email = f"{prefix}@catchmail.io"

        self._email = email
        self._log(f"[CatchMail] Generated mailbox: {email}")
        
        return MailboxAccount(
            email=email,
            account_id=email,
            extra={"provider": "catchmail"},
        )

    def _list_messages(self, account: MailboxAccount) -> list[dict]:
        import requests

        email = account.email or self._email
        
        # Get messages using GET /api/v1/mailbox?address={email}
        try:
            response = requests.get(
                f"{self.api}/api/v1/mailbox",
                params={"address": email},
                headers={"accept": "application/json"},
                proxies=self.proxy,
                timeout=10,
            )
            
            if response.status_code >= 400:
                return []
                
            data = response.json()
            # CatchMail returns an array of messages directly or {"messages": [...]}
            if isinstance(data, list):
                messages = data
            else:
                messages = data.get("messages") or data.get("emails") or []
            return [msg for msg in messages if isinstance(msg, dict)]
        except Exception:
            return []

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            messages = self._list_messages(account)
            return {
                str(msg.get("id") or msg.get("messageId") or "")
                for msg in messages
                if msg.get("id") or msg.get("messageId")
            }
        except Exception:
            return set()

    def _get_message_detail(self, email: str, message_id: str) -> dict:
        import requests

        try:
            response = requests.get(
                f"{self.api}/api/v1/message/{message_id}",
                params={"mailbox": email},
                headers={"accept": "application/json"},
                proxies=self.proxy,
                timeout=10,
            )
            
            if response.status_code >= 400:
                return {}
                
            return response.json()
        except Exception as e:
            self._log(f"[CatchMail] Error fetching message detail for {message_id}: {e}")
            return {}

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
        **kwargs,
    ) -> str:
        import re

        seen = {str(mid) for mid in (before_ids or set())}
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }
        keyword_lower = str(keyword or "").strip().lower()

        def poll_once() -> Optional[str]:
            try:
                messages = self._list_messages(account)
                
                for message in messages:
                    message_id = str(
                        message.get("id") or message.get("messageId") or ""
                    ).strip()
                    
                    if not message_id or message_id in seen:
                        continue

                    # Fetch detailed message content
                    email = account.email or self._email
                    detail = self._get_message_detail(email, message_id)
                    if not detail:
                        continue

                    # Mark seen only after a successful detail fetch so we can retry on failure
                    seen.add(message_id)

                    # Build search text from detailed message content
                    search_text = " ".join(
                        [
                            str(detail.get("subject") or message.get("subject") or ""),
                            str(detail.get("from") or message.get("from") or ""),
                            str(detail.get("text") or ""),
                            str(detail.get("body") or ""),
                            str(detail.get("html") or ""),
                            str(detail.get("content") or ""),
                        ]
                    ).strip()

                    # Decode and clean the text
                    search_text = self._decode_raw_content(search_text) or search_text
                    
                    # Remove email addresses to avoid false matches
                    search_text = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        "",
                        search_text,
                    )

                    # Check keyword match
                    if keyword_lower and keyword_lower not in search_text.lower():
                        continue

                    # Extract verification code
                    code = self._safe_extract(search_text, code_pattern)
                    
                    if not code:
                        continue
                        
                    if code in exclude_codes:
                        self._log(f"[CatchMail] Skipping excluded code: {code}")
                        continue

                    self._log(f"[CatchMail] Received verification code: {code}")
                    return code
            except Exception as e:
                self._log(f"[CatchMail] Error polling CatchMail: {e}")
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )
