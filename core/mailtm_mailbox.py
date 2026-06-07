"""Mail.tm temporary email service integration"""

import requests
import random
import string
import re
from typing import Optional
from .base_mailbox import BaseMailbox, MailboxAccount
from .proxy_utils import build_requests_proxy_config


class MailTmMailbox(BaseMailbox):
    """Mail.tm temporary email service - Free temporary email with API access and multiple domains"""

    def __init__(
        self,
        api_url: str = "https://api.mail.tm",
        proxy: str = None,
    ):
        self.api = (api_url or "https://api.mail.tm").rstrip("/")
        self.proxy = build_requests_proxy_config(proxy)
        self._email = None
        self._password = None
        self._token = None

    def get_email(self) -> MailboxAccount:
        # 1. Fetch available domains
        try:
            r = requests.get(f"{self.api}/domains", proxies=self.proxy, timeout=10)
            r.raise_for_status()
            domains = r.json()
            # Handle standard paginated response
            if isinstance(domains, dict) and "hydra:member" in domains:
                domains = domains["hydra:member"]
            
            active_domains = [d["domain"] for d in domains if d.get("isActive")]
            if not active_domains:
                raise RuntimeError("No active domains found on Mail.tm")
            domain = random.choice(active_domains)
        except Exception as e:
            self._log(f"[Mail.tm] Failed to fetch domains: {e}, falling back to mail.tm")
            domain = "mail.tm"

        # 2. Generate random email and password
        username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
        email = f"{username}@{domain}"
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))

        # 3. Create account
        try:
            r = requests.post(
                f"{self.api}/accounts",
                json={"address": email, "password": password},
                proxies=self.proxy,
                timeout=10
            )
            r.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Failed to create account on Mail.tm: {e}")

        # 4. Get token
        try:
            r = requests.post(
                f"{self.api}/token",
                json={"address": email, "password": password},
                proxies=self.proxy,
                timeout=10
            )
            r.raise_for_status()
            token = r.json().get("token")
            if not token:
                raise RuntimeError("No token returned by Mail.tm")
        except Exception as e:
            raise RuntimeError(f"Failed to authenticate with Mail.tm: {e}")

        self._email = email
        self._password = password
        self._token = token
        self._log(f"[Mail.tm] Created mailbox: {email}")

        return MailboxAccount(
            email=email,
            account_id=email,
            extra={
                "provider": "mailtm",
                "password": password,
                "token": token
            }
        )

    def _list_messages(self, account: MailboxAccount) -> list[dict]:
        token = (account.extra or {}).get("token") or self._token
        if not token:
            self._log("[Mail.tm] No auth token found to check messages")
            return []

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {token}"
        }

        try:
            response = requests.get(
                f"{self.api}/messages",
                headers=headers,
                proxies=self.proxy,
                timeout=10,
            )
            if response.status_code >= 400:
                return []
            data = response.json()
            if isinstance(data, dict) and "hydra:member" in data:
                return data["hydra:member"]
            elif isinstance(data, list):
                return data
            return []
        except Exception:
            return []

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            messages = self._list_messages(account)
            return {
                str(msg.get("id") or "")
                for msg in messages
                if msg.get("id")
            }
        except Exception:
            return set()

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
        **kwargs,
    ) -> str:
        seen = {str(mid) for mid in (before_ids or set())}
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }
        keyword_lower = str(keyword or "").strip().lower()
        token = (account.extra or {}).get("token") or self._token

        def poll_once() -> Optional[str]:
            try:
                messages = self._list_messages(account)
                
                for message in messages:
                    message_id = str(message.get("id") or "").strip()
                    if not message_id or message_id in seen:
                        continue
                    seen.add(message_id)

                    # For mail.tm, list API doesn't give full body. Get message detail.
                    headers = {
                        "accept": "application/json",
                        "Authorization": f"Bearer {token}"
                    }
                    detail_res = requests.get(
                        f"{self.api}/messages/{message_id}",
                        headers=headers,
                        proxies=self.proxy,
                        timeout=5
                    )
                    if detail_res.status_code >= 400:
                        continue
                    msg_detail = detail_res.json()

                    search_text = " ".join(
                        [
                            str(msg_detail.get("subject") or ""),
                            str(msg_detail.get("from", {}).get("address") or ""),
                            str(msg_detail.get("text") or ""),
                            str(msg_detail.get("html") or ""),
                            str(msg_detail.get("intro") or ""),
                        ]
                    ).strip()

                    search_text = self._decode_raw_content(search_text) or search_text
                    
                    search_text = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        "",
                        search_text,
                    )

                    if keyword_lower and keyword_lower not in search_text.lower():
                        continue

                    code = self._safe_extract(search_text, code_pattern)
                    if not code:
                        continue
                        
                    if code in exclude_codes:
                        self._log(f"[Mail.tm] Skipping excluded code: {code}")
                        continue

                    self._log(f"[Mail.tm] Received verification code: {code}")
                    return code
            except Exception as e:
                self._log(f"[Mail.tm] Error polling message detail: {e}")
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )
