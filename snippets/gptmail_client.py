"""
GPTMail Client — Reusable snippet for gptmail.co.uk (mail.chatgpt.org.uk)

Usage:
    from gptmail_client import GPTMailClient

    client = GPTMailClient(api_key="sk-YOUR_KEY")

    # Generate a fresh disposable email
    email = client.generate_email()
    # Or specify a domain:  email = client.generate_email(domain="example.com")

    # Snapshot current inbox message IDs (to filter out old mail later)
    before_ids = client.get_message_ids(email)

    # ... trigger the OTP / verification email from whatever service ...

    # Poll for a 6-digit verification code, ignoring messages already seen
    code = client.wait_for_code(email, before_ids=before_ids, timeout=120)
    print(f"Got code: {code}")

Requirements:
    pip install requests
"""

from __future__ import annotations

import html
import os
import random
import re
import string
import time
from typing import Any, Callable, Optional

import requests


class GPTMailClient:
    """Lightweight, self-contained client for the GPTMail temp-email API."""

    DEFAULT_BASE_URL = "https://mail.chatgpt.org.uk"

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        proxy: str | None = None,
        log_fn: Callable[[str], None] | None = None,
    ):
        self.api = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key.strip()
        self.proxy = self._build_proxy_config(proxy)
        self._log_fn = log_fn or (lambda msg: print(f"[GPTMail] {msg}"))

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def generate_email(self, domain: str = "") -> str:
        """Generate a new disposable email address.

        If *domain* is provided, a random local-part is assembled locally
        (no API call). Otherwise the API picks a domain for you.
        """
        domain = self._normalize_domain(domain)
        if domain:
            email = f"{self._random_local_part()}@{domain}"
            self._log(f"Assembled address locally: {email}")
            return email

        data = self._request_json("GET", "/api/generate-email")
        if not isinstance(data, dict):
            raise RuntimeError(f"GPTMail returned unexpected payload: {data}")

        email = str(data.get("email") or "").strip()
        if not email:
            raise RuntimeError(f"GPTMail returned empty email: {data}")

        self._log(f"Generated address: {email}")
        return email

    def generate_email_from_domains(
        self,
        domains_file: str = "",
        domains: list[str] | None = None,
    ) -> str:
        """Generate an email locally from a domains list — NO API call needed.

        GPTMail uses catch-all domains: any ``username@domain`` will work as
        long as the domain is one that GPTMail controls. This method picks a
        random domain from a file (one domain per line) or from an explicit
        list, generates a random local-part, and returns the address.

        You can then go straight to ``wait_for_code()`` to retrieve OTPs —
        no ``/api/generate-email`` call required.

        Args:
            domains_file: Path to a text file with one domain per line.
                          Defaults to ``DOMAINS.txt`` next to this script.
            domains:      Explicit list of domains (overrides *domains_file*).

        Returns:
            A fresh ``randomuser1234@picked-domain.com`` address.
        """
        if domains:
            domain_list = [d.strip() for d in domains if d.strip()]
        else:
            if not domains_file:
                # Default: DOMAINS.txt in the same directory as this file
                domains_file = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "DOMAINS.txt"
                )
            if not os.path.exists(domains_file):
                raise FileNotFoundError(
                    f"Domains file not found: {domains_file}\n"
                    "Provide a file with one domain per line, or pass domains=[]."
                )
            with open(domains_file, "r", encoding="utf-8") as f:
                domain_list = [
                    line.strip()
                    for line in f
                    if line.strip() and not line.strip().startswith("#")
                ]

        if not domain_list:
            raise ValueError("No domains available")

        domain = random.choice(domain_list)
        email = f"{self._random_local_part()}@{domain}"
        self._log(f"Assembled from domains list: {email} (from {len(domain_list)} domains)")
        return email

    def list_messages(self, email: str) -> list[dict[str, Any]]:
        """Return all messages currently in *email*'s inbox."""
        data = self._request_json(
            "GET", "/api/emails", params={"email": email}, timeout=10
        )
        if isinstance(data, dict):
            messages = data.get("emails", [])
        else:
            messages = data
        return [item for item in (messages or []) if isinstance(item, dict)]

    def get_message_detail(self, message_id: str) -> dict[str, Any]:
        """Fetch the full content of a single message by its ID."""
        data = self._request_json("GET", f"/api/email/{message_id}", timeout=10)
        return data if isinstance(data, dict) else {}

    def get_message_ids(self, email: str) -> set[str]:
        """Return the set of message IDs currently in the inbox.

        Useful for snapshotting *before* triggering an OTP so you can
        filter out old messages when polling.
        """
        try:
            return {
                str(m.get("id"))
                for m in self.list_messages(email)
                if m.get("id") is not None
            }
        except Exception:
            return set()

    def wait_for_code(
        self,
        email: str,
        *,
        keyword: str = "",
        timeout: int = 120,
        poll_interval: float = 3.0,
        before_ids: set[str] | None = None,
        code_pattern: str | None = None,
        exclude_codes: set[str] | None = None,
    ) -> str:
        """Poll the inbox until a verification code is found.

        Args:
            email:          The disposable email to poll.
            keyword:        Optional keyword the email must contain (e.g. "AWS").
            timeout:        Max seconds to wait.
            poll_interval:  Seconds between polls.
            before_ids:     Message IDs to skip (from a prior snapshot).
            code_pattern:   Custom regex for the code (default: 6-digit match).
            exclude_codes:  Codes to ignore (e.g. previously used ones).

        Returns:
            The extracted verification code string.

        Raises:
            TimeoutError if no code is found within *timeout* seconds.
        """
        seen = {str(mid) for mid in (before_ids or set())}
        excluded = {str(c) for c in (exclude_codes or set()) if c}

        def poll_once() -> Optional[str]:
            try:
                messages = self.list_messages(email)
                self._log(f"Poll: {len(messages)} total messages")

                new_count = 0
                for message in messages:
                    message_id = str(message.get("id") or "").strip()
                    if not message_id or message_id in seen:
                        continue
                    seen.add(message_id)
                    new_count += 1

                    subject = str(message.get("subject") or "")
                    from_addr = str(message.get("from_address") or "")
                    self._log(
                        f"New email #{new_count}: from={from_addr[:50]} "
                        f"subject='{subject[:60]}'"
                    )

                    # Fetch full detail
                    try:
                        detail = self.get_message_detail(message_id)
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
                    # Strip email addresses to avoid false 6-digit matches
                    search_text = re.sub(
                        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        "",
                        search_text,
                    )

                    if keyword and keyword.lower() not in search_text.lower():
                        self._log(f"Email #{new_count} doesn't match keyword '{keyword}'")
                        continue

                    code = self._extract_code(search_text, code_pattern)
                    if code and code in excluded:
                        self._log(f"Email #{new_count} code {code} excluded, skipping")
                        continue
                    if code:
                        self._log(f"Extracted code: {code}")
                        return code
                    else:
                        self._log(f"Email #{new_count}: no code found")

                if new_count == 0:
                    self._log("Poll: no new emails")
            except Exception as e:
                self._log(f"Poll error: {e}")
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=poll_interval,
            poll_once=poll_once,
        )

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _log(self, message: str) -> None:
        if self._log_fn:
            self._log_fn(message)

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
                f"GPTMail API {path} returned non-JSON: HTTP {response.status_code} {preview}"
            ) from exc

        if response.status_code >= 400:
            error = payload.get("error") if isinstance(payload, dict) else ""
            message = str(error or response.text or f"HTTP {response.status_code}").strip()
            raise RuntimeError(f"GPTMail API {path} failed: {message}")

        if isinstance(payload, dict) and payload.get("success") is False:
            error = str(payload.get("error") or "unknown error").strip()
            raise RuntimeError(f"GPTMail API {path} failed: {error}")

        # Unwrap the standard { success, data } envelope
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    def _run_polling_wait(
        self,
        *,
        timeout: int,
        poll_interval: float,
        poll_once: Callable[[], Optional[str]],
    ) -> str:
        deadline = time.monotonic() + max(int(timeout), 1)
        while time.monotonic() < deadline:
            code = poll_once()
            if code:
                return code
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(poll_interval, remaining))
        raise TimeoutError(f"Timeout waiting for verification code ({timeout}s)")

    @staticmethod
    def _normalize_domain(value: Any) -> str:
        domain = str(value or "").strip().lower()
        if domain.startswith("@"):
            domain = domain[1:]
        return domain

    @staticmethod
    def _random_local_part() -> str:
        prefix = "".join(random.choices(string.ascii_lowercase, k=6))
        suffix = "".join(random.choices(string.digits, k=4))
        return f"{prefix}{suffix}"

    @staticmethod
    def _build_proxy_config(proxy: str | None) -> dict | None:
        if not proxy:
            return None
        proxy = proxy.strip()
        return {"http": proxy, "https": proxy}

    @staticmethod
    def _extract_code(text: str, pattern: str | None = None) -> Optional[str]:
        """Extract a verification code from *text*.

        Tries patterns in priority order:
        1. Caller-supplied custom pattern
        2. Semantic patterns ('verification code', 'one-time password', etc.)
        3. Generic 'code' + 6 digits
        4. Bare 6-digit number with safe boundaries
        """
        text = str(text or "")
        if not text:
            return None

        # Strip URLs to avoid false positives from tracking links
        text = re.sub(r"https?://\S+", "", text)

        patterns: list[str] = []
        if pattern:
            if pattern in (r"\d{6}", r"(\d{6})"):
                patterns.append(r"(?<![a-zA-Z0-9])(\d{6})(?![a-zA-Z0-9])")
            else:
                patterns.append(pattern)

        patterns.extend(
            [
                r"(?is)(?:verification\s+code|one[-\s]*time\s+(?:password|code)|security\s+code|login\s+code)[^0-9]{0,30}(\d{6})",
                r"(?is)\bcode\b[^0-9]{0,12}(\d{6})",
                r"(?<![a-zA-Z0-9])(\d{6})(?![a-zA-Z0-9])",
            ]
        )

        for regex in patterns:
            m = re.search(regex, text)
            if m:
                return m.group(1) if m.groups() else m.group(0)
        return None

    @staticmethod
    def _decode_raw_content(raw: str) -> str:
        """Decode Quoted-Printable, strip HTML tags and MIME boundaries."""
        import quopri

        text = str(raw or "")
        if not text:
            return ""

        # Only strip headers if the text looks like a raw email
        if re.search(
            r"(?im)^(?:Return-Path|Received|Date|From|To|Subject|Content-Type):", text
        ):
            if "\r\n\r\n" in text:
                text = text.split("\r\n\r\n", 1)[1]
            elif "\n\n" in text:
                text = text.split("\n\n", 1)[1]

        try:
            decoded_bytes = quopri.decodestring(text)
            text = decoded_bytes.decode("utf-8", errors="ignore")
        except Exception:
            pass

        text = html.unescape(text)
        text = re.sub(r"(?im)^content-(?:type|transfer-encoding):.*$", " ", text)
        text = re.sub(r"(?im)^--+[_=\w.-]+$", " ", text)
        text = re.sub(r"(?i)----=_part_[\w.]+", " ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text


# ------------------------------------------------------------------ #
#  Convenience: run directly to test                                  #
# ------------------------------------------------------------------ #
if __name__ == "__main__":
    import sys

    api_key = sys.argv[1] if len(sys.argv) > 1 else ""
    client = GPTMailClient(api_key=api_key)

    print("=== Generating email ===")
    email = client.generate_email()
    print(f"Email: {email}")

    print("\n=== Current inbox ===")
    messages = client.list_messages(email)
    print(f"Messages: {len(messages)}")
    for msg in messages:
        print(f"  [{msg.get('id')}] {msg.get('subject', '(no subject)')}")

    print("\n=== Snapshot IDs ===")
    ids = client.get_message_ids(email)
    print(f"IDs: {ids}")

    print(
        "\nTo poll for a code, trigger an OTP to this address and run:\n"
        f'  client.wait_for_code("{email}", before_ids={ids})'
    )
