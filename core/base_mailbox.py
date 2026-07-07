from __future__ import annotations

"""Mailbox pool base class - Abstract temporary mailbox/Collection service"""

import json
import random
import threading
import time

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Any, Callable
from .proxy_utils import build_requests_proxy_config


@dataclass
class MailboxAccount:
    email: str
    account_id: str = ""
    extra: dict = None  # Platform additional information


class BaseMailbox(ABC):
    def _log(self, message: str) -> None:
        log_fn = getattr(self, "_log_fn", None)
        if callable(log_fn):
            log_fn(message)

    def _checkpoint(self, *, consume_skip: bool = True) -> None:
        task_control = getattr(self, "_task_control", None)
        if task_control is None:
            return
        task_control.checkpoint(
            consume_skip=consume_skip,
            attempt_id=getattr(self, "_task_attempt_token", None),
        )

    def _sleep_with_checkpoint(self, seconds: float) -> None:
        remaining = max(float(seconds or 0), 0.0)
        while remaining > 0:
            self._checkpoint()
            chunk = min(0.25, remaining)
            time.sleep(chunk)
            remaining -= chunk

    def _run_polling_wait(
        self,
        *,
        timeout: int,
        poll_interval: float,
        poll_once: Callable[[], Optional[str]],
        timeout_message: str | None = None,
    ) -> str:
        timeout_seconds = max(int(timeout or 0), 1)
        deadline = time.monotonic() + timeout_seconds

        while time.monotonic() < deadline:
            self._checkpoint()
            code = poll_once()
            if code:
                return code

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._sleep_with_checkpoint(min(float(poll_interval), remaining))

        self._checkpoint()
        raise TimeoutError(timeout_message or f"Timeout waiting for verification code ({timeout_seconds}s)")

    @abstractmethod
    def get_email(self) -> MailboxAccount:
        """Get an available email"""
        ...

    @abstractmethod
    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
        **kwargs,
    ) -> str:
        """Wait and return the verification code,code_pattern For custom regular expressions (default matching6digits)"""
        ...

    def _safe_extract(self, text: str, pattern: str = None) -> Optional[str]:
        """Universal verification code extraction logic: return if there is a capture group group(1), otherwise return group(0)"""
        import re

        text = str(text or "")
        if not text:
            return None

        patterns = []
        if pattern:
            patterns.append(pattern)

        # First match verification codes with obvious semantics to avoid mistaken extraction MIME boundary, timestamp, etc. 6 digits.
        patterns.extend(
            [
                r"(?is)(?:verification\s+code|one[-\s]*time\s+(?:password|code)|security\s+code|login\s+code|Verification code|Check code|dynamic code|Authentication code|Verification code)[^0-9]{0,30}(\d{6})",
                r"(?is)\bcode\b[^0-9]{0,12}(\d{6})",
                r"(?<!#)(?<!\d)(\d{6})(?!\d)",
            ]
        )

        for regex in patterns:
            m = re.search(regex, text)
            if m:
                # Compatible logic: if pattern If there is a capturing group in the group(1), otherwise take group(0)
                return m.group(1) if m.groups() else m.group(0)
        return None

    def _decode_raw_content(self, raw: str) -> str:
        """Parse the original text of the email (Borrowed from Fugle),deal with Quoted-Printable and HTML entity"""
        import quopri, html, re

        text = str(raw or "")
        if not text:
            return ""
        # Only split headers if the text looks like a raw email
        if re.search(
            r"(?im)^(?:Return-Path|Received|Date|From|To|Subject|Content-Type):", text
        ):
            # Simple segmentation Header and Body
            if "\r\n\r\n" in text:
                text = text.split("\r\n\r\n", 1)[1]
            elif "\n\n" in text:
                text = text.split("\n\n", 1)[1]
        try:
            # deal with Quoted-Printable
            decoded_bytes = quopri.decodestring(text)
            text = decoded_bytes.decode("utf-8", errors="ignore")
        except Exception:
            pass
        # Clear HTML Tag and escape
        text = html.unescape(text)
        text = re.sub(r"(?im)^content-(?:type|transfer-encoding):.*$", " ", text)
        text = re.sub(r"(?im)^--+[_=\w.-]+$", " ", text)
        text = re.sub(r"(?i)----=_part_[\w.]+", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @abstractmethod
    def get_current_ids(self, account: MailboxAccount) -> set:
        """Return to current email ID Collection (for filtering old mail)"""
        ...
    def _yyds_safe_extract(self, text: str, pattern: str = None) -> Optional[str]:
        """Universal verification code extraction logic: return if there is a capture group group(1), otherwise return group(0)"""
        import re

        text = str(text or "")
        if not text:
            return None

        # [Repair points 1]: Prioritize filtering out all URL links, preventing extraction directly from the source to trace links (e.g. SendGrid) random numbers in
        text = re.sub(r"https?://\S+", "", text)

        patterns = []
        if pattern:
            # [Repair points 2]: If pure external \d{6} Rough regularization of , automatically adding alphanumeric boundaries to it
            if pattern in (r"\d{6}", r"(\d{6})"):
                patterns.append(r"(?<![a-zA-Z0-9])(\d{6})(?![a-zA-Z0-9])")
            else:
                patterns.append(pattern)

        # First match verification codes with obvious semantics to avoid mistaken extraction MIME boundary, timestamp, etc. 6 digits.
        patterns.extend(
            [
                r"(?is)(?:verification\s+code|one[-\s]*time\s+(?:password|code)|security\s+code|login\s+code|Verification code|Check code|dynamic code|Authentication code|Verification code)[^0-9]{0,30}(\d{6})",
                r"(?is)\bcode\b[^0-9]{0,12}(\d{6})",
                # [Repair points 3]: Modify the rules and regulations and impose strict requirements 6 There cannot be letters or numbers before or after the digit (to prevent matching u20216706)
                r"(?<![a-zA-Z0-9])(\d{6})(?![a-zA-Z0-9])",
            ]
        )

        for regex in patterns:
            m = re.search(regex, text)
            if m:
                # Compatible logic: if pattern If there is a capturing group in the group(1), otherwise take group(0)
                return m.group(1) if m.groups() else m.group(0)
        return None

    def _yyds_decode_raw_content(self, raw: str) -> str:
        """Parse the original text of the email (Borrowed from Fugle),deal with Quoted-Printable and HTML entity"""
        import quopri, html, re

        text = str(raw or "")
        if not text:
            return ""
            
        # [Repair points 4]:Only if common messages are explicitly included Header only when \r\n\r\n Slice.
        # Otherwise it will be deleted by mistake MaliAPI Wait for the parsed data returned directly JSON Text content (error truncated when encountering ordinary text line breaks)
        if re.search(r"(?im)^(?:Return-Path|Received|Date|From|To|Subject|Content-Type):", text):
            if "\r\n\r\n" in text:
                text = text.split("\r\n\r\n", 1)[1]
            elif "\n\n" in text:
                text = text.split("\n\n", 1)[1]
                
        try:
            # deal with Quoted-Printable
            decoded_bytes = quopri.decodestring(text)
            text = decoded_bytes.decode("utf-8", errors="ignore")
        except Exception:
            pass
        # Clear HTML Tag and escape
        text = html.unescape(text)
        text = re.sub(r"(?im)^content-(?:type|transfer-encoding):.*$", " ", text)
        text = re.sub(r"(?im)^--+[_=\w.-]+$", " ", text)
        text = re.sub(r"(?i)----=_part_[\w.]+", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

def create_mailbox(
    provider: str, extra: dict = None, proxy: str = None
) -> "BaseMailbox":
    """Factory method: based on provider Create corresponding mailbox Example"""
    extra = extra or {}
    if provider == "tempmail_lol":
        return TempMailLolMailbox(proxy=proxy)
    elif provider == "skymail":
        return SkyMailMailbox(
            api_base=extra.get("skymail_api_base", "https://api.skymail.ink"),
            auth_token=extra.get("skymail_token", ""),
            domain=extra.get("skymail_domain", ""),
            proxy=proxy,
        )
    elif provider == "cloudmail":
        timeout_raw = extra.get("cloudmail_timeout", extra.get("timeout", 30))
        try:
            timeout_value = int(timeout_raw)
        except (TypeError, ValueError):
            timeout_value = 30
        return CloudMailMailbox(
            api_base=extra.get("cloudmail_api_base")
            or extra.get("base_url")
            or "",
            admin_email=extra.get("cloudmail_admin_email")
            or extra.get("admin_email")
            or "",
            admin_password=extra.get("cloudmail_admin_password")
            or extra.get("admin_password")
            or extra.get("api_key")
            or "",
            domain=extra.get("cloudmail_domain") or extra.get("domain") or "",
            subdomain=extra.get("cloudmail_subdomain")
            or extra.get("subdomain")
            or "",
            timeout=timeout_value,
            proxy=proxy,
        )
    elif provider == "duckmail":
        return DuckMailMailbox(
            api_url=(extra.get("duckmail_api_url") or "https://www.duckmail.sbs"),
            provider_url=(
                extra.get("duckmail_provider_url") or "https://api.duckmail.sbs"
            ),
            bearer=(extra.get("duckmail_bearer") or "kevin273945"),
            domain=extra.get("duckmail_domain", ""),
            api_key=extra.get("duckmail_api_key", ""),
            proxy=proxy,
        )
    elif provider == "freemail":
        return FreemailMailbox(
            api_url=extra.get("freemail_api_url", ""),
            admin_token=extra.get("freemail_admin_token", ""),
            username=extra.get("freemail_username", ""),
            password=extra.get("freemail_password", ""),
            domain=extra.get("freemail_domain", ""),
            proxy=proxy,
        )
    elif provider == "moemail":
        return MoeMailMailbox(
            api_url=extra.get("moemail_api_url", "https://sall.cc"),
            api_key=extra.get("moemail_api_key", ""),
            proxy=proxy,
        )
    elif provider == "maliapi":
        return MaliAPIMailbox(
            api_url=extra.get("maliapi_base_url", "https://maliapi.215.im/v1"),
            api_key=extra.get("maliapi_api_key", ""),
            domain=extra.get("maliapi_domain", ""),
            auto_domain_strategy=extra.get("maliapi_auto_domain_strategy", ""),
            proxy=proxy,
        )
    elif provider == "gptmail":
        return GPTMailMailbox(
            api_url=extra.get("gptmail_base_url", "https://mail.chatgpt.org.uk"),
            api_key=extra.get("gptmail_api_key", ""),
            domain=extra.get("gptmail_domain", ""),
            proxy=proxy,
        )
    elif provider == "applemail":
        return AppleMailMailbox(
            api_url=extra.get("applemail_base_url", "https://www.appleemail.top"),
            pool_file=extra.get("applemail_pool_file", ""),
            pool_dir=extra.get("applemail_pool_dir", "mail"),
            mailboxes=extra.get("applemail_mailboxes", "INBOX,Junk"),
            proxy=proxy,
        )
    elif provider == "opentrashmail":
        return OpenTrashMailMailbox(
            api_url=extra.get("opentrashmail_api_url", ""),
            domain=extra.get("opentrashmail_domain", ""),
            password=extra.get("opentrashmail_password", ""),
            proxy=proxy,
        )
    elif provider == "cfworker":
        return CFWorkerMailbox(
            api_url=extra.get("cfworker_api_url", ""),
            admin_token=extra.get("cfworker_admin_token", ""),
            domain=extra.get("cfworker_domain", ""),
            domain_override=extra.get("cfworker_domain_override", ""),
            domains=extra.get("cfworker_domains", ""),
            enabled_domains=extra.get("cfworker_enabled_domains", ""),
            subdomain=extra.get("cfworker_subdomain", ""),
            domain_level_count=extra.get("email_domain_level_count", 2),
            random_subdomain=extra.get("cfworker_random_subdomain", False),
            random_name_subdomain=extra.get("cfworker_random_name_subdomain", False),
            fingerprint=extra.get("cfworker_fingerprint", ""),
            custom_auth=extra.get("cfworker_custom_auth", ""),
            proxy=proxy,
        )
    elif provider == "luckmail":
        return LuckMailMailbox(
            base_url=extra.get("luckmail_base_url") or "https://mails.luckyous.com/",
            api_key=extra.get("luckmail_api_key", ""),
            project_code=extra.get("luckmail_project_code", ""),
            email_type=extra.get("luckmail_email_type", ""),
            domain=extra.get("luckmail_domain", ""),
            proxy=proxy,
        )
    elif provider == "imap_catchall":
        return ImapCatchallMailbox(
            imap_server=extra.get("imap_catchall_server", ""),
            imap_port=extra.get("imap_catchall_port", 993),
            imap_username=extra.get("imap_catchall_username", ""),
            imap_password=extra.get("imap_catchall_password", ""),
            domain=extra.get("imap_catchall_domain", ""),
            folders=extra.get("imap_catchall_folders", "INBOX"),
            proxy=proxy,
        )
    elif provider in {"outlook", "microsoft"}:
        return OutlookMailbox(
            imap_server=extra.get("outlook_imap_server", ""),
            imap_port=extra.get("outlook_imap_port", ""),
            token_endpoint=extra.get("outlook_token_endpoint", ""),
            backend=extra.get("outlook_backend", ""),
            graph_api_base=extra.get("outlook_graph_api_base", ""),
            proxy=proxy,
        )
    elif provider == "catchmail":
        from .catchmail_mailbox import CatchMailMailbox
        return CatchMailMailbox(
            api_url=extra.get("catchmail_api_url", "https://catchmail.io"),
            proxy=proxy,
            first_name=extra.get("first_name"),
            last_name=extra.get("last_name"),
        )
    elif provider == "mailtm":
        from .mailtm_mailbox import MailTmMailbox
        return MailTmMailbox(
            api_url=extra.get("mailtm_api_url", "https://api.mail.tm"),
            proxy=proxy,
        )
    else:  # laoudo
        return LaoudoMailbox(
            auth_token=extra.get("laoudo_auth", ""),
            email=extra.get("laoudo_email", ""),
            account_id=extra.get("laoudo_account_id", ""),
        )


class AppleMailMailbox(BaseMailbox):
    """Little Apple mailbox service, rotating mailbox accounts based on local mailbox pool files"""

    def __init__(
        self,
        api_url: str = "https://www.appleemail.top",
        pool_file: str = "",
        pool_dir: str = "mail",
        mailboxes: str = "INBOX,Junk",
        proxy: str = None,
    ):
        self.api = (api_url or "https://www.appleemail.top").rstrip("/")
        self.pool_file = str(pool_file or "").strip()
        self.pool_dir = str(pool_dir or "mail").strip() or "mail"
        self.mailboxes = self._normalize_mailboxes(mailboxes)
        self.proxy = build_requests_proxy_config(proxy)
        self._email = None
        self._selected_record = None
        self._selected_pool_path = None

    @staticmethod
    def _normalize_mailboxes(value: Any) -> list[str]:
        if isinstance(value, (list, tuple, set)):
            items = [str(item or "").strip() for item in value]
        else:
            raw = str(value or "INBOX,Junk").strip() or "INBOX,Junk"
            items = [item.strip() for item in raw.split(",")]

        result = []
        seen = set()
        for item in items:
            if not item:
                continue
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result or ["INBOX", "Junk"]

    def _headers(self) -> dict[str, str]:
        return {"accept": "application/json"}

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any],
        timeout: int = 15,
    ) -> Any:
        import requests

        response = requests.request(
            method,
            f"{self.api}{path}",
            params=payload,
            json=None,
            headers=self._headers(),
            proxies=self.proxy,
            timeout=timeout,
        )
        try:
            data = response.json()
        except Exception as exc:
            preview = (response.text or "")[:200]
            raise RuntimeError(
                f"AppleMail API {path} Return non JSON: HTTP {response.status_code} {preview}"
            ) from exc

        if response.status_code >= 400:
            if isinstance(data, dict):
                message = (
                    data.get("detail")
                    or data.get("message")
                    or data.get("error")
                    or response.text
                )
            else:
                message = response.text
            raise RuntimeError(
                f"AppleMail API {path} fail: {str(message or f'HTTP {response.status_code}').strip()}"
            )

        if isinstance(data, dict) and data.get("success") is False:
            message = (
                data.get("message")
                or data.get("detail")
                or data.get("error")
                or "unknown error"
            )
            raise RuntimeError(f"AppleMail API {path} fail: {str(message).strip()}")

        return data

    @staticmethod
    def _unwrap_message_payload(payload: Any) -> list[dict[str, Any]]:
        if payload is None:
            return []
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("data", "result", "results", "messages", "mails", "emails", "items", "list"):
                if key in payload:
                    nested = AppleMailMailbox._unwrap_message_payload(payload.get(key))
                    if nested:
                        return nested
            if any(
                key in payload
                for key in (
                    "id",
                    "message_id",
                    "uid",
                    "mail_id",
                    "subject",
                    "content",
                    "text",
                    "html",
                    "body",
                    "preview",
                    "verification_code",
                    "code",
                    "otp",
                )
            ):
                return [payload]

            collected = []
            for value in payload.values():
                collected.extend(AppleMailMailbox._unwrap_message_payload(value))
            return collected
        return []

    @staticmethod
    def _resolve_message_id(message: dict[str, Any], mailbox: str) -> str:
        import hashlib

        for key in ("id", "message_id", "uid", "mail_id", "mid", "_id"):
            value = str(message.get(key) or "").strip()
            if value:
                return value

        raw = json.dumps(message, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha1(f"{mailbox}:{raw}".encode("utf-8")).hexdigest()
        return f"{mailbox}:{digest}"

    def _build_search_text(self, message: dict[str, Any]) -> str:
        parts = []
        for key in (
            "subject",
            "from",
            "from_address",
            "sender",
            "preview",
            "text",
            "content",
            "body",
            "html",
            "html_content",
            "raw",
            "raw_content",
            "mail_text",
        ):
            value = message.get(key)
            if value:
                parts.append(str(value))

        if not parts:
            parts.append(json.dumps(message, ensure_ascii=False))

        text = " ".join(parts).strip()
        return self._decode_raw_content(text) or text

    def _extract_code_from_message(
        self,
        message: dict[str, Any],
        code_pattern: str = None,
    ) -> Optional[str]:
        for key in ("verification_code", "code", "otp", "captcha", "verify_code"):
            value = str(message.get(key) or "").strip()
            if value:
                code = self._safe_extract(value, code_pattern)
                if code:
                    return code
        return self._safe_extract(self._build_search_text(message), code_pattern)

    def _resolve_mailboxes_for_account(self, account: MailboxAccount) -> list[str]:
        account_mailbox = ""
        if isinstance(account.extra, dict):
            account_mailbox = str(account.extra.get("mailbox") or "").strip()

        result = []
        seen = set()
        for mailbox in ([account_mailbox] if account_mailbox else []) + list(self.mailboxes):
            name = str(mailbox or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
        return result or ["INBOX"]

    def _build_request_payload(self, account: MailboxAccount, mailbox: str) -> dict[str, Any]:
        extra = account.extra or {}
        refresh_token = str(extra.get("refresh_token") or "").strip()
        client_id = str(extra.get("client_id") or "").strip()
        if not refresh_token or not client_id:
            raise RuntimeError("AppleMail Email record is missing refresh_token or client_id")

        return {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "email": account.email,
            "mailbox": mailbox,
        }

    def _list_messages(self, account: MailboxAccount, mailbox: str) -> list[dict[str, Any]]:
        data = self._request_json(
            "GET",
            "/api/mail-all",
            payload=self._build_request_payload(account, mailbox),
            timeout=15,
        )
        if isinstance(data, dict):
            new_refresh_token = str(data.get("new_refresh_token") or "").strip()
            if new_refresh_token:
                if account.extra is None:
                    account.extra = {}
                account.extra["refresh_token"] = new_refresh_token
        return self._unwrap_message_payload(data)

    def get_email(self) -> MailboxAccount:
        from .applemail_pool import take_next_applemail_record

        pool_path, record = take_next_applemail_record(
            pool_file=self.pool_file,
            pool_dir=self.pool_dir,
        )
        self._selected_pool_path = pool_path
        self._selected_record = record
        self._email = record["email"]
        self._log(f"[AppleMail] Use a mailbox pool: {pool_path.name}")
        self._log(f"[AppleMail] Assign mailbox: {record['email']}")
        return MailboxAccount(
            email=record["email"],
            account_id=record["email"],
            extra={
                "provider": "applemail",
                "client_id": record["client_id"],
                "refresh_token": record["refresh_token"],
                "mailbox": record.get("mailbox") or "INBOX",
                "pool_file": pool_path.name,
            },
        )

    def get_current_ids(self, account: MailboxAccount) -> set:
        ids = set()
        for mailbox in self._resolve_mailboxes_for_account(account):
            try:
                messages = self._list_messages(account, mailbox)
            except Exception:
                continue
            ids.update(
                self._resolve_message_id(message, mailbox)
                for message in messages
            )
        return ids

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

        def poll_once() -> Optional[str]:
            for mailbox in self._resolve_mailboxes_for_account(account):
                try:
                    messages = self._list_messages(account, mailbox)
                except Exception:
                    continue

                for message in messages:
                    message_id = self._resolve_message_id(message, mailbox)
                    if message_id in seen:
                        continue
                    seen.add(message_id)

                    search_text = self._build_search_text(message)
                    if keyword and keyword.lower() not in search_text.lower():
                        continue

                    code = self._extract_code_from_message(message, code_pattern)
                    if code and code in exclude_codes:
                        continue
                    if code:
                        self._log(f"[AppleMail] {mailbox} Receive verification code: {code}")
                        return code
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class LaoudoMailbox(BaseMailbox):
    """laoudo.com Email service"""

    def __init__(self, auth_token: str, email: str, account_id: str):
        self.auth = auth_token
        self._email = email
        self._account_id = account_id
        self.api = "https://laoudo.com/api/email"
        self._ua = "Mozilla/5.0"

    def get_email(self) -> MailboxAccount:
        if not self._email:
            raise RuntimeError(
                "Laoudo The email is not configured or has expired, please check laoudo_auth,laoudo_email,laoudo_account_id configuration,"
                "or switch to tempmail_lol(no configuration required)"
            )
        return MailboxAccount(email=self._email, account_id=self._account_id)

    def get_current_ids(self, account: MailboxAccount) -> set:
        from curl_cffi import requests as curl_requests

        try:
            r = curl_requests.get(
                f"{self.api}/list",
                params={
                    "accountId": account.account_id,
                    "allReceive": 0,
                    "emailId": 0,
                    "timeSort": 1,
                    "size": 50,
                    "type": 0,
                },
                headers={"authorization": self.auth, "user-agent": self._ua},
                timeout=15,
                impersonate="chrome131",
            )
            if r.status_code == 200:
                mails = r.json().get("data", {}).get("list", []) or []
                return {
                    m.get("id") or m.get("emailId")
                    for m in mails
                    if m.get("id") or m.get("emailId")
                }
        except Exception:
            pass
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
        from curl_cffi import requests as curl_requests

        seen = set(before_ids) if before_ids else set()
        h = {"authorization": self.auth, "user-agent": self._ua}

        def poll_once() -> Optional[str]:
            try:
                r = curl_requests.get(
                    f"{self.api}/list",
                    params={
                        "accountId": account.account_id,
                        "allReceive": 0,
                        "emailId": 0,
                        "timeSort": 1,
                        "size": 50,
                        "type": 0,
                    },
                    headers=h,
                    timeout=15,
                    impersonate="chrome131",
                )
                if r.status_code == 200:
                    mails = r.json().get("data", {}).get("list", []) or []
                    for mail in mails:
                        mid = mail.get("id") or mail.get("emailId")
                        if not mid or mid in seen:
                            continue
                        seen.add(mid)
                        text = (
                            str(mail.get("subject", ""))
                            + " "
                            + str(mail.get("content") or mail.get("html") or "")
                        )
                        if keyword and keyword.lower() not in text.lower():
                            continue
                        code = self._safe_extract(text, code_pattern)
                        if code:
                            return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=4,
            poll_once=poll_once,
        )


class AitreMailbox(BaseMailbox):
    """mail.aitre.cc Temporary mailbox"""

    def __init__(self, email: str):
        self._email = email
        self.api = "https://mail.aitre.cc/api/tempmail"

    def get_email(self) -> MailboxAccount:
        return MailboxAccount(email=self._email)

    def get_current_ids(self, account: MailboxAccount) -> set:
        import requests

        try:
            r = requests.get(
                f"{self.api}/emails", params={"email": account.email}, timeout=10
            )
            emails = r.json().get("emails", [])
            return {str(m["id"]) for m in emails if "id" in m}
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
        import requests

        seen = set(before_ids) if before_ids else set()
        last_check = None

        def poll_once() -> Optional[str]:
            nonlocal last_check
            params = {"email": account.email}
            if last_check:
                params["lastCheck"] = last_check
            try:
                r = requests.get(f"{self.api}/poll", params=params, timeout=10)
                data = r.json()
                last_check = data.get("lastChecked")
                if data.get("count", 0) > 0:
                    r2 = requests.get(
                        f"{self.api}/emails",
                        params={"email": account.email},
                        timeout=10,
                    )
                    for mail in r2.json().get("emails", []):
                        mid = str(mail.get("id", ""))
                        if mid in seen:
                            continue
                        seen.add(mid)
                        text = mail.get("preview", "") + mail.get("content", "")
                        if keyword and keyword.lower() not in text.lower():
                            continue
                        code = self._safe_extract(text, code_pattern)
                        if code:
                            return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class TempMailLolMailbox(BaseMailbox):
    """tempmail.lol Free temporary email (no registration required, automatically generated)"""

    def __init__(self, proxy: str = None):
        self.api = "https://api.tempmail.lol/v2"
        self.proxy = build_requests_proxy_config(proxy)
        self._token = None
        self._email = None

    def get_email(self) -> MailboxAccount:
        import requests

        r = requests.post(
            f"{self.api}/inbox/create", json={}, proxies=self.proxy, timeout=15
        )
        data = r.json()
        email = data.get("address") or data.get("email", "")
        if not email:
            raise RuntimeError(f"tempmail.lol API Return empty mailbox: {data}")
        self._email = email
        self._token = data.get("token", "")
        print(f"[TempMailLol] Generate mailbox: {self._email}")
        return MailboxAccount(email=self._email, account_id=self._token)

    def get_current_ids(self, account: MailboxAccount) -> set:
        import requests

        try:
            r = requests.get(
                f"{self.api}/inbox",
                params={"token": account.account_id},
                proxies=self.proxy,
                timeout=10,
            )
            return {str(m["id"]) for m in r.json().get("emails", [])}
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
        import requests

        seen = set(before_ids or [])
        otp_sent_at = kwargs.get("otp_sent_at")
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }

        def poll_once() -> Optional[str]:
            try:
                r = requests.get(
                    f"{self.api}/inbox",
                    params={"token": account.account_id},
                    proxies=self.proxy,
                    timeout=10,
                )
                for mail in sorted(
                    r.json().get("emails", []),
                    key=lambda x: x.get("date", 0),
                    reverse=True,
                ):
                    mid = str(mail.get("id", ""))
                    if mid in seen:
                        continue
                    # tempmail.lol returns dates as Unix seconds (not ms).
                    # Do NOT divide by 1000 — that maps recent timestamps to ~1970
                    # and causes ALL emails to be filtered out when otp_sent_at is set.
                    mail_date = mail.get("date", 0)
                    if otp_sent_at and mail_date < otp_sent_at:
                        continue
                    seen.add(mid)
                    text = (
                        mail.get("subject", "")
                        + " "
                        + mail.get("body", "")
                        + " "
                        + mail.get("html", "")
                    )
                    if keyword and keyword.lower() not in text.lower():
                        continue
                    code = self._safe_extract(text, code_pattern)
                    if code and code in exclude_codes:
                        continue
                    if code:
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class SkyMailMailbox(BaseMailbox):
    """SkyMail / CloudMail Self-built email service"""

    def __init__(self, api_base: str, auth_token: str, domain: str, proxy: str = None):
        self.api = (api_base or "").rstrip("/")
        self.auth_token = auth_token or ""
        self.domain = domain or ""
        self.proxy = build_requests_proxy_config(proxy)

    def _headers(self) -> dict:
        return {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": self.auth_token,
        }

    def _ensure_config(self) -> None:
        if not self.api or not self.auth_token or not self.domain:
            raise RuntimeError(
                "SkyMail Not fully configured: please set skymail_api_base,skymail_token,skymail_domain"
            )

    def _gen_prefix(self) -> str:
        import random
        import string

        length = random.randint(8, 13)
        chars = string.ascii_lowercase + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    def get_email(self) -> MailboxAccount:
        import requests

        self._ensure_config()
        email = f"{self._gen_prefix()}@{self.domain}"
        payload = {"list": [{"email": email}]}
        r = requests.post(
            f"{self.api}/api/public/addUser",
            json=payload,
            headers=self._headers(),
            proxies=self.proxy,
            timeout=15,
        )
        if r.status_code != 200:
            raise RuntimeError(f"SkyMail Failed to create mailbox: {r.status_code} {r.text[:200]}")

        data = r.json()
        if data.get("code") != 200:
            raise RuntimeError(f"SkyMail Failed to create mailbox: {data}")

        self._log(f"[SkyMail] Generate mailbox: {email}")
        return MailboxAccount(email=email, account_id=email)

    def _list_mails(self, email: str) -> list:
        import requests

        payload = {
            "toEmail": email,
            "num": 1,
            "size": 20,
        }
        r = requests.post(
            f"{self.api}/api/public/emailList",
            json=payload,
            headers=self._headers(),
            proxies=self.proxy,
            timeout=15,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        if data.get("code") != 200:
            return []
        return data.get("data") or []

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            mails = self._list_mails(account.account_id or account.email)
            ids = set()
            for i, msg in enumerate(mails):
                mid = msg.get("id") or msg.get("mailId") or msg.get("messageId")
                if mid:
                    ids.add(str(mid))
                else:
                    digest = (
                        str(msg.get("date") or msg.get("time") or "")
                        + "|"
                        + str(msg.get("subject") or "")
                    )
                    ids.add(f"idx-{i}-{digest}")
            return ids
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
        target = account.account_id or account.email
        seen = set(before_ids or [])

        def poll_once() -> Optional[str]:
            try:
                mails = self._list_mails(target)
                for i, msg in enumerate(mails):
                    mid = msg.get("id") or msg.get("mailId") or msg.get("messageId")
                    if not mid:
                        digest = (
                            str(msg.get("date") or msg.get("time") or "")
                            + "|"
                            + str(msg.get("subject") or "")
                        )
                        mid = f"idx-{i}-{digest}"
                    mid = str(mid)
                    if mid in seen:
                        continue
                    seen.add(mid)

                    content = " ".join(
                        [
                            str(msg.get("subject") or ""),
                            str(msg.get("content") or ""),
                            str(msg.get("text") or ""),
                            str(msg.get("html") or ""),
                        ]
                    )
                    if keyword and keyword.lower() not in content.lower():
                        continue

                    code = self._safe_extract(content, code_pattern)
                    if code:
                        self._log(f"[SkyMail] Hit verification code: {code}")
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class CloudMailMailbox(BaseMailbox):
    """CloudMail Self-built email service (genToken + emailList)"""

    _token_lock = threading.Lock()
    _token_cache: dict[str, tuple[str, float]] = {}
    _seen_ids_lock = threading.Lock()
    _seen_ids: dict[str, set[str]] = {}

    def __init__(
        self,
        api_base: str,
        admin_email: str,
        admin_password: str,
        domain: Any = "",
        subdomain: str = "",
        timeout: int = 30,
        proxy: str = None,
    ):
        self.api = str(api_base or "").rstrip("/")
        self.admin_email = str(admin_email or "").strip()
        self.admin_password = str(admin_password or "").strip()
        self.domain = domain
        self.subdomain = str(subdomain or "").strip()
        self.timeout = max(int(timeout or 30), 5)
        self.proxy = build_requests_proxy_config(proxy)

    @staticmethod
    def _extract_domain_from_url(url: str) -> str:
        from urllib.parse import urlparse

        parsed = urlparse(str(url or ""))
        host = (parsed.netloc or parsed.path.split("/")[0] or "").strip()
        if ":" in host:
            host = host.split(":", 1)[0].strip()
        return host

    @staticmethod
    def _normalize_domain(value: str) -> str:
        domain = str(value or "").strip().lstrip("@")
        if "://" in domain:
            domain = CloudMailMailbox._extract_domain_from_url(domain)
        return domain.strip()

    def _domain_candidates(self) -> list[str]:
        candidates: list[str] = []

        if isinstance(self.domain, (list, tuple, set)):
            iterable = self.domain
        else:
            raw = str(self.domain or "").strip()
            parsed = None
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None
            if isinstance(parsed, list):
                iterable = parsed
            elif raw:
                normalized = (
                    raw.replace(";", "\n")
                    .replace(",", "\n")
                    .replace("|", "\n")
                    .splitlines()
                )
                iterable = [item for item in normalized if item]
            else:
                iterable = []

        for item in iterable:
            normalized = self._normalize_domain(item)
            if normalized:
                candidates.append(normalized)

        if not candidates:
            inferred = self._normalize_domain(self._extract_domain_from_url(self.api))
            if inferred:
                candidates.append(inferred)
        return candidates

    def _resolve_admin_email(self) -> str:
        if self.admin_email:
            return self.admin_email
        domains = self._domain_candidates()
        if domains:
            return f"admin@{domains[0]}"
        return "admin@example.com"

    def _cache_key(self) -> str:
        return f"{self.api}|{self._resolve_admin_email()}|{self.admin_password}"

    def _ensure_config(self) -> None:
        if not self.api or not self.admin_password:
            raise RuntimeError(
                "CloudMail Not fully configured: please set cloudmail_api_base and cloudmail_admin_password"
            )

    def _headers(self, token: str = "") -> dict:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        if token:
            headers["authorization"] = token
        return headers

    def _generate_token(self) -> str:
        import requests

        self._ensure_config()
        payload = {
            "email": self._resolve_admin_email(),
            "password": self.admin_password,
        }
        r = requests.post(
            f"{self.api}/api/public/genToken",
            json=payload,
            headers=self._headers(),
            proxies=self.proxy,
            timeout=self.timeout,
        )
        if r.status_code != 200:
            raise RuntimeError(
                f"CloudMail generate token fail: {r.status_code} {str(r.text or '')[:200]}"
            )

        try:
            data = r.json()
        except Exception:
            data = {}
        if data.get("code") != 200:
            raise RuntimeError(f"CloudMail generate token fail: {data}")
        token = ((data.get("data") or {}).get("token") or "").strip()
        if not token:
            raise RuntimeError("CloudMail generate token fail: Response not returned token")
        return token

    def _get_token(self, *, force_refresh: bool = False) -> str:
        cache_key = self._cache_key()
        now = time.time()
        with CloudMailMailbox._token_lock:
            if not force_refresh:
                cached = CloudMailMailbox._token_cache.get(cache_key)
                if cached and now < cached[1]:
                    return cached[0]

            token = self._generate_token()
            CloudMailMailbox._token_cache[cache_key] = (token, now + 3600)
            return token

    def _list_mails(self, email: str, *, retry_auth: bool = True) -> list:
        import requests

        token = self._get_token()
        payload = {
            "toEmail": email,
            "timeSort": "desc",
        }
        r = requests.post(
            f"{self.api}/api/public/emailList",
            json=payload,
            headers=self._headers(token),
            proxies=self.proxy,
            timeout=self.timeout,
        )
        if r.status_code == 401 and retry_auth:
            token = self._get_token(force_refresh=True)
            r = requests.post(
                f"{self.api}/api/public/emailList",
                json=payload,
                headers=self._headers(token),
                proxies=self.proxy,
                timeout=self.timeout,
            )
        if r.status_code != 200:
            return []

        try:
            data = r.json()
        except Exception:
            data = {}
        if data.get("code") != 200:
            return []
        return data.get("data") or []

    def _gen_prefix(self) -> str:
        import random
        import string

        first = random.choice(string.ascii_lowercase)
        rest = "".join(random.choices(string.ascii_lowercase + string.digits, k=9))
        return first + rest

    def _build_email(self) -> str:
        domains = self._domain_candidates()
        if not domains:
            raise RuntimeError("CloudMail No available domain name configured")
        domain = random.choice(domains)
        if self.subdomain:
            domain = f"{self.subdomain}.{domain}"
        return f"{self._gen_prefix()}@{domain}"

    @staticmethod
    def _parse_message_timestamp(message: dict) -> Optional[float]:
        from datetime import datetime

        keys = [
            "time",
            "date",
            "created",
            "createdAt",
            "created_at",
            "receivedAt",
            "received_at",
            "sendTime",
            "timestamp",
        ]
        for key in keys:
            value = message.get(key)
            if value in (None, ""):
                continue
            if isinstance(value, (int, float)):
                numeric = float(value)
                return numeric / 1000 if numeric > 10_000_000_000 else numeric
            text = str(value).strip()
            if not text:
                continue
            try:
                numeric = float(text)
                return numeric / 1000 if numeric > 10_000_000_000 else numeric
            except (TypeError, ValueError):
                pass
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
        return None

    @staticmethod
    def _mail_id(message: dict, index: int = 0) -> str:
        for key in ("emailId", "id", "mailId", "messageId"):
            value = message.get(key)
            if value not in (None, ""):
                return str(value)
        digest = (
            str(message.get("date") or message.get("time") or "")
            + "|"
            + str(message.get("subject") or "")
        )
        return f"idx-{index}-{digest}"

    def _remember_seen_id(self, email: str, message_id: str) -> None:
        with CloudMailMailbox._seen_ids_lock:
            CloudMailMailbox._seen_ids.setdefault(email, set()).add(message_id)

    def _load_seen_ids(self, email: str) -> set[str]:
        with CloudMailMailbox._seen_ids_lock:
            return set(CloudMailMailbox._seen_ids.get(email, set()))

    def get_email(self) -> MailboxAccount:
        self._ensure_config()
        email = self._build_email()
        self._log(f"[CloudMail] Generate mailbox: {email}")
        return MailboxAccount(email=email, account_id=email)

    def get_current_ids(self, account: MailboxAccount) -> set:
        target = account.account_id or account.email
        try:
            mails = self._list_mails(target)
            return {self._mail_id(msg, idx) for idx, msg in enumerate(mails)}
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
        target = account.account_id or account.email
        seen = set(before_ids or set())
        seen.update(self._load_seen_ids(target))
        otp_sent_at = kwargs.get("otp_sent_at")
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }

        def poll_once() -> Optional[str]:
            try:
                mails = self._list_mails(target)
                for idx, msg in enumerate(mails):
                    mid = self._mail_id(msg, idx)
                    if mid in seen:
                        continue
                    seen.add(mid)
                    self._remember_seen_id(target, mid)

                    msg_ts = self._parse_message_timestamp(msg)
                    if otp_sent_at and msg_ts and msg_ts < float(otp_sent_at):
                        continue

                    content = " ".join(
                        [
                            str(msg.get("subject") or ""),
                            str(msg.get("content") or ""),
                            str(msg.get("text") or ""),
                            str(msg.get("html") or ""),
                        ]
                    )
                    if keyword and keyword.lower() not in content.lower():
                        continue
                    code = self._safe_extract(content, code_pattern)
                    if code and code in exclude_codes:
                        continue
                    if code:
                        self._log(f"[CloudMail] Hit verification code: {code}")
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class DuckMailMailbox(BaseMailbox):
    """DuckMail Automatically generate email addresses (randomly create accounts)"""

    def __init__(
        self,
        api_url: str = "https://www.duckmail.sbs",
        provider_url: str = "https://api.duckmail.sbs",
        bearer: str = "kevin273945",
        domain: str = "",
        api_key: str = "",
        proxy: str = None,
    ):
        self.api = (api_url or "https://www.duckmail.sbs").rstrip("/")
        self.provider_url = (provider_url or "https://api.duckmail.sbs").rstrip("/")
        self.bearer = bearer or "kevin273945"
        self.domain = str(domain or "").strip()
        self.api_key = str(api_key or "").strip()
        self.proxy = build_requests_proxy_config(proxy)
        self._token = None
        self._address = None
        # If configured API Key, request directly DuckMail API; Otherwise, use the front-end proxy
        self._direct = bool(self.api_key)

    def _proxy_headers(self) -> dict:
        return {
            "authorization": f"Bearer {self.bearer}",
            "content-type": "application/json",
            "x-api-provider-base-url": self.provider_url,
        }

    def _direct_headers(self, token: str = "") -> dict:
        auth = token or self.api_key
        return {
            "authorization": f"Bearer {auth}",
            "content-type": "application/json",
        }

    def _request(self, method: str, endpoint: str, token: str = "", **kwargs):
        """Unified request method, choose direct connection or proxy according to the mode"""
        import requests

        if self._direct:
            url = f"{self.provider_url}{endpoint}"
            headers = self._direct_headers(token)
        else:
            from urllib.parse import quote

            url = f"{self.api}/api/mail?endpoint={quote(endpoint, safe='')}"
            headers = (
                self._proxy_headers()
                if not token
                else {
                    "authorization": f"Bearer {token}",
                    "x-api-provider-base-url": self.provider_url,
                }
            )
        r = requests.request(
            method, url, headers=headers, proxies=self.proxy, timeout=15, **kwargs
        )
        return r

    def get_email(self) -> MailboxAccount:
        import random, string

        username = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        password = "Test" + "".join(random.choices(string.digits, k=8)) + "!"
        domain = self.domain or self.provider_url.replace("https://api.", "").replace(
            "https://", ""
        )
        address = f"{username}@{domain}"
        print(f"[DuckMail] Create account: {address} direct={self._direct}")
        # Create account
        r = self._request(
            "POST", "/accounts", json={"address": address, "password": password}
        )
        if r.status_code >= 400 or not r.text.strip().startswith("{"):
            raise RuntimeError(
                f"[DuckMail] Failed to create account: HTTP {r.status_code} body={r.text[:300]}"
            )
        data = r.json()
        self._address = data.get("address", address)
        # Log in to get token
        r2 = self._request(
            "POST", "/token", json={"address": self._address, "password": password}
        )
        if r2.status_code >= 400 or not r2.text.strip().startswith(("{", "[")):
            raise RuntimeError(
                f"[DuckMail] Login failed: HTTP {r2.status_code} body={r2.text[:300]}"
            )
        self._token = r2.json().get("token", "")
        return MailboxAccount(email=self._address, account_id=self._token)

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            r = self._request("GET", "/messages?page=1", token=account.account_id)
            return {str(m["id"]) for m in r.json().get("hydra:member", [])}
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
        from datetime import datetime
        import re

        seen = set(before_ids or [])
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }
        otp_sent_at = kwargs.get("otp_sent_at")

        def _parse_message_timestamp(*values) -> Optional[float]:
            for value in values:
                if value in (None, ""):
                    continue
                if isinstance(value, (int, float)):
                    numeric = float(value)
                    return numeric / 1000 if numeric > 10_000_000_000 else numeric
                text = str(value).strip()
                if not text:
                    continue
                try:
                    numeric = float(text)
                    return numeric / 1000 if numeric > 10_000_000_000 else numeric
                except (TypeError, ValueError):
                    pass
                try:
                    normalized = text.replace("Z", "+00:00")
                    return datetime.fromisoformat(normalized).timestamp()
                except ValueError:
                    continue
            return None

        def poll_once() -> Optional[str]:
            try:
                r = self._request("GET", "/messages?page=1", token=account.account_id)
                msgs = r.json().get("hydra:member", [])
                for msg in msgs:
                    mid = str(msg.get("id") or msg.get("msgid") or "")
                    if mid in seen:
                        continue
                    seen.add(mid)
                    # Request email details to get complete text
                    try:
                        r2 = self._request(
                            "GET", f"/messages/{mid}", token=account.account_id
                        )
                        detail = r2.json()
                        body = (
                            str(detail.get("text") or "")
                            + " "
                            + str(detail.get("subject") or "")
                        )
                    except Exception:
                        detail = {}
                        body = str(msg.get("subject") or "")
                    message_ts = _parse_message_timestamp(
                        detail.get("createdAt"),
                        detail.get("created_at"),
                        detail.get("receivedAt"),
                        detail.get("received_at"),
                        detail.get("date"),
                        detail.get("created"),
                        msg.get("createdAt"),
                        msg.get("created_at"),
                        msg.get("receivedAt"),
                        msg.get("received_at"),
                        msg.get("date"),
                        msg.get("created"),
                    )
                    if otp_sent_at and message_ts and message_ts < float(otp_sent_at):
                        continue
                    body = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "", body
                    )
                    code = self._safe_extract(body, code_pattern)
                    if code and code in exclude_codes:
                        continue
                    if code:
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class MaliAPIMailbox(BaseMailbox):
    """YYDS Mail / MaliAPI Temporary email service"""

    def __init__(
        self,
        api_url: str = "https://maliapi.215.im/v1",
        api_key: str = "",
        domain: str = "",
        auto_domain_strategy: str = "",
        proxy: str = None,
    ):
        self.api = (api_url or "https://maliapi.215.im/v1").rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.domain = str(domain or "").strip()
        self.auto_domain_strategy = str(auto_domain_strategy or "").strip()
        self.proxy = build_requests_proxy_config(proxy)
        self._email = None
        self._temp_token = None

    def _headers(self, bearer: str = "") -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict = None,
        params: dict = None,
        bearer: str = "",
    ) -> Any:
        import requests

        response = requests.request(
            method,
            f"{self.api}{path}",
            headers=self._headers(bearer),
            json=json_body,
            params=params,
            proxies=self.proxy,
            timeout=15,
        )
        try:
            payload = response.json()
        except Exception:
            payload = {}

        if response.status_code >= 400:
            error = response.text or f"HTTP {response.status_code}"
            error_code = ""
            if isinstance(payload, dict):
                error = str(payload.get("error") or error).strip()
                error_code = str(payload.get("errorCode") or "").strip()
            if error_code:
                raise RuntimeError(f"MaliAPI Request failed: {error} ({error_code})")
            raise RuntimeError(f"MaliAPI Request failed: {str(error).strip()}")

        if isinstance(payload, dict):
            if payload.get("success") is False:
                error = str(payload.get("error") or "unknown error").strip()
                error_code = str(payload.get("errorCode") or "").strip()
                if error_code:
                    raise RuntimeError(f"MaliAPI Request failed: {error} ({error_code})")
                raise RuntimeError(f"MaliAPI Request failed: {error}")
            if "data" in payload:
                return payload.get("data")
        return payload

    def _ensure_api_key(self) -> None:
        if not self.api_key:
            raise RuntimeError("MaliAPI Not configured: Please fill in the global settings maliapi_api_key")

    def _list_messages(self, account: MailboxAccount) -> list[dict]:
        data = self._request("GET", "/messages", params={"address": account.email})
        if isinstance(data, dict):
            messages = data.get("messages", [])
        else:
            messages = data
        return [item for item in (messages or []) if isinstance(item, dict)]

    def _get_message_detail(self, message_id: str) -> dict:
        data = self._request("GET", f"/messages/{message_id}")
        if isinstance(data, dict) and isinstance(data.get("message"), dict):
            return data["message"]
        return data if isinstance(data, dict) else {}

    def get_email(self) -> MailboxAccount:
        self._ensure_api_key()
        body = {}
        if self.domain:
            body["domain"] = self.domain
        if self.auto_domain_strategy:
            body["autoDomainStrategy"] = self.auto_domain_strategy

        data = self._request("POST", "/accounts", json_body=body)
        if not isinstance(data, dict):
            raise RuntimeError(f"MaliAPI Return exception: {data}")

        email = str(data.get("address") or data.get("email") or "").strip()
        temp_token = str(
            data.get("tempToken") or data.get("temp_token") or data.get("token") or ""
        ).strip()
        inbox_id = str(data.get("id") or "").strip()
        if not email:
            raise RuntimeError(f"MaliAPI Return empty mailbox: {data}")

        self._email = email
        self._temp_token = temp_token
        self._log(f"[MaliAPI] Generate mailbox: {email}")
        return MailboxAccount(
            email=email,
            account_id=temp_token or inbox_id or email,
            extra={
                "provider": "maliapi",
                "temp_token": temp_token,
                "inbox_id": inbox_id,
            },
        )

    def get_current_ids(self, account: MailboxAccount) -> set:
        self._ensure_api_key()
        try:
            return {
                str(message.get("id"))
                for message in self._list_messages(account)
                if message.get("id") is not None
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
        import re

        self._ensure_api_key()
        seen = {str(mid) for mid in (before_ids or set())}

        def poll_once() -> Optional[str]:
            try:
                for message in self._list_messages(account):
                    message_id = str(message.get("id") or "").strip()
                    if not message_id or message_id in seen:
                        continue
                    seen.add(message_id)

                    try:
                        detail = self._get_message_detail(message_id)
                    except Exception:
                        detail = message

                    search_text = " ".join(
                        [
                            str(detail.get("subject") or message.get("subject") or ""),
                            str(detail.get("text") or ""),
                            str(detail.get("html") or ""),
                            str(message.get("subject") or ""),
                            str(message.get("snippet") or ""),
                        ]
                    ).strip()
                    search_text = self._yyds_decode_raw_content(search_text) or search_text
                    search_text = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        "",
                        search_text,
                    )
                    if keyword and keyword.lower() not in search_text.lower():
                        continue

                    code = self._yyds_safe_extract(search_text, code_pattern)
                    if code:
                        self._log(f"[MaliAPI] Receive verification code: {code}")
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class GPTMailMailbox(BaseMailbox):
    """GPTMail Temporary email service"""

    def __init__(
        self,
        api_url: str = "https://mail.chatgpt.org.uk",
        api_key: str = "",
        domain: str = "",
        proxy: str = None,
    ):
        self.api = (api_url or "https://mail.chatgpt.org.uk").rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.domain = self._normalize_domain(domain)
        self.proxy = build_requests_proxy_config(proxy)
        self._email = None

    @staticmethod
    def _normalize_domain(value: Any) -> str:
        domain = str(value or "").strip().lower()
        if domain.startswith("@"):
            domain = domain[1:]
        return domain

    @staticmethod
    def _generate_local_part() -> str:
        import string

        prefix = "".join(random.choices(string.ascii_lowercase, k=6))
        suffix = "".join(random.choices(string.digits, k=4))
        return f"{prefix}{suffix}"

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        timeout: int = 15,
    ) -> Any:
        import requests

        response = requests.request(
            method,
            f"{self.api}{path}",
            params=params,
            json=json_body,
            headers=self._headers(),
            proxies=self.proxy,
            timeout=timeout,
        )
        try:
            payload = response.json()
        except Exception as exc:
            preview = (response.text or "")[:200]
            raise RuntimeError(
                f"GPTMail API {path} Return non JSON: HTTP {response.status_code} {preview}"
            ) from exc

        if response.status_code >= 400:
            error = payload.get("error") if isinstance(payload, dict) else ""
            message = str(error or response.text or f"HTTP {response.status_code}").strip()
            raise RuntimeError(f"GPTMail API {path} fail: {message}")

        if isinstance(payload, dict) and payload.get("success") is False:
            error = str(payload.get("error") or "unknown error").strip()
            raise RuntimeError(f"GPTMail API {path} fail: {error}")

        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    def _list_messages(self, email: str) -> list[dict]:
        data = self._request_json("GET", "/api/emails", params={"email": email}, timeout=10)
        if isinstance(data, dict):
            messages = data.get("emails", [])
        else:
            messages = data
        return [item for item in (messages or []) if isinstance(item, dict)]

    def _get_message_detail(self, message_id: str) -> dict[str, Any]:
        data = self._request_json("GET", f"/api/email/{message_id}", timeout=10)
        return data if isinstance(data, dict) else {}

    def get_email(self) -> MailboxAccount:
        if self.domain:
            email = f"{self._generate_local_part()}@{self.domain}"
            self._email = email
            self._log(f"[GPTMail] Local assembled mailbox: {email}")
            return MailboxAccount(
                email=email,
                account_id=email,
                extra={"provider": "gptmail", "domain": self.domain, "local_address": True},
            )

        data = self._request_json("GET", "/api/generate-email")
        if not isinstance(data, dict):
            raise RuntimeError(f"GPTMail Return exception: {data}")

        email = str(data.get("email") or "").strip()
        if not email:
            raise RuntimeError(f"GPTMail Return empty mailbox: {data}")

        self._email = email
        self._log(f"[GPTMail] Generate mailbox: {email}")
        return MailboxAccount(
            email=email,
            account_id=email,
            extra={"provider": "gptmail"},
        )

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            return {
                str(message.get("id"))
                for message in self._list_messages(account.email)
                if message.get("id") is not None
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
        import re

        seen = {str(mid) for mid in (before_ids or set())}
        exclude_codes = {
            str(code) for code in (kwargs.get("exclude_codes") or set()) if code
        }

        def poll_once() -> Optional[str]:
            try:
                messages = self._list_messages(account.email)
                self._log(f"[GPTMail] Poll: {len(messages)} total messages in mailbox")
                
                new_count = 0
                for message in messages:
                    message_id = str(message.get("id") or "").strip()
                    if not message_id or message_id in seen:
                        continue
                    seen.add(message_id)
                    new_count += 1
                    
                    subject = str(message.get("subject") or "")
                    from_addr = str(message.get("from_address") or "")
                    self._log(f"[GPTMail] New email #{new_count}: from={from_addr[:50]} subject='{subject[:60]}'")

                    try:
                        detail = self._get_message_detail(message_id)
                    except Exception:
                        detail = {}

                    search_text = " ".join(
                        [
                            str(message.get("subject") or ""),
                            str(message.get("from_address") or ""),
                            str(message.get("content") or ""),
                            str(message.get("html_content") or ""),
                            str(detail.get("subject") or ""),
                            str(detail.get("content") or ""),
                            str(detail.get("html_content") or ""),
                            str(detail.get("raw_headers") or ""),
                        ]
                    ).strip()
                    search_text = self._decode_raw_content(search_text) or search_text
                    search_text = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        "",
                        search_text,
                    )
                    
                    if keyword and keyword.lower() not in search_text.lower():
                        self._log(f"[GPTMail] Email #{new_count} doesn't match keyword '{keyword}'")
                        continue

                    code = self._safe_extract(search_text, code_pattern)
                    if code and code in exclude_codes:
                        self._log(f"[GPTMail] Email #{new_count} code {code} already used, skipping")
                        continue
                    if code:
                        self._log(f"[GPTMail] Extracted code from email #{new_count}: {code}")
                        return code
                    else:
                        self._log(f"[GPTMail] Email #{new_count} no code found in content")
                        
                if new_count == 0:
                    self._log(f"[GPTMail] Poll: no new emails")
            except Exception as e:
                self._log(f"[GPTMail] Poll error: {e}")
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class OpenTrashMailMailbox(BaseMailbox):
    """OpenTrashMail Temporary email service"""

    def __init__(
        self,
        api_url: str = "",
        domain: str = "",
        password: str = "",
        proxy: str = None,
    ):
        self.api = str(api_url or "").strip().rstrip("/")
        self.domain = self._normalize_domain(domain)
        self.password = str(password or "").strip()
        self.proxy = build_requests_proxy_config(proxy)

    @staticmethod
    def _normalize_domain(value: Any) -> str:
        domain = str(value or "").strip().lower()
        if domain.startswith("@"):
            domain = domain[1:]
        return domain

    @staticmethod
    def _generate_local_part() -> str:
        import string

        prefix = "".join(random.choices(string.ascii_lowercase, k=8))
        suffix = "".join(random.choices(string.digits, k=2))
        return f"{prefix}{suffix}"

    def _headers(self) -> dict[str, str]:
        return {"accept": "application/json, text/plain, */*"}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        timeout: int = 15,
    ):
        import requests

        request_params = dict(params or {})
        if self.password and "password" not in request_params:
            request_params["password"] = self.password

        return requests.request(
            method,
            f"{self.api}{path}",
            params=request_params or None,
            json=None,
            headers=self._headers(),
            proxies=self.proxy,
            timeout=timeout,
        )

    def _require_api(self) -> None:
        if not self.api:
            raise RuntimeError(
                "OpenTrashMail Not configured API URL,Check, please opentrashmail_api_url"
            )

    def _build_email_path(self, email: str) -> str:
        from urllib.parse import quote

        return quote(str(email or "").strip(), safe="@")

    def _parse_random_email(self, html_text: str) -> str:
        import re

        text = str(html_text or "")
        if not text:
            return ""

        match = re.search(r"/address/([^\"'<>\s]+@[^\"'<>\s]+)", text, re.IGNORECASE)
        if match:
            return str(match.group(1) or "").strip()

        match = re.search(
            r"([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})",
            text,
            re.IGNORECASE,
        )
        if match:
            return str(match.group(1) or "").strip()
        return ""

    def _list_messages(self, email: str) -> list[dict[str, Any]]:
        self._require_api()
        response = self._request(
            "GET",
            f"/json/{self._build_email_path(email)}",
            timeout=10,
        )
        if response.status_code == 404:
            return []
        try:
            payload = response.json()
        except Exception as exc:
            preview = (response.text or "")[:200]
            raise RuntimeError(
                f"OpenTrashMail Inbox returns non JSON: HTTP {response.status_code} {preview}"
            ) from exc

        if response.status_code >= 400:
            if isinstance(payload, dict) and payload.get("error"):
                error = payload.get("error")
            else:
                error = response.text or f"HTTP {response.status_code}"
            raise RuntimeError(f"OpenTrashMail Inbox query failed: {str(error).strip()}")

        if not payload:
            return []

        messages: list[dict[str, Any]] = []
        if isinstance(payload, dict):
            for message_id, item in payload.items():
                if not isinstance(item, dict):
                    continue
                message = dict(item)
                message.setdefault("id", str(message_id))
                messages.append(message)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict):
                    messages.append(item)
        return messages

    def _get_message_detail(self, email: str, message_id: str) -> dict[str, Any]:
        self._require_api()
        response = self._request(
            "GET",
            f"/json/{self._build_email_path(email)}/{message_id}",
            timeout=10,
        )
        if response.status_code == 404:
            return {}
        try:
            payload = response.json()
        except Exception as exc:
            preview = (response.text or "")[:200]
            raise RuntimeError(
                f"OpenTrashMail Email details return non JSON: HTTP {response.status_code} {preview}"
            ) from exc

        if response.status_code >= 400:
            if isinstance(payload, dict) and payload.get("error"):
                error = payload.get("error")
            else:
                error = response.text or f"HTTP {response.status_code}"
            raise RuntimeError(f"OpenTrashMail Email details query failed: {str(error).strip()}")

        return payload if isinstance(payload, dict) else {}

    def get_email(self) -> MailboxAccount:
        if self.domain:
            email = f"{self._generate_local_part()}@{self.domain}"
            self._log(f"[OpenTrashMail] Local assembled mailbox: {email}")
            return MailboxAccount(
                email=email,
                account_id=email,
                extra={
                    "provider": "opentrashmail",
                    "domain": self.domain,
                    "local_address": True,
                },
            )

        self._require_api()
        response = self._request("GET", "/api/random", timeout=15)
        if response.status_code >= 400:
            raise RuntimeError(
                f"OpenTrashMail Random mailbox generation failed: HTTP {response.status_code}"
            )

        email = self._parse_random_email(response.text)
        if not email:
            preview = (response.text or "")[:200]
            raise RuntimeError(f"OpenTrashMail Unable to parse random mailbox: {preview}")

        self._log(f"[OpenTrashMail] Generate mailbox: {email}")
        return MailboxAccount(
            email=email,
            account_id=email,
            extra={"provider": "opentrashmail"},
        )

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            return {
                str(message.get("id"))
                for message in self._list_messages(account.email)
                if message.get("id") is not None
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
        import re

        seen = {str(mid) for mid in (before_ids or set())}
        exclude_codes = {
            str(code) for code in (kwargs.get("exclude_codes") or set()) if code
        }

        def poll_once() -> Optional[str]:
            try:
                messages = self._list_messages(account.email)
                for message in messages:
                    message_id = str(message.get("id") or "").strip()
                    if not message_id or message_id in seen:
                        continue
                    seen.add(message_id)

                    detail = self._get_message_detail(account.email, message_id)
                    parsed = detail.get("parsed") if isinstance(detail, dict) else {}
                    if not isinstance(parsed, dict):
                        parsed = {}

                    decoded_raw = self._decode_raw_content(detail.get("raw") or "")
                    search_text = " ".join(
                        [
                            str(message.get("subject") or ""),
                            str(message.get("from") or ""),
                            str(message.get("body") or ""),
                            str(detail.get("from") or ""),
                            str(parsed.get("subject") or ""),
                            str(parsed.get("body") or ""),
                            str(parsed.get("htmlbody") or ""),
                            decoded_raw,
                        ]
                    ).strip()
                    search_text = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        "",
                        search_text,
                    )
                    if keyword and keyword.lower() not in search_text.lower():
                        continue

                    code = self._safe_extract(search_text, code_pattern)
                    if code and code in exclude_codes:
                        continue
                    if code:
                        self._log(f"[OpenTrashMail] Receive verification code: {code}")
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class CFWorkerMailbox(BaseMailbox):
    """Cloudflare Worker Self-built temporary mailbox service"""

    def __init__(
        self,
        api_url: str,
        admin_token: str = "",
        domain: str = "",
        domain_override: str = "",
        domains: Any = None,
        enabled_domains: Any = None,
        subdomain: str = "",
        domain_level_count: Any = 2,
        random_subdomain: Any = False,
        random_name_subdomain: Any = False,
        fingerprint: str = "",
        custom_auth: str = "",
        proxy: str = None,
    ):
        self.api = api_url.rstrip("/")
        self.admin_token = admin_token
        self.domain = self._normalize_domain(domain)
        self.domain_override = self._normalize_domain(domain_override)
        self.domains = self._parse_domains(domains)
        raw_enabled_domains = self._parse_domains(enabled_domains)
        if self.domains:
            allowed = set(self.domains)
            self.enabled_domains = [d for d in raw_enabled_domains if d in allowed]
        else:
            self.enabled_domains = raw_enabled_domains
        self.subdomain = self._normalize_subdomain(subdomain)
        self.domain_level_count = self._parse_domain_level_count(domain_level_count)
        self.random_subdomain = self._to_bool(random_subdomain)
        self.random_name_subdomain = self._to_bool(random_name_subdomain)
        self.fingerprint = fingerprint
        self.custom_auth = custom_auth
        self.proxy = build_requests_proxy_config(proxy)
        self._token = None

    def _headers(self) -> dict:
        h = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "x-admin-auth": self.admin_token,
        }
        if self.fingerprint:
            h["x-fingerprint"] = self.fingerprint
        if self.custom_auth:
            h["x-custom-auth"] = self.custom_auth
        return h

    def _ensure_api_configured(self) -> None:
        if not self.api:
            raise RuntimeError("CF Worker API URL Not configured")

    def _read_json(self, response, action: str):
        try:
            return response.json()
        except Exception:
            body = (response.text or "").strip()
            snippet = body[:200] if body else "<empty>"
            raise RuntimeError(
                f"CF Worker {action} Return non JSON response: HTTP {response.status_code}, body={snippet}"
            )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        payload: Optional[dict] = None,
        timeout: int = 15,
    ):
        import requests

        url = f"{self.api}{path}"
        response = requests.request(
            method,
            url,
            params=params,
            json=payload,
            headers=self._headers(),
            proxies=self.proxy,
            timeout=timeout,
        )
        body = (response.text or "").strip()
        preview = body[:200] or "<empty>"

        if response.status_code >= 400:
            if "private site password" in body.lower():
                raise RuntimeError(
                    "CFWorker API Private site password is required, please configure cfworker_custom_auth"
                )
            raise RuntimeError(
                f"CFWorker API {path} fail: HTTP {response.status_code} {preview}"
            )

        try:
            return response.json()
        except Exception as e:
            raise RuntimeError(
                f"CFWorker API {path} Return non JSON: HTTP {response.status_code} {preview}"
            ) from e

    def _generate_local_part(self) -> str:
        import string

        # Avoid starting with pure numbers and improve email format“like real people”degree
        prefix = "".join(random.choices(string.ascii_lowercase, k=6))
        suffix = "".join(random.choices(string.digits, k=4))
        return f"{prefix}{suffix}"

    @staticmethod
    def _normalize_domain(domain: Any) -> str:
        value = str(domain or "").strip().lower()
        if value.startswith("@"):
            value = value[1:]
        return value

    @staticmethod
    def _normalize_subdomain(value: Any) -> str:
        sub = str(value or "").strip().lower().strip(".")
        if sub.startswith("@"):
            sub = sub[1:]
        parts = [part for part in sub.split(".") if part]
        return ".".join(parts)

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "on"}

    @staticmethod
    def _parse_domain_level_count(value: Any) -> int:
        try:
            parsed = int(str(value or "").strip() or "2")
        except (TypeError, ValueError):
            return 2
        return parsed if parsed >= 2 else 2

    @classmethod
    def _parse_domains(cls, value: Any) -> list[str]:
        if not value:
            return []

        items: list[Any]
        if isinstance(value, (list, tuple, set)):
            items = list(value)
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [
                    part for chunk in text.splitlines() for part in chunk.split(",")
                ]
        else:
            items = [value]

        domains: list[str] = []
        seen = set()
        for item in items:
            domain = cls._normalize_domain(item)
            if not domain or domain in seen:
                continue
            seen.add(domain)
            domains.append(domain)
        return domains

    def _pick_domain(self) -> str:
        if self.domain_override:
            return self.domain_override
        if self.enabled_domains:
            return random.choice(self.enabled_domains)
        return self.domain

    def _generate_subdomain_label(self, length: int = 6) -> str:
        import string

        alphabet = string.ascii_lowercase + string.digits
        return "".join(random.choices(alphabet, k=length))

    def _compose_domain(self, base_domain: str) -> str:
        domain = self._normalize_domain(base_domain)
        if not domain:
            return ""

        sub_parts: list[str] = []
        if self.random_name_subdomain:
            try:
                import names
                import random

                name_func = random.choice([names.get_first_name, names.get_last_name])
                sub_parts.append(name_func().lower().replace(" ", ""))
            except ImportError:
                sub_parts.append(self._generate_subdomain_label())
        elif self.random_subdomain:
            sub_parts.append(self._generate_subdomain_label())
        if self.subdomain:
            sub_parts.append(self.subdomain)

        base_level_count = len([part for part in domain.split(".") if part])
        expected_total_levels = max(self.domain_level_count, 2)
        missing_levels = max(expected_total_levels - (base_level_count + len(sub_parts)), 0)
        if missing_levels > 0:
            fillers = [self._generate_subdomain_label() for _ in range(missing_levels)]
            sub_parts = fillers + sub_parts

        if not sub_parts:
            return domain
        return f"{'.'.join(sub_parts)}.{domain}"

    def get_email(self) -> MailboxAccount:
        self._ensure_api_configured()
        name = self._generate_local_part()
        payload = {"enablePrefix": True, "name": name}
        selected_domain = self._compose_domain(self._pick_domain())
        if selected_domain:
            payload["domain"] = selected_domain
            self._log(f"[CFWorker] Domain name used this time: {selected_domain}")
        data = self._request_json(
            "POST", "/admin/new_address", payload=payload, timeout=15
        )
        email = data.get("email", data.get("address", ""))
        token = data.get("token", data.get("jwt", ""))
        if not email or not token:
            raise RuntimeError(
                f"CFWorker API /admin/new_address Return missing email/jwt: {data}"
            )
        self._token = token
        print(
            f"[CFWorker] Generate mailbox: {email} token={token[:40] if token else 'NONE'}..."
        )
        return MailboxAccount(
            email=email,
            account_id=token,
            extra={"cfworker_domain": selected_domain} if selected_domain else None,
        )

    def _get_mails(self, email: str) -> list:
        self._ensure_api_configured()
        data = self._request_json(
            "GET",
            "/admin/mails",
            params={"limit": 20, "offset": 0, "address": email},
            timeout=10,
        )
        return data.get("results", data) if isinstance(data, dict) else data

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            mails = self._get_mails(account.email)
            return {str(m.get("id", "")) for m in mails}
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
        import re
        from datetime import datetime, timezone

        seen = set(before_ids or [])
        exclude_codes = set(kwargs.get("exclude_codes") or [])
        otp_sent_at = kwargs.get("otp_sent_at")
        otp_cutoff = float(otp_sent_at) - 2 if otp_sent_at else None

        def poll_once() -> Optional[str]:
            try:
                mails = self._get_mails(account.email)
                for mail in sorted(mails, key=lambda x: x.get("id", 0), reverse=True):
                    mid = str(mail.get("id", ""))
                    if not mid or mid in seen:
                        continue

                    created_at = str(mail.get("created_at", "") or "").strip()
                    if otp_cutoff and created_at:
                        try:
                            mail_ts = (
                                datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                                .replace(tzinfo=timezone.utc)
                                .timestamp()
                            )
                            if mail_ts < otp_cutoff:
                                self._log(
                                    f"[CFWorker] \u8df3\u8fc7\u65e7\u90ae\u4ef6 id={mid} created_at={created_at}"
                                )
                                continue
                        except Exception:
                            pass

                    # Only mark it as processed after passing time boundary filtering to avoid boundary emails being added prematurely seen.
                    seen.add(mid)

                    raw = str(mail.get("raw", ""))
                    subject = str(mail.get("subject", ""))
                    search_text = f"{subject} {self._decode_raw_content(raw)}".strip()
                    search_text = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        "",
                        search_text,
                    )
                    search_text = re.sub(r"m=\+\d+\.\d+", "", search_text)
                    search_text = re.sub(r"\bt=\d+\b", "", search_text)
                    if keyword and keyword.lower() not in search_text.lower():
                        continue

                    code = self._safe_extract(search_text, code_pattern)
                    if code and code in exclude_codes:
                        self._log(
                            f"[CFWorker] \u8df3\u8fc7\u5df2\u7528\u9a8c\u8bc1\u7801 id={mid} created_at={created_at} code={code}"
                        )
                        continue
                    if code:
                        self._log(
                            f"[CFWorker] \u547d\u4e2d\u65b0\u9a8c\u8bc1\u7801 id={mid} created_at={created_at} code={code}"
                        )
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
            timeout_message=f"\u7b49\u5f85\u9a8c\u8bc1\u7801\u8d85\u65f6 ({timeout}s)",
        )


