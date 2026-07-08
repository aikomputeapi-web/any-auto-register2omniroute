"""
OAuth PKCE Register client

Complete implementation auth.openai.com Register state machine + Log in to get Token the whole life cycle.
Each step is encapsulated as an independent method, and the caller can complete the entire registration process by calling it in sequence.
"""

import json
import re
import time
import urllib.parse
from typing import Optional

from curl_cffi import requests as curl_requests
from core.proxy_utils import build_requests_proxy_config

from .oauth import (
    OAuthStart,
    _decode_jwt_segment,
    generate_oauth_url,
    submit_callback_url,
)

AUTH_BASE = "https://auth.openai.com"
SENTINEL_API = "https://sentinel.openai.com/backend-api/sentinel/req"
SENTINEL_REFERER = (
    "https://sentinel.openai.com/backend-api/sentinel/frame.html?sv=20260219f9f6"
)
CLOUDFLARE_TRACE = "https://cloudflare.com/cdn-cgi/trace"


class OAuthPkceClient:
    """
    OAuth PKCE Register client

    Complete registration process (12 step):
      1.  examine IP area
      2.  access OAuth Authorize URL, get oai-did Cookie
      3.  get Sentinel Token
      4.  Submit email (authorize/continue)
      5.  Submit password (user/register)
      6.  send OTP (email-otp/send)
      7.  verify OTP (email-otp/validate)
      8.  create Account (create_account)
      9.  Register again OAuth Log in
      10. parse workspace_id
      11. choose workspace
      12. Tracking redirect chains, exchanges OAuth code → access_token
    """

    def __init__(self, proxy: Optional[str] = None, log_fn=None):
        self.proxy = proxy
        self._log = log_fn or (lambda msg: None)
        self._proxies = build_requests_proxy_config(self.proxy)

        # Main session: throughout registration + Login process
        self.session = curl_requests.Session(
            proxies=self._proxies,
            impersonate="chrome",
            verify=False,
        )

        self._device_id: Optional[str] = None
        self._sentinel: Optional[str] = None

    # ══════════════════════════════════════════════════════════════════
    # Internal method: Get Sentinel Token(minimalist mode)
    # ══════════════════════════════════════════════════════════════════

    def _fetch_sentinel_token(
        self, device_id: str, flow: str = "authorize_continue"
    ) -> str:
        """
        get Sentinel Token.

        Use independent connections (no multiplexing) session cookie), request body p Leave the field blank,
        Only get the response token The fields are assembled into openai-sentinel-token header value.

        Returns:
            JSON Formatted sentinel token string.
        """
        req_body = json.dumps({"p": "", "id": device_id, "flow": flow})

        resp = curl_requests.post(
            SENTINEL_API,
            headers={
                "origin": "https://sentinel.openai.com",
                "referer": SENTINEL_REFERER,
                "content-type": "text/plain;charset=UTF-8",
            },
            data=req_body,
            proxies=self._proxies,
            impersonate="chrome",
            timeout=15,
        )

        if resp.status_code != 200:
            raise RuntimeError(f"Sentinel Failed to obtain: HTTP {resp.status_code}")

        c_value = resp.json().get("token", "")
        if not c_value:
            raise RuntimeError("Sentinel Response missing token Field")

        return json.dumps(
            {
                "p": "",
                "t": "",
                "c": c_value,
                "id": device_id,
                "flow": flow,
            },
            separators=(",", ":"),
        )

    # ══════════════════════════════════════════════════════════════════
    # step 1:examine IP area
    # ══════════════════════════════════════════════════════════════════

    def check_ip_region(self) -> str:
        """Check current IP area,CN/HK Not supported."""
        try:
            resp = self.session.get(CLOUDFLARE_TRACE, timeout=10)
            match = re.search(r"^loc=(.+)$", resp.text, re.MULTILINE)
            loc = match.group(1).strip() if match else "UNKNOWN"
            self._log(f"current IP area: {loc}")
            if loc in ("CN", "HK"):
                raise RuntimeError(f"IP Region not supported: {loc}")
            return loc
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"IP Region check failed: {e}") from e

    # ══════════════════════════════════════════════════════════════════
    # step 2:access OAuth Authorize URL, get oai-did Cookie
    # ══════════════════════════════════════════════════════════════════

    def init_oauth_session(self) -> OAuthStart:
        """generate OAuth PKCE URL and access, build auth.openai.com session."""
        oauth = generate_oauth_url()
        self._log("access OAuth Authorize URL...")
        self.session.get(oauth.auth_url, timeout=15)
        self._device_id = self.session.cookies.get("oai-did") or ""
        self._log(
            f"oai-did: {self._device_id[:16]}..."
            if self._device_id
            else "oai-did: (Not obtained)"
        )
        return oauth

    # ══════════════════════════════════════════════════════════════════
    # step 3: get Sentinel Token
    # ══════════════════════════════════════════════════════════════════

    def refresh_sentinel(self) -> str:
        """get new Sentinel Token and cache."""
        if not self._device_id:
            raise RuntimeError("Not initialized yet oai-did(Please call first init_oauth_session)")
        self._sentinel = self._fetch_sentinel_token(self._device_id)
        self._log("Sentinel Token Obtained")
        return self._sentinel

    # ══════════════════════════════════════════════════════════════════
    # step 4:Submit email
    # ══════════════════════════════════════════════════════════════════

    def submit_email(self, email: str) -> dict:
        """Towards authorize/continue Submit the email address and trigger the registration state machine."""
        if not self._sentinel:
            raise RuntimeError("Sentinel Token not initialized")

        payload = json.dumps(
            {
                "username": {"value": email, "kind": "email"},
                "screen_hint": "signup",
            }
        )
        self._log(f"Submit email: {email}")

        resp = self.session.post(
            f"{AUTH_BASE}/api/accounts/authorize/continue",
            headers={
                "referer": f"{AUTH_BASE}/create-account",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": self._sentinel,
            },
            data=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to submit email: HTTP {resp.status_code} {resp.text[:300]}"
            )

        data = resp.json()
        self._log(f"Email submission successful")
        return data

    # ══════════════════════════════════════════════════════════════════
    # step 5:Submit password
    # ══════════════════════════════════════════════════════════════════

    def submit_password(self, email: str, password: str) -> str:
        """Towards user/register Submit password and return continue_url."""
        payload = json.dumps({"password": password, "username": email})
        self._log("Submit password...")

        resp = self.session.post(
            f"{AUTH_BASE}/api/accounts/user/register",
            headers={
                "referer": f"{AUTH_BASE}/create-account/password",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": self._sentinel or "",
            },
            data=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Failed to submit password: HTTP {resp.status_code} {resp.text[:300]}"
            )

        continue_url = resp.json().get("continue_url") or ""
        self._log(f"Password submitted successfully{', continue_url Obtained' if continue_url else ''}")
        return continue_url

    # ══════════════════════════════════════════════════════════════════
    # step 6:send OTP
    # ══════════════════════════════════════════════════════════════════

    def send_otp(self, continue_url: str = "") -> bool:
        """Trigger the sending of email verification code."""
        url = continue_url or f"{AUTH_BASE}/api/accounts/email-otp/send"
        self._log(f"Send verification code: {url}")

        try:
            resp = self.session.post(
                url,
                headers={
                    "referer": f"{AUTH_BASE}/create-account/password",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "openai-sentinel-token": self._sentinel or "",
                },
                timeout=30,
            )
            self._log(f"Verification code sending status: {resp.status_code}")
            return resp.status_code == 200
        except Exception as e:
            self._log(f"Exception when sending verification code (non-fatal): {e}")
            return False

    # ══════════════════════════════════════════════════════════════════
    # step 7:verify OTP
    # ══════════════════════════════════════════════════════════════════

    def validate_otp(self, code: str) -> None:
        """Submit the email verification code."""
        self._log(f"verify OTP: {code}")

        resp = self.session.post(
            f"{AUTH_BASE}/api/accounts/email-otp/validate",
            headers={
                "referer": f"{AUTH_BASE}/email-verification",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=json.dumps({"code": code}),
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"OTP Authentication failed: HTTP {resp.status_code} {resp.text[:300]}"
            )
        self._log("OTP Verification passed")

    # ══════════════════════════════════════════════════════════════════
    # step 8:create Account
    # ══════════════════════════════════════════════════════════════════

    def create_account(self, name: str, birthdate: str) -> None:
        """Submit your name and birthday to complete account creation."""
        self._log(f"create Account: {name} ({birthdate})")

        resp = self.session.post(
            f"{AUTH_BASE}/api/accounts/create_account",
            headers={
                "referer": f"{AUTH_BASE}/about-you",
                "accept": "application/json",
                "content-type": "application/json",
            },
            data=json.dumps({"name": name, "birthdate": birthdate}),
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Account creation failed: HTTP {resp.status_code} {resp.text[:300]}"
            )
        self._log("Account created successfully")

    # ══════════════════════════════════════════════════════════════════
    # step 9:Re-register after OAuth Log in
    # ══════════════════════════════════════════════════════════════════

    def login_after_register(
        self, email: str, password: str, otp_code: str = ""
    ) -> OAuthStart:
        """
        Restart after registration is complete OAuth Login process.

        registration stage session Does not contain workspace Information, must go again
        OAuth Log in to get oai-client-auth-session Cookie.

        Returns:
            Login phase OAuthStart(Including code_verifier etc. for steps 12 Token exchange).
        """
        self._log("=" * 40)
        self._log("start OAuth Login (get workspace)...")

        # 9-1. Visit new OAuth URL
        login_oauth = generate_oauth_url()
        self.session.get(login_oauth.auth_url, timeout=15)
        login_did = self.session.cookies.get("oai-did") or self._device_id or ""
        self._log(
            f"Login phase oai-did: {login_did[:16]}..."
            if login_did
            else "Login phase oai-did: (null)"
        )

        # 9-2. Get login stage Sentinel
        login_sentinel = self._fetch_sentinel_token(login_did)

        # 9-3. Submit email (screen_hint=login)
        login_email_resp = self.session.post(
            f"{AUTH_BASE}/api/accounts/authorize/continue",
            headers={
                "referer": f"{AUTH_BASE}/sign-in",
                "accept": "application/json",
                "content-type": "application/json",
                "openai-sentinel-token": login_sentinel,
            },
            data=json.dumps(
                {
                    "username": {"value": email, "kind": "email"},
                    "screen_hint": "login",
                }
            ),
            timeout=30,
        )
        if login_email_resp.status_code != 200:
            raise RuntimeError(f"Failed to log in and submit email: HTTP {login_email_resp.status_code}")

        page_type = (login_email_resp.json().get("page") or {}).get("type", "")
        self._log(f"Login page type: {page_type}")

        # 9-4. Submit password (login_password page)
        if "password" in page_type:
            self._log("Submit password...")
            pwd_resp = self.session.post(
                f"{AUTH_BASE}/api/accounts/password/verify",
                headers={
                    "referer": f"{AUTH_BASE}/log-in/password",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "openai-sentinel-token": login_sentinel,
                },
                data=json.dumps({"password": password}),
                timeout=30,
            )
            if pwd_resp.status_code != 200:
                raise RuntimeError(f"Login password verification failed: HTTP {pwd_resp.status_code}")
            page_type = (pwd_resp.json().get("page") or {}).get("type", "")
            self._log(f"Page type after password verification: {page_type}")

        # 9-5. secondary OTP(Reuse the registration phase verification code)
        if "otp" in page_type or "verification" in page_type:
            if not otp_code:
                raise RuntimeError("Login required twice OTP Verified without providing verification code")
            self._log(f"Submit login two-step verification code: {otp_code}")
            # Trigger the sending request to satisfy the backend state machine (error reporting can be ignored)
            try:
                self.session.post(
                    f"{AUTH_BASE}/api/accounts/passwordless/send-otp",
                    headers={
                        "referer": f"{AUTH_BASE}/log-in/password",
                        "accept": "application/json",
                        "content-type": "application/json",
                    },
                    timeout=10,
                )
            except Exception:
                pass

            otp_resp = self.session.post(
                f"{AUTH_BASE}/api/accounts/email-otp/validate",
                headers={
                    "referer": f"{AUTH_BASE}/email-verification",
                    "accept": "application/json",
                    "content-type": "application/json",
                    "openai-sentinel-token": login_sentinel,
                },
                data=json.dumps({"code": otp_code}),
                timeout=30,
            )
            if otp_resp.status_code != 200:
                raise RuntimeError(
                    f"Log in twice OTP fail: HTTP {otp_resp.status_code} {otp_resp.text[:200]}"
                )
            self._log("Login second verification passed")

        self._log("OAuth Login process completed")
        return login_oauth

    # ══════════════════════════════════════════════════════════════════
    # step 10: parsing workspace_id
    # ══════════════════════════════════════════════════════════════════

    def extract_workspace_id(self) -> str:
        """from oai-client-auth-session Cookie(JWT) parsed in workspace_id."""
        auth_cookie = self.session.cookies.get("oai-client-auth-session") or ""
        if not auth_cookie:
            raise RuntimeError("not found oai-client-auth-session Cookie")

        # JWT Segment traversal (workspace Probably in the first or second paragraph)
        segments = auth_cookie.split(".")
        for i in range(min(len(segments), 2)):
            data = _decode_jwt_segment(segments[i])
            workspaces = data.get("workspaces") or []
            if workspaces:
                wid = str((workspaces[0] or {}).get("id") or "").strip()
                if wid:
                    self._log(f"Parsed successfully workspace_id: {wid}")
                    return wid

        # debugging information
        first_data = _decode_jwt_segment(segments[0]) if segments else {}
        self._log(f"Cookie Field: {list(first_data.keys())}")
        raise RuntimeError("Unable to access from Cookie Medium parsing workspace_id")

    # ══════════════════════════════════════════════════════════════════
    # step 11:choose workspace
    # ══════════════════════════════════════════════════════════════════

    def select_workspace(self, workspace_id: str) -> str:
        """choose workspace,return continue_url."""
        self._log(f"choose workspace: {workspace_id}")

        resp = self.session.post(
            f"{AUTH_BASE}/api/accounts/workspace/select",
            headers={
                "referer": f"{AUTH_BASE}/sign-in-with-chatgpt/codex/consent",
                "content-type": "application/json",
            },
            data=json.dumps({"workspace_id": workspace_id}),
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"workspace/select fail: HTTP {resp.status_code} {resp.text[:300]}"
            )

        continue_url = str((resp.json() or {}).get("continue_url") or "").strip()
        if not continue_url:
            raise RuntimeError("workspace/select Response missing continue_url")
        self._log("workspace Choose success,continue_url Obtained")
        return continue_url

    # ══════════════════════════════════════════════════════════════════
    # step 12: Track redirect chains, exchanges OAuth code → access_token
    # ══════════════════════════════════════════════════════════════════

    def follow_redirects_and_exchange_token(
        self, continue_url: str, oauth_start: OAuthStart
    ) -> dict:
        """Follow redirect chain, capture code= callback URL,exchange access_token."""
        current_url = continue_url

        for hop in range(8):
            resp = self.session.get(current_url, allow_redirects=False, timeout=15)
            location = resp.headers.get("Location") or ""

            if resp.status_code not in (301, 302, 303, 307, 308) or not location:
                break

            next_url = urllib.parse.urljoin(current_url, location)
            self._log(f"Redirect [{hop + 1}] → {next_url[:100]}...")

            if "code=" in next_url and "state=" in next_url:
                self._log("captured OAuth callback URL,exchange Token...")
                token_json = submit_callback_url(
                    callback_url=next_url,
                    expected_state=oauth_start.state,
                    code_verifier=oauth_start.code_verifier,
                    redirect_uri=oauth_start.redirect_uri,
                    proxy_url=self.proxy,
                )
                return json.loads(token_json)

            current_url = next_url

        raise RuntimeError("Failed to catch in redirect chain OAuth callback URL(Including code= parameter)")