class MoeMailMailbox(BaseMailbox):
    """MoeMail (sall.cc) Email service - Automatically register an account and generate a temporary email"""

    def __init__(
        self, api_url: str = "https://sall.cc", api_key: str = "", proxy: str = None
    ):
        self.api = api_url.rstrip("/")
        self.api_key = str(api_key or "").strip()
        self.proxy = build_requests_proxy_config(proxy)
        self._session_token = None
        self._email = None

    def _api_headers(self) -> dict:
        if not self.api_key:
            return {}
        return {"X-API-Key": self.api_key}

    def _register_and_login(self) -> str:
        import requests, random, string

        s = requests.Session()
        s.proxies = self.proxy
        ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        s.headers.update(
            {"user-agent": ua, "origin": self.api, "referer": f"{self.api}/zh-CN/login"}
        )
        s.headers.update(self._api_headers())
        # register
        username = "".join(random.choices(string.ascii_lowercase + string.digits, k=12))
        password = "Test" + "".join(random.choices(string.digits, k=8)) + "!"
        print(f"[MoeMail] Register an account: {username} / {password}")
        r_reg = s.post(
            f"{self.api}/api/auth/register",
            json={"username": username, "password": password, "turnstileToken": ""},
            timeout=15,
        )
        print(f"[MoeMail] Registration results: {r_reg.status_code} {r_reg.text[:80]}")
        # get CSRF
        csrf_r = s.get(f"{self.api}/api/auth/csrf", timeout=10)
        csrf = csrf_r.json().get("csrfToken", "")
        # Log in
        s.post(
            f"{self.api}/api/auth/callback/credentials",
            headers={"content-type": "application/x-www-form-urlencoded"},
            data=f"username={username}&password={password}&csrfToken={csrf}&redirect=false&callbackUrl={self.api}",
            allow_redirects=True,
            timeout=15,
        )
        self._session = s
        for cookie in s.cookies:
            if "session-token" in cookie.name:
                self._session_token = cookie.value
                print(f"[MoeMail] Login successful")
                return cookie.value
        print(f"[MoeMail] Login failed,cookies: {[c.name for c in s.cookies]}")
        return ""

    def get_email(self) -> MailboxAccount:
        # Register a new account every time you call to ensure a unique email address
        self._session_token = None
        self._register_and_login()
        import random, string

        name = "".join(random.choices(string.ascii_letters + string.digits, k=8))
        # Get a list of available domain names and randomly select one
        domain = "sall.cc"
        try:
            cfg_r = self._session.get(
                f"{self.api}/api/config", headers=self._api_headers(), timeout=10
            )
            domains = [
                d.strip()
                for d in cfg_r.json().get("emailDomains", "sall.cc").split(",")
                if d.strip()
            ]
            if domains:
                domain = random.choice(domains)
        except Exception:
            pass
        r = self._session.post(
            f"{self.api}/api/emails/generate",
            headers=self._api_headers(),
            json={"name": name, "domain": domain, "expiryTime": 86400000},
            timeout=15,
        )
        data = r.json()
        self._email = data.get("email", data.get("address", ""))
        email_id = data.get("id", "")
        print(
            f"[MoeMail] Generate mailbox: {self._email} id={email_id} domain={domain} status={r.status_code}"
        )
        if not email_id:
            print(f"[MoeMail] Build failed: {data}")
        if email_id:
            self._email_count = getattr(self, "_email_count", 0) + 1
        return MailboxAccount(email=self._email, account_id=str(email_id))

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            r = self._session.get(
                f"{self.api}/api/emails/{account.account_id}",
                headers=self._api_headers(),
                timeout=10,
            )
            return {str(m.get("id", "")) for m in r.json().get("messages", [])}
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
        import re

        seen = set(before_ids or [])

        def poll_once() -> Optional[str]:
            try:
                r = self._session.get(
                    f"{self.api}/api/emails/{account.account_id}",
                    headers=self._api_headers(),
                    timeout=10,
                )
                msgs = r.json().get("messages", [])
                for msg in msgs:
                    mid = str(msg.get("id", ""))
                    if not mid or mid in seen:
                        continue
                    seen.add(mid)
                    body = (
                        str(
                            msg.get("content")
                            or msg.get("text")
                            or msg.get("body")
                            or msg.get("html")
                            or ""
                        )
                        + " "
                        + str(msg.get("subject") or "")
                    )
                    body = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "", body
                    )
                    code = self._safe_extract(body, code_pattern)
                    if code:
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class LuckMailMailbox(BaseMailbox):
    """LuckMail Blending mode:ChatGPT Use the purchase email address, and use the order receiving code on other platforms."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        project_code: str = "",
        email_type: str = "",
        domain: str = "",
        proxy: str = None,
    ):
        if not base_url or not api_key:
            raise RuntimeError(
                "LuckMail Not configured: Please fill in the global settings luckmail_base_url and luckmail_api_key"
            )
        from .luckmail import LuckMailClient

        self._client = LuckMailClient(
            base_url=base_url,
            api_key=api_key,
            proxy_url=proxy,
        )
        self._project_code = project_code
        self._email_type = email_type or None
        self._domain = domain or None
        self._order_no = None
        self._token = None
        self._email = None

    def _use_purchase_mode(self, account: MailboxAccount = None) -> bool:
        if (
            account
            and account.account_id
            and str(account.account_id).startswith("tok_")
        ):
            return True
        if self._token:
            return True
        return self._project_code == "openai"

    def _resolve_token(self, account: MailboxAccount = None) -> str:
        token = (account.account_id if account else "") or self._token
        if token:
            self._token = token
            return token

        email = (account.email if account else "") or self._email
        if not email:
            return ""

        try:
            purchases = self._client.user.get_purchases(
                page=1,
                page_size=100,
                keyword=email,
            )
        except Exception:
            return ""

        email_lower = str(email).strip().lower()
        for item in purchases.list:
            if str(item.email_address).strip().lower() == email_lower and item.token:
                self._token = item.token
                self._email = item.email_address
                return item.token
        return ""

    def _cancel_order_silently(self, order_no: str) -> None:
        if not order_no:
            return
        try:
            self._client.user.cancel_order(order_no)
            self._log(f"[LuckMail] Order canceled: {order_no}")
        except Exception:
            pass

    def _extract_code_from_token_mails(
        self,
        token: str,
        code_pattern: str = None,
        before_ids: set = None,
        exclude_codes: set = None,
    ) -> Optional[str]:
        try:
            mail_list = self._client.user.get_token_mails(token)
        except Exception:
            return None

        seen = {str(mid) for mid in (before_ids or set())}
        excluded = {str(code) for code in (exclude_codes or set()) if code}
        for mail in mail_list.mails:
            message_id = str(mail.message_id or "")
            if message_id and message_id in seen:
                continue
            body = " ".join(
                [
                    str(mail.subject or ""),
                    str(mail.body or ""),
                    str(mail.html_body or ""),
                ]
            )
            code = self._safe_extract(body, code_pattern)
            if code and code in excluded:
                continue
            if code:
                return code
        return None

    def get_email(self) -> MailboxAccount:
        if not self._project_code:
            raise RuntimeError("LuckMail not set project_code, unable to create mailbox")

        if self._use_purchase_mode():
            self._log(
                f"[LuckMail] branch: ChatGPT + LuckMail -> Purchase email interface "
                f"(project_code={self._project_code}, email_type={self._email_type or '-'}, domain={self._domain or '-'})"
            )
            try:
                result = self._client.user.purchase_emails(
                    project_code=self._project_code,
                    quantity=1,
                    email_type=self._email_type,
                    domain=self._domain,
                )
            except Exception as e:
                raise RuntimeError(f"LuckMail Failed to purchase email address: {e}") from e

            purchases = (result or {}).get("purchases") or []
            if not purchases:
                raise RuntimeError(f"LuckMail Purchase email returned empty: {result}")

            item = purchases[0]
            email = str(item.get("email_address") or "").strip()
            token = str(item.get("token") or "").strip()
            if not email or not token:
                raise RuntimeError(f"LuckMail Return missing email/token: {item}")

            self._email = email
            self._token = token
            self._log(f"[LuckMail] Purchased email address: {email}")
            if item.get("warranty_until"):
                self._log(f"[LuckMail] Warranty expired: {item.get('warranty_until')}")
            return MailboxAccount(
                email=email,
                account_id=token,
                extra={
                    "provider": "luckmail",
                    "token": token,
                    "project_code": self._project_code,
                },
            )

        self._log(
            f"[LuckMail] branch: Other platforms + LuckMail -> Create order/Order receiving code "
            f"(project_code={self._project_code}, email_type={self._email_type or '-'})"
        )
        try:
            body = {"project_code": self._project_code}
            if self._email_type:
                body["email_type"] = self._email_type
            order = self._client.user._sync_create_order(body)
        except Exception as e:
            raise RuntimeError(f"LuckMail Failed to create order: {e}") from e
        self._order_no = order.order_no
        email = order.email_address
        self._email = email
        self._log(f"[LuckMail] Order {order.order_no} Assign mailbox: {email}")
        self._log(f"[LuckMail] timeout: {order.expired_at}")
        return MailboxAccount(email=email, account_id=order.order_no)

    def get_current_ids(self, account: MailboxAccount) -> set:
        if not self._use_purchase_mode(account):
            return set()
        token = self._resolve_token(account)
        if not token:
            return set()
        try:
            mail_list = self._client.user.get_token_mails(token)
            return {str(m.message_id) for m in (mail_list.mails or []) if m.message_id}
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
        if not self._use_purchase_mode(account):
            self._log("[LuckMail] Waiting for verification code branch: Order receiving code")
            order_no = account.account_id or self._order_no
            if not order_no:
                raise RuntimeError("LuckMail Order not created, unable to wait for verification code")

            def on_poll_order(result):
                self._log(f"[LuckMail] Polling... state: {result.status}")

            deadline = time.monotonic() + max(int(timeout or 0), 1)
            last_status = "pending"
            try:
                while time.monotonic() < deadline:
                    self._checkpoint()
                    remaining = max(1, int(deadline - time.monotonic()))
                    slice_timeout = min(remaining, 6)
                    try:
                        code_result = self._client.user._sync_wait_for_code(
                            order_no=order_no,
                            timeout=slice_timeout,
                            interval=3.0,
                            on_poll=on_poll_order,
                        )
                    except Exception as e:
                        raise TimeoutError(f"LuckMail Waiting for verification code failed: {e}") from e

                    last_status = str(code_result.status or "pending")
                    if code_result.status == "success" and code_result.verification_code:
                        code = code_result.verification_code
                        self._log(f"[LuckMail] Receive verification code: {code}")
                        return code
                    if code_result.status in {"cancelled", "timeout"}:
                        break
            except Exception:
                self._cancel_order_silently(order_no)
                raise

            self._cancel_order_silently(order_no)
            raise TimeoutError(
                f"LuckMail Timeout waiting for verification code ({timeout}s), the final state: {last_status}"
            )

        token = self._resolve_token(account)
        if not token:
            raise RuntimeError("LuckMail Purchased email not found Token, unable to wait for verification code")
        self._log("[LuckMail] Waiting for verification code branch: Purchased email address Token Receive code")

        exclude_codes = {
            str(code) for code in (kwargs.get("exclude_codes") or set()) if code
        }
        seen_message_ids = {str(mid) for mid in (before_ids or set()) if mid}
        if before_ids is None:
            seen_message_ids = self.get_current_ids(account)
            if seen_message_ids:
                self._log(
                    f"[LuckMail] Old email baseline has been established, skip now {len(seen_message_ids)} historical emails"
                )

        saw_new_mail = False

        def poll_once() -> Optional[str]:
            nonlocal saw_new_mail
            found_new_mail = False
            try:
                mail_list = self._client.user.get_token_mails(token)
            except Exception as e:
                raise TimeoutError(f"LuckMail Waiting for verification code failed: {e}") from e

            for mail in mail_list.mails:
                message_id = str(mail.message_id or "").strip()
                if message_id and message_id in seen_message_ids:
                    continue

                found_new_mail = True
                saw_new_mail = True
                if message_id:
                    seen_message_ids.add(message_id)

                body = " ".join(
                    [
                        str(mail.subject or ""),
                        str(mail.body or ""),
                        str(mail.html_body or ""),
                    ]
                )
                code = self._safe_extract(body, code_pattern)
                if code and code in exclude_codes:
                    self._log(
                        f"[LuckMail] Skip used verification code message_id={message_id or '-'} code={code}"
                    )
                    continue
                if code:
                    self._log(f"[LuckMail] Receive verification code: {code}")
                    return code

            self._log(
                f"[LuckMail] Polling... new mail: {'yes' if found_new_mail else 'no'}"
            )

            if found_new_mail:
                self._log("[LuckMail] The verification code is not yet available in the new email. Please wait for the next one....")
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
            timeout_message=(
                f"LuckMail Timeout waiting for verification code ({timeout}s), the final state: "
                f"has_new_mail={saw_new_mail}"
            ),
        )


class OutlookMailboxBackend(ABC):
    """Outlook Receiving backend strategy."""

    backend_name: str = ""

    def __init__(self, mailbox: "OutlookMailbox"):
        self.mailbox = mailbox

    @abstractmethod
    def get_current_ids(self, account: MailboxAccount) -> set:
        ...

    @abstractmethod
    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set | None = None,
        code_pattern: str | None = None,
        **kwargs,
    ) -> str:
        ...


class OutlookImapMailboxBackend(OutlookMailboxBackend):
    backend_name = "imap"

    def get_current_ids(self, account: MailboxAccount) -> set:
        imap_conn = None
        try:
            imap_conn = self.mailbox._open_imap(account)
            seen: set[str] = set()
            for folder in self.mailbox._imap_folder_names:
                status, _ = imap_conn.select(folder, readonly=True)
                if status != "OK":
                    continue
                status, data = imap_conn.uid("search", None, "ALL")
                if status != "OK":
                    continue
                ids = data[0].split() if data and data[0] else []
                for uid in ids[-100:]:
                    uid_str = (
                        uid.decode("utf-8", errors="ignore")
                        if isinstance(uid, bytes)
                        else str(uid)
                    )
                    if uid_str:
                        seen.add(f"{folder}:{uid_str}")
            return seen
        finally:
            try:
                if imap_conn:
                    imap_conn.logout()
            except Exception:
                pass

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set | None = None,
        code_pattern: str | None = None,
        **kwargs,
    ) -> str:
        from email import message_from_bytes
        from email.policy import default as email_default_policy

        seen = {str(mid) for mid in (before_ids or set())}
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }
        keyword_lower = str(keyword or "").strip().lower()

        def poll_once() -> Optional[str]:
            for folder in self.mailbox._imap_folder_names:
                imap_conn = None
                try:
                    self.mailbox._log(f"[Microsoft Mail][IMAP] folder={folder} Start polling")
                    imap_conn = self.mailbox._open_imap(account)
                    self.mailbox._log(f"[Microsoft Mail][IMAP] folder={folder} IMAP Login successful")
                    status, _ = imap_conn.select(folder, readonly=True)
                    if status != "OK":
                        self.mailbox._log(
                            f"[Microsoft Mail][IMAP] folder={folder} select fail: status={status}"
                        )
                        continue
                    status, data = imap_conn.uid("search", None, "ALL")
                    if status != "OK":
                        self.mailbox._log(
                            f"[Microsoft Mail][IMAP] folder={folder} search fail: status={status}"
                        )
                        continue
                    ids = data[0].split() if data and data[0] else []
                    if len(ids) > 50:
                        ids = ids[-50:]
                    new_uids = []
                    for uid in ids:
                        uid_str = (
                            uid.decode("utf-8", errors="ignore")
                            if isinstance(uid, bytes)
                            else str(uid)
                        )
                        seen_key = f"{folder}:{uid_str}"
                        if not uid_str or seen_key in seen:
                            continue
                        seen.add(seen_key)
                        new_uids.append(uid)
                    self.mailbox._log(
                        f"[Microsoft Mail][IMAP] folder={folder} uid_total={len(ids)} new_uid_count={len(new_uids)}"
                    )
                    for uid in new_uids:
                        status, msg_data = imap_conn.uid("fetch", uid, "(RFC822)")
                        if status != "OK":
                            self.mailbox._log(
                                f"[Microsoft Mail][IMAP] folder={folder} fetch fail: uid={uid!r} status={status}"
                            )
                            continue
                        raw = None
                        for item in msg_data or []:
                            if isinstance(item, tuple) and item[1]:
                                raw = item[1]
                                break
                        if not raw:
                            self.mailbox._log(
                                f"[Microsoft Mail][IMAP] folder={folder} fetch Empty response: uid={uid!r}"
                            )
                            continue
                        msg = message_from_bytes(raw, policy=email_default_policy)
                        subject = self.mailbox._decode_header_value(msg.get("Subject", ""))
                        text = self.mailbox._extract_message_text(msg)
                        self.mailbox._log(
                            f"[Microsoft Mail][IMAP] folder={folder} hit new mail subject={subject or '-'}"
                        )
                        if keyword_lower and keyword_lower not in text.lower():
                            self.mailbox._log(
                                f"[Microsoft Mail][IMAP] folder={folder} Skip emails that don’t match keywords"
                            )
                            continue
                        code = self.mailbox._safe_extract(text, code_pattern)
                        if not code:
                            self.mailbox._log(
                                f"[Microsoft Mail][IMAP] folder={folder} Verification code not retrieved"
                            )
                            continue
                        if code in exclude_codes:
                            self.mailbox._log(
                                f"[Microsoft Mail][IMAP] folder={folder} Skip attempted verification codes: {code}"
                            )
                            continue
                        self.mailbox._log(
                            f"[Microsoft Mail][IMAP] folder={folder} Verification code extraction successful: {code}"
                        )
                        return code
                except Exception as exc:
                    self.mailbox._log(
                        f"[Microsoft Mail][IMAP] folder={folder} IMAP Query exception: {exc}"
                    )
                    continue
                finally:
                    try:
                        if imap_conn:
                            imap_conn.logout()
                    except Exception:
                        pass
            return None

        return self.mailbox._run_polling_wait(
            timeout=timeout,
            poll_interval=5,
            poll_once=poll_once,
        )


class OutlookGraphMailboxBackend(OutlookMailboxBackend):
    backend_name = "graph"

    def get_current_ids(self, account: MailboxAccount) -> set:
        access_token = self.mailbox._get_oauth_access_token(
            account,
            preferred_backend=self.backend_name,
        )
        seen: set[str] = set()
        for folder in self.mailbox._graph_folder_names:
            try:
                messages = self.mailbox._graph_list_messages(
                    access_token=access_token,
                    folder=folder,
                )
                for message in messages:
                    message_id = str(message.get("id") or "").strip()
                    if message_id:
                        seen.add(f"{folder}:{message_id}")
            except RuntimeError as exc:
                if "HTTP 401" in str(exc):
                    # 401 → token Failed, force refresh and try again.
                    self.mailbox._log(
                        f"[Microsoft Mail][Graph] get_current_ids folder={folder} meet 401, force refresh token"
                    )
                    _cache = (account.extra or {}).get("_oauth_token_cache")
                    if isinstance(_cache, dict):
                        _cache.pop(
                            self.mailbox._normalize_backend_name(self.backend_name), None
                        )
                    access_token = self.mailbox._get_oauth_access_token(
                        account,
                        preferred_backend=self.backend_name,
                    )
                    try:
                        messages = self.mailbox._graph_list_messages(
                            access_token=access_token,
                            folder=folder,
                        )
                        for message in messages:
                            message_id = str(message.get("id") or "").strip()
                            if message_id:
                                seen.add(f"{folder}:{message_id}")
                    except Exception:
                        pass
                else:
                    raise
        return seen

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set | None = None,
        code_pattern: str | None = None,
        **kwargs,
    ) -> str:
        seen = {str(mid) for mid in (before_ids or set())}
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }
        keyword_lower = str(keyword or "").strip().lower()

        # Mark whether it has been done once 401 Force brush token, to avoid infinite loops
        _token_refreshed = False

        def _force_refresh_token() -> str:
            """Clear OAuth Caching, forcing re-fetching access token."""
            _cache = (account.extra or {}).get("_oauth_token_cache")
            if isinstance(_cache, dict):
                _cache.pop(
                    self.mailbox._normalize_backend_name(self.backend_name), None
                )
            return self.mailbox._get_oauth_access_token(
                account,
                preferred_backend=self.backend_name,
            )

        def poll_once() -> Optional[str]:
            nonlocal _token_refreshed
            access_token = self.mailbox._get_oauth_access_token(
                account,
                preferred_backend=self.backend_name,
            )
            for folder in self.mailbox._graph_folder_names:
                try:
                    self.mailbox._log(f"[Microsoft Mail][Graph] folder={folder} Start polling")
                    messages = self.mailbox._graph_list_messages(
                        access_token=access_token,
                        folder=folder,
                    )
                    new_messages = []
                    for message in messages:
                        message_id = str(message.get("id") or "").strip()
                        seen_key = f"{folder}:{message_id}"
                        if not message_id or seen_key in seen:
                            continue
                        seen.add(seen_key)
                        new_messages.append(message)
                    self.mailbox._log(
                        f"[Microsoft Mail][Graph] folder={folder} message_total={len(messages)} new_count={len(new_messages)}"
                    )
                    for message in new_messages:
                        subject = str(message.get("subject") or "").strip()
                        text = self.mailbox._graph_message_text(message)
                        self.mailbox._log(
                            f"[Microsoft Mail][Graph] folder={folder} hit new mail subject={subject or '-'}"
                        )
                        if keyword_lower and keyword_lower not in text.lower():
                            self.mailbox._log(
                                f"[Microsoft Mail][Graph] folder={folder} Skip emails that don’t match keywords"
                            )
                            continue
                        code = self.mailbox._safe_extract(text, code_pattern)
                        if not code:
                            message_id = str(message.get("id") or "").strip()
                            if message_id:
                                detail = self.mailbox._graph_get_message(
                                    access_token=access_token,
                                    message_id=message_id,
                                )
                                text = self.mailbox._graph_message_text(detail)
                                code = self.mailbox._safe_extract(text, code_pattern)
                        if not code:
                            self.mailbox._log(
                                f"[Microsoft Mail][Graph] folder={folder} Verification code not retrieved"
                            )
                            continue
                        if code in exclude_codes:
                            self.mailbox._log(
                                f"[Microsoft Mail][Graph] folder={folder} Skip attempted verification codes: {code}"
                            )
                            continue
                        self.mailbox._log(
                            f"[Microsoft Mail][Graph] folder={folder} Verification code extraction successful: {code}"
                        )
                        return code
                except Exception as exc:
                    exc_str = str(exc)
                    # 401 → token Failed, force refresh and try again.
                    if "HTTP 401" in exc_str and not _token_refreshed:
                        _token_refreshed = True
                        self.mailbox._log(
                            f"[Microsoft Mail][Graph] folder={folder} meet 401, force refresh token Try again later"
                        )
                        try:
                            access_token = _force_refresh_token()
                            messages = self.mailbox._graph_list_messages(
                                access_token=access_token,
                                folder=folder,
                            )
                            new_messages = []
                            for message in messages:
                                message_id = str(message.get("id") or "").strip()
                                seen_key = f"{folder}:{message_id}"
                                if not message_id or seen_key in seen:
                                    continue
                                seen.add(seen_key)
                                new_messages.append(message)
                            for message in new_messages:
                                subject = str(message.get("subject") or "").strip()
                                text = self.mailbox._graph_message_text(message)
                                if keyword_lower and keyword_lower not in text.lower():
                                    continue
                                code = self.mailbox._safe_extract(text, code_pattern)
                                if not code:
                                    mid = str(message.get("id") or "").strip()
                                    if mid:
                                        detail = self.mailbox._graph_get_message(
                                            access_token=access_token,
                                            message_id=mid,
                                        )
                                        text = self.mailbox._graph_message_text(detail)
                                        code = self.mailbox._safe_extract(text, code_pattern)
                                if code and code not in exclude_codes:
                                    self.mailbox._log(
                                        f"[Microsoft Mail][Graph] folder={folder} refresh token The verification code was extracted successfully: {code}"
                                    )
                                    return code
                        except Exception as retry_exc:
                            self.mailbox._log(
                                f"[Microsoft Mail][Graph] folder={folder} refresh token Still failed after: {retry_exc}"
                            )
                        continue
                    self.mailbox._log(
                        f"[Microsoft Mail][Graph] folder={folder} Query exception: {exc}"
                    )
                    continue
            return None

        return self.mailbox._run_polling_wait(
            timeout=timeout,
            poll_interval=5,
            poll_once=poll_once,
        )


class MailApiUrlOtpBackend(OutlookMailboxBackend):
    backend_name = "mailapi_url"

    @staticmethod
    def _code_key(code: str) -> str:
        return f"mailapi_code:{str(code or '').strip()}"

    def _fetch_mailapi_text(self, account: MailboxAccount) -> str:
        import requests

        extra = account.extra or {}
        url = str(extra.get("mailapi_url") or "").strip()
        if not url:
            raise RuntimeError("mailapi_url Empty, unable to poll for code acquisition")
        response = requests.get(
            url,
            timeout=15,
            proxies=getattr(self.mailbox, "_proxy", None),
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"MailAPI Code retrieval request failed: HTTP {response.status_code}"
            )
        return str(response.text or "")

    def _extract_code(self, text: str, code_pattern: str | None) -> str:
        normalized_text = self.mailbox._decode_raw_content(text) or str(text or "")
        return str(self.mailbox._safe_extract(normalized_text, code_pattern) or "").strip()

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            text = self._fetch_mailapi_text(account)
            code = self._extract_code(text, None)
            return {self._code_key(code)} if code else set()
        except Exception:
            return set()

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set | None = None,
        code_pattern: str | None = None,
        **kwargs,
    ) -> str:
        seen = {str(mid) for mid in (before_ids or set())}
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }
        keyword_lower = str(keyword or "").strip().lower()

        def poll_once() -> Optional[str]:
            try:
                text = self._fetch_mailapi_text(account)
            except Exception as exc:
                self.mailbox._log(f"[MailAPI] Pull failed: {exc}")
                return None

            if keyword_lower and keyword_lower not in str(text).lower():
                return None
            code = self._extract_code(text, code_pattern)
            if not code:
                return None
            if code in exclude_codes:
                self.mailbox._log(f"[MailAPI] Skip attempted verification codes: {code}")
                return None
            code_key = self._code_key(code)
            if code_key in seen:
                return None
            seen.add(code_key)
            self.mailbox._log(f"[MailAPI] Receive verification code: {code}")
            return code

        return self.mailbox._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class OutlookMailbox(BaseMailbox):
    """Microsoft Email (Outlook / Hotmail) local account pool (Graph / IMAP Strategy)"""

    # Class-level lock: ensure mutual exclusion of numbers when multiple threads are concurrent, preventing multiple instances from accessing the same mailbox
    _pop_lock = threading.Lock()

    def __init__(
        self,
        imap_server: str = "",
        imap_port: int | str = 993,
        token_endpoint: str = "",
        backend: str = "graph",
        graph_api_base: str = "",
        proxy: str = None,
    ):
        self._lock = threading.Lock()
        self._proxy = build_requests_proxy_config(proxy)
        self._imap_servers = []
        if imap_server:
            self._imap_servers.append(str(imap_server).strip())
        else:
            try:
                from platforms.chatgpt.constants import OUTLOOK_IMAP_SERVERS

                self._imap_servers.extend(
                    [
                        str(OUTLOOK_IMAP_SERVERS.get("NEW") or "").strip(),
                        str(OUTLOOK_IMAP_SERVERS.get("OLD") or "").strip(),
                    ]
                )
            except Exception:
                self._imap_servers.extend(
                    ["outlook.live.com", "outlook.office365.com"]
                )
        self._imap_servers = [
            host for host in self._imap_servers if isinstance(host, str) and host
        ]
        try:
            self._imap_port = int(imap_port or 993)
        except (TypeError, ValueError):
            self._imap_port = 993
        self._token_endpoint = str(token_endpoint or "").strip()
        self._backend_name = self._normalize_backend_name(backend)
        self._graph_api_base = (
            str(graph_api_base or "").strip() or "https://graph.microsoft.com/v1.0"
        )
        self._imap_folder_names = ["INBOX", "Junk", "Deleted Items", "Trash"]
        self._graph_folder_names = ["inbox", "junkemail", "deleteditems"]
        self._backends: dict[str, OutlookMailboxBackend] = {
            "imap": OutlookImapMailboxBackend(self),
            "graph": OutlookGraphMailboxBackend(self),
            "mailapi_url": MailApiUrlOtpBackend(self),
        }

    @staticmethod
    def _normalize_backend_name(value: Any) -> str:
        backend = str(value or "graph").strip().lower() or "graph"
        return backend if backend in {"graph", "imap"} else "graph"

    @staticmethod
    def _normalize_account_type(value: Any) -> str:
        account_type = str(value or "").strip().lower()
        if account_type in {"mailapi_url", "microsoft_oauth"}:
            return account_type
        return "microsoft_oauth"

    def _is_mailapi_account(self, account: MailboxAccount) -> bool:
        extra = getattr(account, "extra", None) or {}
        account_type = self._normalize_account_type(extra.get("account_type"))
        if account_type == "mailapi_url":
            return True
        return bool(str(extra.get("mailapi_url") or "").strip())

    def _pop_account(self) -> dict:
        from sqlmodel import Session, select
        from core.db import engine, OutlookAccountModel

        with OutlookMailbox._pop_lock:
            with Session(engine) as session:
                account = (
                    session.exec(
                        select(OutlookAccountModel)
                        .where(OutlookAccountModel.enabled == True)
                        .order_by(OutlookAccountModel.id)
                    )
                    .first()
                )
                if not account:
                    raise RuntimeError("The Microsoft email account pool is empty. Please import it in batches on the settings page first.")

                payload = {
                    "id": account.id,
                    "email": account.email,
                    "password": account.password,
                    "client_id": account.client_id,
                    "refresh_token": account.refresh_token,
                    "account_type": getattr(account, "account_type", "microsoft_oauth"),
                    "mailapi_url": getattr(account, "mailapi_url", ""),
                }
                session.delete(account)
                session.commit()
                return payload

    def get_email(self) -> MailboxAccount:
        payload = self._pop_account()
        email = str(payload.get("email") or "").strip()
        if not email:
            raise RuntimeError("Microsoft email account mailbox is empty")
        password = str(payload.get("password") or "")
        client_id = str(payload.get("client_id") or "")
        refresh_token = str(payload.get("refresh_token") or "")
        account_type = self._normalize_account_type(payload.get("account_type"))
        mailapi_url = str(payload.get("mailapi_url") or "").strip()
        auth_mode = (
            "mailapi_url"
            if account_type == "mailapi_url"
            else ("oauth" if client_id and refresh_token else "password")
        )
        self._log(f"[Microsoft Mail] Remove account: {email}(removed from local pool)")
        self._log(
            "[Microsoft Mail] Account authentication information: "
            f"has_password={bool(password)} "
            f"has_client_id={bool(client_id)} "
            f"has_refresh_token={bool(refresh_token)} "
            f"has_mailapi_url={bool(mailapi_url)} "
            f"account_type={account_type} "
            f"auth_mode={auth_mode}"
        )
        return MailboxAccount(
            email=email,
            account_id=str(payload.get("id") or ""),
            extra={
                "provider": "microsoft",
                "password": password,
                "client_id": client_id,
                "refresh_token": refresh_token,
                "account_type": account_type,
                "mailapi_url": mailapi_url,
                "outlook_backend": self._backend_name,
            },
        )

    def requeue_account(self, account: MailboxAccount) -> None:
        from sqlmodel import Session, select
        from core.db import engine, OutlookAccountModel

        email = str(getattr(account, "email", "") or "").strip()
        extra = getattr(account, "extra", None) or {}
        if not email:
            return

        password = str(extra.get("password") or "")
        client_id = str(extra.get("client_id") or "")
        refresh_token = str(extra.get("refresh_token") or "")
        account_type = self._normalize_account_type(extra.get("account_type"))
        mailapi_url = str(extra.get("mailapi_url") or "")

        with self._lock:
            with Session(engine) as session:
                existing = session.exec(
                    select(OutlookAccountModel).where(OutlookAccountModel.email == email)
                ).first()
                if existing:
                    existing.password = password
                    existing.client_id = client_id
                    existing.refresh_token = refresh_token
                    existing.account_type = account_type
                    existing.mailapi_url = mailapi_url
                    existing.enabled = True
                    existing.updated_at = _utcnow()
                    session.add(existing)
                else:
                    session.add(
                        OutlookAccountModel(
                            email=email,
                            password=password,
                            client_id=client_id,
                            refresh_token=refresh_token,
                            account_type=account_type,
                            mailapi_url=mailapi_url,
                            enabled=True,
                            created_at=_utcnow(),
                            updated_at=_utcnow(),
                        )
                    )
                session.commit()
        self._log(f"[Microsoft Mail] The account has been rolled back to the local pool: {email}")

    def _token_endpoints(self) -> list[str]:
        if self._token_endpoint:
            return [self._token_endpoint]
        try:
            from platforms.chatgpt.constants import MICROSOFT_TOKEN_ENDPOINTS

            return [
                MICROSOFT_TOKEN_ENDPOINTS.get("CONSUMERS", ""),
                MICROSOFT_TOKEN_ENDPOINTS.get("LIVE", ""),
                MICROSOFT_TOKEN_ENDPOINTS.get("COMMON", ""),
            ]
        except Exception:
            return [
                "https://login.microsoftonline.com/consumers/oauth2/v2.0/token",
                "https://login.live.com/oauth20_token.srf",
                "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            ]

    def _oauth_scope_candidates(
        self,
        preferred_backend: str | None = None,
    ) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        try:
            from platforms.chatgpt.constants import MICROSOFT_SCOPES

            scope_map = {
                "imap_new": str(MICROSOFT_SCOPES.get("IMAP_NEW") or "").strip(),
                "outlook_default": "https://outlook.office.com/.default offline_access",
                "graph_default": str(MICROSOFT_SCOPES.get("GRAPH_API") or "").strip(),
                "empty": "",
            }
        except Exception:
            scope_map = {
                "imap_new": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
                "outlook_default": "https://outlook.office.com/.default offline_access",
                "graph_default": "https://graph.microsoft.com/.default",
                "empty": "",
            }

        backend = self._normalize_backend_name(preferred_backend or self._backend_name)
        ordered_labels = (
            ["graph_default", "outlook_default", "imap_new", "empty"]
            if backend == "graph"
            else ["imap_new", "outlook_default", "graph_default", "empty"]
        )
        raw_candidates = [(label, scope_map.get(label, "")) for label in ordered_labels]

        seen = set()
        for label, scope in raw_candidates:
            key = (str(label or "").strip(), str(scope or "").strip())
            if key in seen:
                continue
            seen.add(key)
            candidates.append(key)
        return candidates

    def probe_oauth_availability(
        self,
        *,
        email: str,
        client_id: str,
        refresh_token: str,
        preferred_backend: str | None = None,
    ) -> dict[str, Any]:
        if not client_id or not refresh_token:
            self._log(
                f"[Microsoft Mail] OAuth token jump over: email={email} has_client_id={bool(client_id)} has_refresh_token={bool(refresh_token)}"
            )
            return {
                "ok": False,
                "reason": "missing_oauth_credentials",
                "message": "Lack client_id or refresh_token, unable to pass Microsoft mailbox availability check",
            }

        import requests

        last_error = ""
        for endpoint in self._token_endpoints():
            endpoint = str(endpoint or "").strip()
            if not endpoint:
                continue
            for scope_label, scope in self._oauth_scope_candidates(preferred_backend):
                payload = {
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                }
                if scope:
                    payload["scope"] = scope
                try:
                    self._log(
                        "[Microsoft Mail] OAuth token ask: "
                        f"email={email} endpoint={endpoint} scope_label={scope_label} has_scope={bool(scope)}"
                    )
                    resp = requests.post(
                        endpoint,
                        data=payload,
                        timeout=20,
                        proxies=self._proxy,
                    )
                    self._log(
                        "[Microsoft Mail] OAuth token response: "
                        f"email={email} endpoint={endpoint} scope_label={scope_label} status={resp.status_code}"
                    )
                except Exception as exc:
                    last_error = str(exc)
                    self._log(
                        "[Microsoft Mail] OAuth token Request exception: "
                        f"email={email} endpoint={endpoint} scope_label={scope_label} error={exc}"
                    )
                    continue

                body_text = str(resp.text or "")[:500]
                if resp.status_code >= 400:
                    self._log(f"[Microsoft Mail] OAuth token Failure response: {body_text[:200]}")
                    lowered = body_text.lower()
                    if "invalid_grant" in lowered and "service abuse mode" in lowered:
                        return {
                            "ok": False,
                            "reason": "service_abuse_mode",
                            "message": "Microsoft mailbox availability test failed, the account is in service abuse mode",
                            "status_code": resp.status_code,
                            "endpoint": endpoint,
                            "scope_label": scope_label,
                        }
                    last_error = body_text or f"HTTP {resp.status_code}"
                    continue

                try:
                    data = resp.json() if resp.content else {}
                    access_token = str(data.get("access_token") or "").strip()
                    if access_token:
                        expires_in = data.get("expires_in")
                        try:
                            expires_in_value = max(int(expires_in or 0), 0)
                        except (TypeError, ValueError):
                            expires_in_value = 0
                        self._log(
                            f"[Microsoft Mail] OAuth access token get success: {email} (scope_label={scope_label})"
                        )
                        return {
                            "ok": True,
                            "reason": "ok",
                            "message": "Microsoft mailbox availability test passed",
                            "access_token": access_token,
                            "scope_label": scope_label,
                            "endpoint": endpoint,
                            "expires_in": expires_in_value,
                        }

                    self._log(
                        f"[Microsoft Mail] OAuth token Response did not contain access_token: keys={sorted(list(data.keys()))[:10]}"
                    )
                    last_error = body_text or "OAuth Response did not contain access_token"
                except Exception as exc:
                    last_error = body_text or str(exc) or "OAuth Response parsing failed"
                    self._log(
                        "[Microsoft Mail] OAuth token Response parsing exception: "
                        f"email={email} endpoint={endpoint} scope_label={scope_label} error={exc}"
                    )
                    continue

        return {
            "ok": False,
            "reason": "oauth_token_failed",
            "message": f"Microsoft mailbox availability test failed: {last_error or 'OAuth token Failed to obtain'}",
        }

    def _fetch_oauth_token_bundle(
        self,
        *,
        email: str,
        client_id: str,
        refresh_token: str,
        preferred_backend: str | None = None,
    ) -> dict[str, Any]:
        probe = self.probe_oauth_availability(
            email=email,
            client_id=client_id,
            refresh_token=refresh_token,
            preferred_backend=preferred_backend,
        )
        if probe.get("ok"):
            return {
                "access_token": str(probe.get("access_token") or ""),
                "scope_label": probe.get("scope_label", ""),
                "expires_in": probe.get("expires_in", 0),
                "endpoint": probe.get("endpoint", ""),
            }
        self._log(f"[Microsoft Mail] OAuth token Failed to obtain, fall back to password login: {email}")
        return {"reason": str(probe.get("reason") or "")}

    def _fetch_oauth_token(
        self,
        *,
        email: str,
        client_id: str,
        refresh_token: str,
        preferred_backend: str | None = None,
    ) -> str:
        bundle = self._fetch_oauth_token_bundle(
            email=email,
            client_id=client_id,
            refresh_token=refresh_token,
            preferred_backend=preferred_backend,
        )
        return str(bundle.get("access_token") or "").strip()

    def _get_oauth_access_token(
        self,
        account: MailboxAccount,
        *,
        preferred_backend: str | None = None,
    ) -> str:
        extra = account.extra or {}
        client_id = str(extra.get("client_id") or "").strip()
        refresh_token = str(extra.get("refresh_token") or "").strip()
        email_addr = str(account.email or "").strip()
        if not client_id or not refresh_token:
            raise RuntimeError("Microsoft Mail OAuth Credentials are missing and cannot be obtained access token")

        cache = extra.setdefault("_oauth_token_cache", {})
        cache_key = self._normalize_backend_name(preferred_backend or self._backend_name)
        cached = cache.get(cache_key) if isinstance(cache, dict) else None
        now = time.time()
        if isinstance(cached, dict):
            access_token = str(cached.get("access_token") or "").strip()
            expires_at = float(cached.get("expires_at") or 0)
            if access_token and expires_at > now + 60:
                return access_token

        bundle = self._fetch_oauth_token_bundle(
            email=email_addr,
            client_id=client_id,
            refresh_token=refresh_token,
            preferred_backend=cache_key,
        )
        access_token = str(bundle.get("access_token") or "").strip()
        if not access_token:
            reason = bundle.get("reason", "")
            suffix = f" [{reason}]" if reason else ""
            raise RuntimeError(f"Microsoft Mail OAuth access token Failed to obtain{suffix}")

        expires_in = bundle.get("expires_in")
        try:
            expires_in_value = max(int(expires_in or 0), 0)
        except (TypeError, ValueError):
            expires_in_value = 0
        if isinstance(cache, dict):
            cache[cache_key] = {
                "access_token": access_token,
                "expires_at": now + expires_in_value if expires_in_value else now + 300,
                "scope_label": bundle.get("scope_label", ""),
            }
        return access_token

    def _imap_auth_oauth(self, imap_conn, *, email: str, access_token: str) -> None:
        auth_string = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
        imap_conn.authenticate("XOAUTH2", lambda _: auth_string.encode("utf-8"))

    def _open_imap(self, account: MailboxAccount):
        import imaplib

        email_addr = str(account.email or "").strip()
        extra = account.extra or {}
        password = str(extra.get("password") or "").strip()
        client_id = str(extra.get("client_id") or "").strip()
        refresh_token = str(extra.get("refresh_token") or "").strip()

        access_token = ""
        if client_id and refresh_token:
            access_token = self._get_oauth_access_token(
                account,
                preferred_backend="imap",
            )

        last_error = None
        for host in self._imap_servers:
            if not host:
                continue
            if access_token:
                try:
                    imap_conn = imaplib.IMAP4_SSL(host, self._imap_port, timeout=30)
                    self._imap_auth_oauth(
                        imap_conn, email=email_addr, access_token=access_token
                    )
                    return imap_conn
                except Exception as exc:
                    last_error = exc
                    try:
                        imap_conn.logout()
                    except Exception:
                        pass
            if password:
                try:
                    imap_conn = imaplib.IMAP4_SSL(host, self._imap_port, timeout=30)
                    imap_conn.login(email_addr, password)
                    return imap_conn
                except Exception as exc:
                    last_error = exc
                    try:
                        imap_conn.logout()
                    except Exception:
                        pass

        raise RuntimeError(f"Microsoft Mail IMAP Login failed: {last_error}")

    def _resolve_backend(self, account: MailboxAccount) -> OutlookMailboxBackend:
        extra = account.extra or {}
        if self._is_mailapi_account(account):
            return self._backends["mailapi_url"]
        override = self._normalize_backend_name(
            extra.get("outlook_backend") or self._backend_name
        )
        if override == "graph":
            has_oauth = bool(
                str(extra.get("client_id") or "").strip()
                and str(extra.get("refresh_token") or "").strip()
            )
            if not has_oauth:
                self._log(
                    "[Microsoft Mail] Graph Backend needs OAuth Credentials, the current account is missing client_id/refresh_token, automatically switch IMAP"
                )
                override = "imap"
        return self._backends.get(override) or self._backends["graph"]

    def _graph_headers(self, *, access_token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
        }

    def _graph_request_json(
        self,
        *,
        method: str,
        path: str,
        access_token: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        import requests

        url = f"{self._graph_api_base.rstrip('/')}/{path.lstrip('/')}"
        resp = requests.request(
            method,
            url,
            headers=self._graph_headers(access_token=access_token),
            params=params or None,
            timeout=20,
            proxies=self._proxy,
        )
        if resp.status_code >= 400:
            preview = (resp.text or "")[:300]
            raise RuntimeError(
                f"Outlook Graph Request failed: HTTP {resp.status_code} {preview}"
            )
        return resp.json() if resp.content else {}

    def _graph_list_messages(
        self,
        *,
        access_token: str,
        folder: str,
    ) -> list[dict[str, Any]]:
        data = self._graph_request_json(
            method="GET",
            path=f"/me/mailFolders/{folder}/messages",
            access_token=access_token,
            params={
                "$top": "25",
                "$orderby": "receivedDateTime DESC",
                "$select": "id,subject,bodyPreview,body,receivedDateTime,from,internetMessageId",
            },
        )
        value = data.get("value") or []
        return value if isinstance(value, list) else []

    def _graph_get_message(
        self,
        *,
        access_token: str,
        message_id: str,
    ) -> dict[str, Any]:
        from urllib.parse import quote

        return self._graph_request_json(
            method="GET",
            path=f"/me/messages/{quote(str(message_id or '').strip(), safe='')}",
            access_token=access_token,
            params={
                "$select": "id,subject,bodyPreview,body,uniqueBody,receivedDateTime,from,internetMessageId",
            },
        )

    def _graph_message_text(self, message: dict[str, Any]) -> str:
        subject = str((message or {}).get("subject") or "").strip()
        preview = str((message or {}).get("bodyPreview") or "").strip()

        body = (message or {}).get("body") or {}
        body_content = (
            str(body.get("content") or "").strip() if isinstance(body, dict) else ""
        )
        unique_body = (message or {}).get("uniqueBody") or {}
        unique_body_content = (
            str(unique_body.get("content") or "").strip()
            if isinstance(unique_body, dict)
            else ""
        )
        combined = " ".join(
            part for part in [subject, preview, body_content, unique_body_content] if part
        )
        return self._decode_raw_content(combined)

    def _decode_header_value(self, value: str) -> str:
        from email.header import decode_header

        if not value:
            return ""
        parts = decode_header(value)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                try:
                    decoded.append(part.decode(charset or "utf-8", errors="ignore"))
                except Exception:
                    decoded.append(part.decode("utf-8", errors="ignore"))
            else:
                decoded.append(str(part))
        return "".join(decoded)

    def _extract_message_text(self, message) -> str:
        subject = self._decode_header_value(message.get("Subject", ""))
        body_chunks = []
        if message.is_multipart():
            for part in message.walk():
                if part.get_content_maintype() == "multipart":
                    continue
                content_type = part.get_content_type()
                if content_type not in ("text/plain", "text/html"):
                    continue
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                try:
                    body_chunks.append(payload.decode(charset, errors="ignore"))
                except Exception:
                    body_chunks.append(payload.decode("utf-8", errors="ignore"))
        else:
            payload = message.get_payload(decode=True)
            if payload is None:
                payload = message.get_payload()
            if isinstance(payload, bytes):
                try:
                    body_chunks.append(payload.decode("utf-8", errors="ignore"))
                except Exception:
                    body_chunks.append(payload.decode("latin1", errors="ignore"))
            elif payload:
                body_chunks.append(str(payload))

        combined = (subject + " " + " ".join(body_chunks)).strip()
        return self._decode_raw_content(combined)

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            backend = self._resolve_backend(account)
            self._log(f"[Microsoft Mail] Current receiving backend: {backend.backend_name}")
            return backend.get_current_ids(account)
        except Exception as exc:
            self._log(f"[Microsoft Mail] Get current email ID fail: {exc}")
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
        backend = self._resolve_backend(account)
        self._log(f"[Microsoft Mail] OTP Receiving backend: {backend.backend_name}")
        return backend.wait_for_code(
            account,
            keyword=keyword,
            timeout=timeout,
            before_ids=before_ids,
            code_pattern=code_pattern,
            **kwargs,
        )


class FreemailMailbox(BaseMailbox):
    """
    Freemail Self-built mailbox service (based on Cloudflare Worker)
    project: https://github.com/idinging/freemail
    Supports two authentication methods: administrator token or account password
    """

    def __init__(
        self,
        api_url: str,
        admin_token: str = "",
        username: str = "",
        password: str = "",
        domain: str = "",
        proxy: str = None,
    ):
        self.api = api_url.rstrip("/")
        self.admin_token = admin_token
        self.username = username
        self.password = password
        self.domain = str(domain or "").strip().lstrip("@")
        self.proxy = build_requests_proxy_config(proxy)
        self._session = None
        self._email = None
        self._domains = None

    def _get_session(self):
        import requests

        s = requests.Session()
        s.proxies = self.proxy
        if self.admin_token:
            s.headers.update({"Authorization": f"Bearer {self.admin_token}"})
        elif self.username and self.password:
            s.post(
                f"{self.api}/api/login",
                json={"username": self.username, "password": self.password},
                timeout=15,
            )
        self._session = s
        return s

    def get_email(self) -> MailboxAccount:
        if not self._session:
            self._get_session()

        target_domain = self.domain
        domain_index = 0
        if target_domain:
            domains = self._ensure_domains()
            if domains:
                lookup = str(target_domain).lower()
                for idx, domain in enumerate(domains):
                    if str(domain or "").strip().lower() == lookup:
                        domain_index = idx
                        break

        params = {"domainIndex": domain_index} if target_domain else {}
        r = self._session.get(f"{self.api}/api/generate", params=params, timeout=15)
        data = r.json()
        email = str(data.get("email", "") or "")
        if target_domain and email and "@" in email:
            actual_domain = email.split("@", 1)[1].strip().lower()
            if actual_domain != target_domain.lower():
                self._log(
                    f"[Freemail] Specify domain name {target_domain} Missed, actual return {actual_domain}"
                )

        self._email = email
        print(f"[Freemail] Generate mailbox: {email}")
        return MailboxAccount(email=email, account_id=email)

    def _ensure_domains(self) -> list:
        if self._domains is not None:
            return self._domains
        self._domains = []
        if not self._session:
            self._get_session()
        try:
            r = self._session.get(f"{self.api}/api/domains", timeout=15)
            payload = r.json()
            normalized = []
            def _append_domain(value):
                domain = str(value or "").strip().lstrip("@")
                if domain and domain not in normalized:
                    normalized.append(domain)
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        _append_domain(
                            item.get("domain")
                            or item.get("name")
                            or item.get("value")
                        )
                    else:
                        _append_domain(item)
            elif isinstance(payload, dict):
                candidates = payload.get("domains") or payload.get("data") or []
                if isinstance(candidates, list):
                    for item in candidates:
                        if isinstance(item, dict):
                            _append_domain(
                                item.get("domain")
                                or item.get("name")
                                or item.get("value")
                            )
                        else:
                            _append_domain(item)
            self._domains = normalized
        except Exception:
            self._domains = []
        return self._domains

    def get_current_ids(self, account: MailboxAccount) -> set:
        try:
            r = self._session.get(
                f"{self.api}/api/emails",
                params={"mailbox": account.email, "limit": 50},
                timeout=10,
            )
            return {str(m["id"]) for m in r.json() if "id" in m}
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
        seen = set(before_ids or [])
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }

        def poll_once() -> Optional[str]:
            try:
                r = self._session.get(
                    f"{self.api}/api/emails",
                    params={"mailbox": account.email, "limit": 20},
                    timeout=10,
                )
                for msg in r.json():
                    mid = str(msg.get("id", ""))
                    if not mid or mid in seen:
                        continue
                    seen.add(mid)
                    # Use directly verification_code Field
                    code = str(msg.get("verification_code") or "").strip()
                    if code and code != "None":
                        if code in exclude_codes:
                            continue
                        return code
                    # Bottom line: from preview extract
                    text = (
                        str(msg.get("preview", "")) + " " + str(msg.get("subject", ""))
                    )
                    code = self._safe_extract(text, code_pattern)
                    if code:
                        if code in exclude_codes:
                            continue
                        return code
            except Exception:
                pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=3,
            poll_once=poll_once,
        )


class ImapCatchallMailbox(BaseMailbox):
    """Generic IMAP catchall mailbox provider.

    Connects to any IMAP server with standard username/password authentication.
    Generates random email addresses on the configured domain (catchall routing
    must be configured on the mail server so all addresses land in one inbox).
    Polls the IMAP inbox for verification codes by matching the To/Delivered-To
    header to the generated address.
    """

    def __init__(
        self,
        imap_server: str,
        imap_port: int = 993,
        imap_username: str = "",
        imap_password: str = "",
        domain: str = "",
        folders: str = "INBOX",
        proxy: str = None,
    ):
        self._imap_server = str(imap_server or "").strip()
        try:
            self._imap_port = int(imap_port or 993)
        except (TypeError, ValueError):
            self._imap_port = 993
        self._imap_username = str(imap_username or "").strip()
        self._imap_password = str(imap_password or "").strip()
        self._domain = str(domain or "").strip()
        self._folder_names = [
            f.strip() for f in str(folders or "INBOX").split(",") if f.strip()
        ] or ["INBOX"]
        self._generated_email = ""

    def _ensure_config(self) -> None:
        if not self._imap_server:
            raise RuntimeError(
                "IMAP Catchall not fully configured: imap_catchall_server is required"
            )
        if not self._imap_username or not self._imap_password:
            raise RuntimeError(
                "IMAP Catchall not fully configured: imap_catchall_username and imap_catchall_password are required"
            )
        if not self._domain:
            raise RuntimeError(
                "IMAP Catchall not fully configured: imap_catchall_domain is required"
            )

    def _gen_prefix(self) -> str:
        import string

        length = random.randint(8, 13)
        chars = string.ascii_lowercase + string.digits
        return "".join(random.choice(chars) for _ in range(length))

    def _open_imap(self):
        import imaplib

        conn = imaplib.IMAP4_SSL(self._imap_server, self._imap_port, timeout=30)
        conn.login(self._imap_username, self._imap_password)
        return conn

    @staticmethod
    def _decode_header_value(raw) -> str:
        from email.header import decode_header

        if raw is None:
            return ""
        parts = []
        for part, charset in decode_header(str(raw)):
            if isinstance(part, bytes):
                parts.append(part.decode(charset or "utf-8", errors="ignore"))
            else:
                parts.append(str(part))
        return " ".join(parts).strip()

    @staticmethod
    def _extract_message_text(msg) -> str:
        import re

        parts: list[str] = []

        def _walk(payload):
            if payload.is_multipart():
                for sub in payload.iter_parts():
                    _walk(sub)
            else:
                ct = str(payload.get_content_type() or "")
                if ct.startswith("text/"):
                    body = payload.get_content()
                    if isinstance(body, bytes):
                        body = body.decode("utf-8", errors="ignore")
                    parts.append(str(body or ""))

        _walk(msg)
        text = " ".join(parts)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _email_matches(self, msg, target_email: str) -> bool:
        """Check if the email was addressed to target_email."""
        import re

        target_lower = target_email.lower()
        for header_name in ("To", "Delivered-To", "X-Original-To", "Envelope-To"):
            value = str(msg.get(header_name) or "").lower()
            if target_lower in value:
                return True
        # Also check Received headers for the target
        for received in msg.get_all("Received") or []:
            if target_lower in str(received or "").lower():
                return True
        return False

    def get_email(self) -> MailboxAccount:
        self._ensure_config()
        prefix = self._gen_prefix()
        email = f"{prefix}@{self._domain}"
        self._generated_email = email
        self._log(f"[IMAP Catchall] Generated email: {email}")
        return MailboxAccount(email=email, account_id=email, extra={"provider": "imap_catchall"})

    def get_current_ids(self, account: MailboxAccount) -> set:
        imap_conn = None
        try:
            imap_conn = self._open_imap()
            seen: set[str] = set()
            for folder in self._folder_names:
                try:
                    status, _ = imap_conn.select(folder, readonly=True)
                    if status != "OK":
                        continue
                    status, data = imap_conn.uid("search", None, "ALL")
                    if status != "OK":
                        continue
                    ids = data[0].split() if data and data[0] else []
                    for uid in ids[-100:]:
                        uid_str = (
                            uid.decode("utf-8", errors="ignore")
                            if isinstance(uid, bytes)
                            else str(uid)
                        )
                        if uid_str:
                            seen.add(f"{folder}:{uid_str}")
                except Exception:
                    continue
            return seen
        except Exception as exc:
            self._log(f"[IMAP Catchall] get_current_ids error: {exc}")
            return set()
        finally:
            try:
                if imap_conn:
                    imap_conn.logout()
            except Exception:
                pass

    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
        **kwargs,
    ) -> str:
        from email import message_from_bytes
        from email.policy import default as email_default_policy

        seen = {str(mid) for mid in (before_ids or set())}
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }
        keyword_lower = str(keyword or "").strip().lower()
        target_email = str(account.email or "").strip()

        def poll_once() -> Optional[str]:
            for folder in self._folder_names:
                imap_conn = None
                try:
                    self._log(f"[IMAP Catchall] folder={folder} polling...")
                    imap_conn = self._open_imap()
                    status, _ = imap_conn.select(folder, readonly=True)
                    if status != "OK":
                        self._log(f"[IMAP Catchall] folder={folder} select fail: {status}")
                        continue
                    status, data = imap_conn.uid("search", None, "ALL")
                    if status != "OK":
                        self._log(f"[IMAP Catchall] folder={folder} search fail: {status}")
                        continue
                    ids = data[0].split() if data and data[0] else []
                    if len(ids) > 50:
                        ids = ids[-50:]
                    new_uids = []
                    for uid in ids:
                        uid_str = (
                            uid.decode("utf-8", errors="ignore")
                            if isinstance(uid, bytes)
                            else str(uid)
                        )
                        seen_key = f"{folder}:{uid_str}"
                        if not uid_str or seen_key in seen:
                            continue
                        seen.add(seen_key)
                        new_uids.append(uid)
                    self._log(
                        f"[IMAP Catchall] folder={folder} uid_total={len(ids)} new={len(new_uids)}"
                    )
                    for uid in new_uids:
                        status, msg_data = imap_conn.uid("fetch", uid, "(RFC822)")
                        if status != "OK":
                            continue
                        raw = None
                        for item in msg_data or []:
                            if isinstance(item, tuple) and item[1]:
                                raw = item[1]
                                break
                        if not raw:
                            continue
                        msg = message_from_bytes(raw, policy=email_default_policy)
                        # Check if this email was addressed to our generated address
                        if target_email and not self._email_matches(msg, target_email):
                            continue
                        subject = self._decode_header_value(msg.get("Subject", ""))
                        text = self._extract_message_text(msg)
                        full_text = f"{subject} {text}"
                        self._log(
                            f"[IMAP Catchall] folder={folder} matched mail for {target_email}, subject={subject or '-'}"
                        )
                        if keyword_lower and keyword_lower not in full_text.lower():
                            self._log(f"[IMAP Catchall] folder={folder} keyword mismatch, skipping")
                            continue
                        if code_pattern and "http" in code_pattern:
                            code = self._safe_extract(full_text, code_pattern)
                        else:
                            code = self._yyds_safe_extract(
                                self._yyds_decode_raw_content(full_text), code_pattern
                            )
                            if not code:
                                code = self._safe_extract(full_text, code_pattern)
                        if not code:
                            self._log(f"[IMAP Catchall] folder={folder} no code found in email")
                            continue
                        if code in exclude_codes:
                            self._log(f"[IMAP Catchall] folder={folder} code {code} excluded")
                            continue
                        self._log(f"[IMAP Catchall] folder={folder} extracted code: {code}")
                        return code
                except Exception as exc:
                    self._log(f"[IMAP Catchall] folder={folder} error: {exc}")
                finally:
                    try:
                        if imap_conn:
                            imap_conn.logout()
                    except Exception:
                        pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=5,
            poll_once=poll_once,
        )
