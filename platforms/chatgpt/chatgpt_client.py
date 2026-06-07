"""
ChatGPT Register client module
use curl_cffi Simulate browser behavior
"""

import random
import uuid
import time
from urllib.parse import urlparse
from core.proxy_utils import build_requests_proxy_config

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    print("[FAIL] Requires installation curl_cffi: pip install curl_cffi")
    import sys

    sys.exit(1)

from .sentinel_token import build_sentinel_token
from .sentinel_browser import get_sentinel_token_via_browser
from .utils import (
    FlowState,
    build_browser_headers,
    decode_jwt_payload,
    describe_flow_state,
    extract_flow_state,
    generate_datadog_trace,
    normalize_flow_url,
    random_delay,
    seed_oai_device_cookie,
)


# Chrome Fingerprint configuration
_CHROME_PROFILES = [
    {
        "major": 131,
        "impersonate": "chrome131",
        "build": 6778,
        "patch_range": (69, 205),
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    },
    {
        "major": 133,
        "impersonate": "chrome133a",
        "build": 6943,
        "patch_range": (33, 153),
        "sec_ch_ua": '"Not(A:Brand";v="99", "Google Chrome";v="133", "Chromium";v="133"',
    },
    {
        "major": 136,
        "impersonate": "chrome136",
        "build": 7103,
        "patch_range": (48, 175),
        "sec_ch_ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    },
]


def _random_chrome_version():
    """randomly select one Chrome Version"""
    profile = random.choice(_CHROME_PROFILES)
    major = profile["major"]
    build = profile["build"]
    patch = random.randint(*profile["patch_range"])
    full_ver = f"{major}.0.{build}.{patch}"
    ua = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{full_ver} Safari/537.36"
    return profile["impersonate"], major, full_ver, ua, profile["sec_ch_ua"]


class ChatGPTClient:
    """ChatGPT Register client"""

    BASE = "https://chatgpt.com"
    AUTH = "https://auth.openai.com"

    def __init__(self, proxy=None, verbose=True, browser_mode="protocol"):
        """
        initialization ChatGPT client

        Args:
            proxy: proxy address
            verbose: Whether to output detailed logs
            browser_mode: protocol | headless | headed
        """
        self.proxy = proxy
        self.verbose = verbose
        self.browser_mode = browser_mode or "protocol"
        self.device_id = str(uuid.uuid4())
        self.accept_language = random.choice(
            [
                "en-US,en;q=0.9",
                "en-US,en;q=0.9,zh-CN;q=0.8",
                "en,en-US;q=0.9",
                "en-US,en;q=0.8",
            ]
        )

        # random Chrome Version
        (
            self.impersonate,
            self.chrome_major,
            self.chrome_full,
            self.ua,
            self.sec_ch_ua,
        ) = _random_chrome_version()

        # create session
        self.session = curl_requests.Session(impersonate=self.impersonate)

        if self.proxy:
            self.session.proxies = build_requests_proxy_config(self.proxy)

        # Setting the Basics headers
        self.session.headers.update(
            {
                "User-Agent": self.ua,
                "Accept-Language": self.accept_language,
                "sec-ch-ua": self.sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-ch-ua-arch": '"x86"',
                "sec-ch-ua-bitness": '"64"',
                "sec-ch-ua-full-version": f'"{self.chrome_full}"',
                "sec-ch-ua-platform-version": f'"{random.randint(10, 15)}.0.0"',
            }
        )

        # set up oai-did cookie
        seed_oai_device_cookie(self.session, self.device_id)
        self.last_registration_state = FlowState()
        self.last_stage = ""

    def _get_sentinel_token(self, flow: str, *, page_url: str | None = None):
        prefer_browser = flow in {"username_password_create", "oauth_create_account"}
        if prefer_browser:
            token = get_sentinel_token_via_browser(
                flow=flow,
                proxy=self.proxy,
                page_url=page_url,
                headless=self.browser_mode != "headed",
                device_id=self.device_id,
                log_fn=lambda msg: self._log(msg),
            )
            if token:
                self._log(f"{flow}: Passed Playwright SentinelSDK get token")
                return token

        token = build_sentinel_token(
            self.session,
            self.device_id,
            flow=flow,
            user_agent=self.ua,
            sec_ch_ua=self.sec_ch_ua,
            impersonate=self.impersonate,
        )
        if token:
            self._log(f"{flow}: Passed HTTP PoW get token")
        return token

    def _log(self, msg):
        """Output log"""
        if self.verbose:
            print(f"  {msg}")

    def _enter_stage(self, stage: str, detail: str = ""):
        self.last_stage = str(stage or "").strip()
        if self.last_stage:
            message = f"[stage={self.last_stage}]"
            if detail:
                message += f" {detail}"
            self._log(message)

    def _browser_pause(self, low=0.15, high=0.45):
        """exist headed Add a slight pause in the mode to simulate the rhythm of a head browser."""
        if self.browser_mode == "headed":
            random_delay(low, high)

    def _headers(
        self,
        url,
        *,
        accept,
        referer=None,
        origin=None,
        content_type=None,
        navigation=False,
        fetch_mode=None,
        fetch_dest=None,
        fetch_site=None,
        extra_headers=None,
    ):
        return build_browser_headers(
            url=url,
            user_agent=self.ua,
            sec_ch_ua=self.sec_ch_ua,
            chrome_full_version=self.chrome_full,
            accept=accept,
            accept_language=self.accept_language,
            referer=referer,
            origin=origin,
            content_type=content_type,
            navigation=navigation,
            fetch_mode=fetch_mode,
            fetch_dest=fetch_dest,
            fetch_site=fetch_site,
            headed=self.browser_mode == "headed",
            extra_headers=extra_headers,
        )

    def _reset_session(self):
        """Reset browser fingerprint and session to bypass occasional Cloudflare/SPA Middle page."""
        self.device_id = str(uuid.uuid4())
        (
            self.impersonate,
            self.chrome_major,
            self.chrome_full,
            self.ua,
            self.sec_ch_ua,
        ) = _random_chrome_version()
        self.accept_language = random.choice(
            [
                "en-US,en;q=0.9",
                "en-US,en;q=0.9,zh-CN;q=0.8",
                "en,en-US;q=0.9",
                "en-US,en;q=0.8",
            ]
        )

        self.session = curl_requests.Session(impersonate=self.impersonate)
        if self.proxy:
            self.session.proxies = build_requests_proxy_config(self.proxy)

        self.session.headers.update(
            {
                "User-Agent": self.ua,
                "Accept-Language": self.accept_language,
                "sec-ch-ua": self.sec_ch_ua,
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-ch-ua-arch": '"x86"',
                "sec-ch-ua-bitness": '"64"',
                "sec-ch-ua-full-version": f'"{self.chrome_full}"',
                "sec-ch-ua-platform-version": f'"{random.randint(10, 15)}.0.0"',
            }
        )
        seed_oai_device_cookie(self.session, self.device_id)

    def _state_from_url(self, url, method="GET"):
        state = extract_flow_state(
            current_url=normalize_flow_url(url, auth_base=self.AUTH),
            auth_base=self.AUTH,
            default_method=method,
        )
        if method:
            state.method = str(method).upper()
        return state

    def _state_from_payload(self, data, current_url=""):
        return extract_flow_state(
            data=data,
            current_url=current_url,
            auth_base=self.AUTH,
        )

    def _state_signature(self, state: FlowState):
        return (
            state.page_type or "",
            state.method or "",
            state.continue_url or "",
            state.current_url or "",
        )

    def _is_registration_complete_state(self, state: FlowState):
        current_url = (state.current_url or "").lower()
        continue_url = (state.continue_url or "").lower()
        page_type = state.page_type or ""
        return (
            page_type in {"callback", "chatgpt_home", "oauth_callback"}
            or ("chatgpt.com" in current_url and "redirect_uri" not in current_url)
            or (
                "chatgpt.com" in continue_url
                and "redirect_uri" not in continue_url
                and page_type != "external_url"
            )
        )

    def _state_is_password_registration(self, state: FlowState):
        return state.page_type in {"create_account_password", "password"}

    def _state_is_email_otp(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return (
            state.page_type == "email_otp_verification"
            or "email-verification" in target
            or "email-otp" in target
        )

    def _state_is_about_you(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return state.page_type == "about_you" or "about-you" in target

    def _state_requires_navigation(self, state: FlowState):
        if (state.method or "GET").upper() != "GET":
            return False
        if state.page_type == "external_url" and state.continue_url:
            return True
        if state.continue_url and state.continue_url != state.current_url:
            return True
        return False

    def _follow_flow_state(self, state: FlowState, referer=None):
        """Following the return from the server continue_url, advance the registration state machine."""
        target_url = state.continue_url or state.current_url
        if not target_url:
            return False, "lack to follow continue_url"

        try:
            self._browser_pause()
            r = self.session.get(
                target_url,
                headers=self._headers(
                    target_url,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=referer,
                    navigation=True,
                ),
                allow_redirects=True,
                timeout=30,
            )
            final_url = str(r.url)
            self._log(f"follow -> {r.status_code} {final_url}")

            content_type = (r.headers.get("content-type", "") or "").lower()
            if "application/json" in content_type:
                try:
                    next_state = self._state_from_payload(
                        r.json(), current_url=final_url
                    )
                except Exception:
                    next_state = self._state_from_url(final_url)
            else:
                next_state = self._state_from_url(final_url)

            self._log(f"follow state -> {describe_flow_state(next_state)}")
            return True, next_state
        except Exception as e:
            self._log(f"follow continue_url fail: {e}")
            return False, str(e)

    def _get_cookie_value(self, name, domain_hint=None):
        """Read the current session Cookie."""
        for cookie in self.session.cookies.jar:
            if cookie.name != name:
                continue
            if domain_hint and domain_hint not in (cookie.domain or ""):
                continue
            return cookie.value
        return ""

    def get_next_auth_session_token(self):
        """get ChatGPT next-auth session Cookie."""
        return (
            self._get_cookie_value("__Secure-next-auth.session-token", "chatgpt.com")
            or self._get_cookie_value("__Secure-authjs.session-token", "chatgpt.com")
        )

    def fetch_chatgpt_session(self, max_attempts=5, retry_delay=1.2):
        """ask ChatGPT Session interface and returns raw session data."""
        url = f"{self.BASE}/api/auth/session"
        last_error = ""

        for attempt in range(max(1, int(max_attempts or 1))):
            try:
                self._browser_pause()
                response = self.session.get(
                    url,
                    headers=self._headers(
                        url,
                        accept="application/json",
                        referer=f"{self.BASE}/",
                        fetch_site="same-origin",
                    ),
                    timeout=30,
                )
            except Exception as exc:
                last_error = f"/api/auth/session Request exception: {exc}"
                if attempt < max_attempts - 1:
                    self._log(
                        f"{last_error},wait {retry_delay:.1f}s Try again later "
                        f"({attempt + 1}/{max_attempts})"
                    )
                    time.sleep(retry_delay)
                    continue
                return False, last_error

            if response.status_code != 200:
                last_error = f"/api/auth/session -> HTTP {response.status_code}"
                if attempt < max_attempts - 1:
                    self._log(
                        f"{last_error},wait {retry_delay:.1f}s Try again later "
                        f"({attempt + 1}/{max_attempts})"
                    )
                    time.sleep(retry_delay)
                    continue
                return False, last_error

            try:
                data = response.json()
            except Exception as exc:
                last_error = f"/api/auth/session Return non JSON: {exc}"
                if attempt < max_attempts - 1:
                    self._log(
                        f"{last_error},wait {retry_delay:.1f}s Try again later "
                        f"({attempt + 1}/{max_attempts})"
                    )
                    time.sleep(retry_delay)
                    continue
                return False, last_error

            access_token = str(data.get("accessToken") or "").strip()
            if access_token:
                return True, data

            last_error = "/api/auth/session Not returned accessToken"
            if attempt < max_attempts - 1:
                self._log(
                    f"{last_error},wait {retry_delay:.1f}s Try again later "
                    f"({attempt + 1}/{max_attempts})"
                )
                try:
                    self.session.get(
                        f"{self.BASE}/",
                        headers=self._headers(
                            f"{self.BASE}/",
                            accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                            referer=f"{self.BASE}/",
                            navigation=True,
                        ),
                        allow_redirects=True,
                        timeout=30,
                    )
                except Exception:
                    pass
                time.sleep(retry_delay)
                continue

            return False, last_error

        return False, last_error or "/api/auth/session Not returned accessToken"

    def reuse_session_and_get_tokens(self):
        """
        Take over what has been established in the pre-procedure stage ChatGPT Session, read directly Session / AccessToken.

        Returns:
            tuple[bool, dict|str]: Return normalized on success token/session Data; returns an error message on failure.
        """
        self._enter_stage("token_exchange", "reuse session -> /api/auth/session")
        state = self.last_registration_state or FlowState()
        self._log("step 1/4: Follow the registration callback external_url ...")
        if state.page_type == "external_url" or self._state_requires_navigation(state):
            ok, followed = self._follow_flow_state(
                state,
                referer=state.current_url or f"{self.AUTH}/about-you",
            )
            if not ok:
                return False, f"Registration callback failed: {followed}"
            self.last_registration_state = followed
        else:
            self._log("The registration callback has been implemented, skip the additional follow-up")

        self._log("step 2/4: examine __Secure-next-auth.session-token ...")
        session_cookie = ""
        for attempt in range(5):
            session_cookie = self.get_next_auth_session_token()
            if session_cookie:
                break
            self._log(
                f"next-auth session cookie Not implemented yet, please make up for it once ChatGPT Home page reach "
                f"({attempt + 1}/5)"
            )
            try:
                self._browser_pause(0.2, 0.5)
                self.session.get(
                    f"{self.BASE}/",
                    headers=self._headers(
                        f"{self.BASE}/",
                        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        referer=state.current_url or f"{self.AUTH}/about-you",
                        navigation=True,
                    ),
                    allow_redirects=True,
                    timeout=30,
                )
            except Exception as exc:
                self._log(f"Complementary touch ChatGPT Home page exception: {exc}")
            time.sleep(1.0)
        if not session_cookie:
            return False, "Lack ChatGPT session-token, the registration callback may not be fully implemented."

        self._log("step 3/4: ask ChatGPT /api/auth/session ...")
        ok, session_or_error = self.fetch_chatgpt_session()
        if not ok:
            return False, session_or_error

        session_data = session_or_error
        access_token = str(session_data.get("accessToken") or "").strip()
        session_token = str(
            session_data.get("sessionToken") or session_cookie or ""
        ).strip()
        user = session_data.get("user") or {}
        account = session_data.get("account") or {}
        jwt_payload = decode_jwt_payload(access_token)
        auth_payload = jwt_payload.get("https://api.openai.com/auth") or {}

        account_id = (
            str(account.get("id") or "").strip()
            or str(auth_payload.get("chatgpt_account_id") or "").strip()
        )
        user_id = (
            str(user.get("id") or "").strip()
            or str(auth_payload.get("chatgpt_user_id") or "").strip()
            or str(auth_payload.get("user_id") or "").strip()
        )

        normalized = {
            "access_token": access_token,
            "session_token": session_token,
            "account_id": account_id,
            "user_id": user_id,
            "workspace_id": account_id,
            "expires": session_data.get("expires"),
            "user": user,
            "account": account,
            "auth_provider": session_data.get("authProvider"),
            "raw_session": session_data,
        }

        self._log("step 4/4: Fetched from current session accessToken")
        if account_id:
            self._log(f"Session Account ID: {account_id}")
        if user_id:
            self._log(f"Session User ID: {user_id}")
        return True, normalized

    def visit_homepage(self):
        """Visit the homepage and create session"""
        self._log("access ChatGPT front page...")
        url = f"{self.BASE}/"
        try:
            self._browser_pause()
            r = self.session.get(
                url,
                headers=self._headers(
                    url,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    navigation=True,
                ),
                allow_redirects=True,
                timeout=30,
            )
            return r.status_code == 200
        except Exception as e:
            self._log(f"Failed to access home page: {e}")
            return False

    def get_csrf_token(self):
        """get CSRF token"""
        self._log("get CSRF token...")
        url = f"{self.BASE}/api/auth/csrf"
        try:
            r = self.session.get(
                url,
                headers=self._headers(
                    url,
                    accept="application/json",
                    referer=f"{self.BASE}/",
                    fetch_site="same-origin",
                ),
                timeout=30,
            )

            if r.status_code == 200:
                data = r.json()
                token = data.get("csrfToken", "")
                if token:
                    self._log(f"CSRF token: {token[:20]}...")
                    return token
        except Exception as e:
            self._log(f"get CSRF token fail: {e}")

        return None

    def signin(self, email, csrf_token):
        """
        Submit your email and get authorize URL

        Returns:
            str: authorize URL
        """
        self._log(f"Submit email: {email}")
        url = f"{self.BASE}/api/auth/signin/openai"

        params = {
            "prompt": "login",
            "ext-oai-did": self.device_id,
            "auth_session_logging_id": str(uuid.uuid4()),
            "screen_hint": "login_or_signup",
            "login_hint": email,
        }

        form_data = {
            "callbackUrl": f"{self.BASE}/",
            "csrfToken": csrf_token,
            "json": "true",
        }

        try:
            self._browser_pause()
            r = self.session.post(
                url,
                params=params,
                data=form_data,
                headers=self._headers(
                    url,
                    accept="application/json",
                    referer=f"{self.BASE}/",
                    origin=self.BASE,
                    content_type="application/x-www-form-urlencoded",
                    fetch_site="same-origin",
                ),
                timeout=30,
            )

            if r.status_code == 200:
                data = r.json()
                authorize_url = data.get("url", "")
                if authorize_url:
                    self._log(f"Get authorize URL")
                    return authorize_url
        except Exception as e:
            self._log(f"Failed to submit email: {e}")

        return None

    def authorize(self, url, max_retries=3):
        """
        access authorize URL, follow the redirect (with retry mechanism)
        This is the key step to establish auth.openai.com of session

        Returns:
            str: ultimately redirected URL
        """
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self._log(
                        f"access authorize URL... (try {attempt + 1}/{max_retries})"
                    )
                    time.sleep(1)  # Wait before retrying
                else:
                    self._log("access authorize URL...")

                self._browser_pause()
                r = self.session.get(
                    url,
                    headers=self._headers(
                        url,
                        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        referer=f"{self.BASE}/",
                        navigation=True,
                    ),
                    allow_redirects=True,
                    timeout=30,
                )

                final_url = str(r.url)
                self._log(f"redirect to: {final_url}")
                return final_url

            except Exception as e:
                error_msg = str(e)
                is_tls_error = (
                    "TLS" in error_msg
                    or "SSL" in error_msg
                    or "curl: (35)" in error_msg
                )

                if is_tls_error and attempt < max_retries - 1:
                    self._log(
                        f"Authorize TLS mistake (try {attempt + 1}/{max_retries}): {error_msg[:100]}"
                    )
                    continue
                else:
                    self._log(f"Authorize fail: {e}")
                    return ""

        return ""

    def callback(self, callback_url=None, referer=None):
        """Complete registration callback"""
        self._log("Execute callback...")
        url = callback_url or f"{self.AUTH}/api/accounts/authorize/callback"
        ok, _ = self._follow_flow_state(
            self._state_from_url(url),
            referer=referer or f"{self.AUTH}/about-you",
        )
        return ok

    def register_user(self, email, password):
        """
        Registered user (email + password)

        Returns:
            tuple: (success, message)
        """
        self._enter_stage("authorize_continue", f"register_user email={email}")
        self._log(f"Registered user: {email}")
        url = f"{self.AUTH}/api/accounts/user/register"

        headers = self._headers(
            url,
            accept="application/json",
            referer=f"{self.AUTH}/create-account/password",
            origin=self.AUTH,
            content_type="application/json",
            fetch_site="same-origin",
        )
        headers.update(generate_datadog_trace())
        headers["oai-device-id"] = self.device_id

        sentinel_token = self._get_sentinel_token(
            "username_password_create",
            page_url=f"{self.AUTH}/create-account/password",
        )
        if sentinel_token:
            headers["openai-sentinel-token"] = sentinel_token

        payload = {
            "username": email,
            "password": password,
        }

        try:
            self._browser_pause()
            r = self.session.post(url, json=payload, headers=headers, timeout=30)

            if r.status_code == 200:
                data = r.json()
                self._log("Registration successful")
                self._log(f"authorize_continue/register_user response URL: {str(r.url)[:120]}")
                return True, "Registration successful"
            else:
                try:
                    error_data = r.json()
                    error_msg = error_data.get("error", {}).get("message", r.text[:200])
                except:
                    error_msg = r.text[:200]
                self._log(f"Registration failed: {r.status_code} - {error_msg}")
                return False, f"HTTP {r.status_code}: {error_msg}"

        except Exception as e:
            self._log(f"Registration exception: {e}")
            return False, str(e)

    def send_email_otp(self, referer=None):
        """Trigger sending email verification code"""
        self._enter_stage("otp", "send email otp")
        self._log("Trigger sending verification code...")
        url = f"{self.AUTH}/api/accounts/email-otp/send"

        try:
            self._browser_pause()
            r = self.session.get(
                url,
                headers=self._headers(
                    url,
                    accept="application/json, text/plain, */*",
                    referer=referer or f"{self.AUTH}/create-account/password",
                    fetch_site="same-origin",
                    extra_headers={"oai-device-id": self.device_id},
                ),
                allow_redirects=True,
                timeout=30,
            )
            self._log(f"Verification code sending status: {r.status_code}")
            if r.status_code != 200:
                self._log(f"Verification code sending failed response: {r.text[:180]}")
                return False

            try:
                payload = r.json()
            except Exception:
                payload = {}

            if isinstance(payload, dict) and payload:
                next_state = self._state_from_payload(payload, current_url=str(r.url) or url)
                self._log(f"Verification code sending response: {describe_flow_state(next_state)}")
                self._log(f"otp/send current URL: {str(r.url)[:120]}")
            else:
                self._log("Verification code sending response: No JSON(processed as triggered)")
            return True
        except Exception as e:
            self._log(f"Failed to send verification code: {e}")
            return False

    def verify_email_otp(self, otp_code, return_state=False):
        """
        Verify email OTP code

        Args:
            otp_code: 6Verification code

        Returns:
            tuple: (success, message)
        """
        self._enter_stage("otp", f"verify email otp code={otp_code}")
        self._log(f"verify OTP code: {otp_code}")
        url = f"{self.AUTH}/api/accounts/email-otp/validate"

        sentinel_token = self._get_sentinel_token(
            "email_otp_validate",
            page_url=f"{self.AUTH}/email-verification",
        )

        extra = {"oai-device-id": self.device_id}
        if sentinel_token:
            extra["openai-sentinel-token"] = sentinel_token

        headers = self._headers(
            url,
            accept="application/json",
            referer=f"{self.AUTH}/email-verification",
            origin=self.AUTH,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers=extra,
        )
        headers.update(generate_datadog_trace())

        payload = {"code": otp_code}

        try:
            self._browser_pause()
            r = self.session.post(url, json=payload, headers=headers, timeout=30)

            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    data = {}
                next_state = self._state_from_payload(
                    data, current_url=str(r.url) or f"{self.AUTH}/about-you"
                )
                self._log(f"Verification successful {describe_flow_state(next_state)}")
                self._log(f"otp/validate current URL: {str(r.url)[:120]}")
                return (True, next_state) if return_state else (True, "Verification successful")
            else:
                error_msg = r.text[:200]
                self._log(f"Authentication failed: {r.status_code} - {error_msg}")
                return False, f"HTTP {r.status_code}"

        except Exception as e:
            self._log(f"Validation exception: {e}")
            return False, str(e)

    def create_account(self, first_name, last_name, birthdate, return_state=False):
        """
        Complete account creation (submit name and birthday)

        Args:
            first_name: name
            last_name: surname
            birthdate: Birthday (YYYY-MM-DD)

        Returns:
            tuple: (success, message)
        """
        self._enter_stage("about_you", "register create_account")
        name = f"{first_name} {last_name}"
        self._log(f"Complete account creation: {name}")
        url = f"{self.AUTH}/api/accounts/create_account"

        sentinel_token = self._get_sentinel_token(
            "oauth_create_account",
            page_url=f"{self.AUTH}/about-you",
        )
        if sentinel_token:
            self._log("create_account: Generated sentinel token")
        else:
            self._log("create_account: Not generated sentinel token, downgrade continuation request")

        headers = self._headers(
            url,
            accept="application/json",
            referer=f"{self.AUTH}/about-you",
            origin=self.AUTH,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": self.device_id,
            },
        )
        if sentinel_token:
            headers["openai-sentinel-token"] = sentinel_token
        headers.update(generate_datadog_trace())

        payload = {
            "name": name,
            "birthdate": birthdate,
        }

        try:
            self._browser_pause()
            r = self.session.post(url, json=payload, headers=headers, timeout=30)

            if r.status_code == 200:
                try:
                    data = r.json()
                except Exception:
                    data = {}
                next_state = self._state_from_payload(
                    data, current_url=str(r.url) or self.BASE
                )
                self._log(f"Account created successfully {describe_flow_state(next_state)}")
                self._log(f"about_you/create_account current URL: {str(r.url)[:120]}")
                return (True, next_state) if return_state else (True, "Account created successfully")
            else:
                error_code = ""
                error_msg = r.text[:200]
                try:
                    error_data = r.json() or {}
                    error_info = error_data.get("error") or {}
                    error_code = str(error_info.get("code") or "").strip()
                    error_msg = str(error_info.get("message") or error_msg).strip()
                except Exception:
                    pass

                detail = f"HTTP {r.status_code}"
                if error_code:
                    detail += f": {error_code}"
                elif error_msg:
                    detail += f": {error_msg}"

                self._log(f"Creation failed: {detail} - {error_msg[:200]}")
                if self.browser_mode != "protocol" and (r.status_code == 403 or "cloudflare" in error_msg.lower() or "challenge" in error_msg.lower()):
                    self._log("Trigger browser fallback to submit about-you details...")
                    success, b_state = self._browser_submit_create_account(first_name, last_name, birthdate)
                    if success:
                        return (True, b_state) if return_state else (True, "Account created successfully")
                    else:
                        return False, f"Browser fallback failed: {b_state}"
                return False, detail

        except Exception as e:
            self._log(f"Create exception: {e}")
            if self.browser_mode != "protocol":
                self._log("Trigger browser fallback on create exception...")
                success, b_state = self._browser_submit_create_account(first_name, last_name, birthdate)
                if success:
                    return (True, b_state) if return_state else (True, "Account created successfully")
                else:
                    return False, f"Browser fallback failed: {b_state}"
            return False, str(e)

    def _browser_submit_create_account(self, first_name, last_name, birthdate):
        """Submit name and birthdate via Playwright browser context"""
        from playwright.sync_api import sync_playwright
        from core.browser_runtime import resolve_browser_headless, ensure_browser_display_available
        from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile
        import json

        headless = self.browser_mode != "headed"
        effective_headless, reason = resolve_browser_headless(headless)
        ensure_browser_display_available(effective_headless)

        launch_args = {
            "headless": effective_headless,
            "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        }
        proxy_config = build_playwright_proxy_config(self.proxy)
        if proxy_config:
            launch_args["proxy"] = proxy_config

        us_loc = resolve_us_profile(self.proxy)

        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_args)
            try:
                context = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    user_agent=self.ua,
                    locale=us_loc["locale"],
                    timezone_id=us_loc["timezone"],
                    geolocation={"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
                    permissions=["geolocation"],
                    ignore_https_errors=True,
                )

                # Copy cookies from curl_cffi session to Playwright context
                playwright_cookies = []
                for cookie in self.session.cookies:
                    domain = cookie.domain
                    if not domain.startswith("."):
                        domain = "." + domain
                    playwright_cookies.append({
                        "name": cookie.name,
                        "value": cookie.value,
                        "domain": domain,
                        "path": cookie.path,
                        "secure": True,
                        "sameSite": "Lax",
                    })
                context.add_cookies(playwright_cookies)

                page = context.new_page()
                target_url = f"{self.AUTH}/about-you"
                self._log(f"Navigating browser to: {target_url}")
                page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

                # Wait for inputs to become visible
                first_name_sel = 'input[name="firstName"], input[placeholder*="First"], input[type="text"]'
                page.wait_for_selector(first_name_sel, timeout=15000)

                # Fill details
                page.fill('input[placeholder*="First"], input[name="firstName"]', first_name)
                page.fill('input[placeholder*="Last"], input[name="lastName"]', last_name)
                page.fill('input[type="date"], input[placeholder*="YYYY"], input[name="birthday"]', birthdate)

                # Click submit
                submit_btn = 'button[type="submit"], button:has-text("Continue"), button:has-text("Submit")'
                page.click(submit_btn)

                # Wait for redirect
                page.wait_for_timeout(5000)

                # Retrieve updated cookies and sync them back to self.session
                updated_cookies = context.cookies()
                for c in updated_cookies:
                    self.session.cookies.set(
                        c["name"],
                        c["value"],
                        domain=c["domain"],
                        path=c["path"],
                    )

                final_url = page.url
                self._log(f"Browser redirected to: {final_url}")
                state = self._state_from_url(final_url)
                return True, state

            except Exception as e:
                self._log(f"Browser fallback exception: {e}")
                return False, str(e)
            finally:
                browser.close()


    def register_complete_flow(
        self,
        email,
        password,
        first_name,
        last_name,
        birthdate,
        skymail_client,
        stop_before_about_you_submission=False,
        otp_wait_timeout=600,
        otp_resend_wait_timeout=300,
    ):
        """
        Complete registration process (based on the original run_register method)

        Args:
            email: Mail
            password: password
            first_name: name
            last_name: surname
            birthdate: Birthday
            skymail_client: Skymail Client (used to obtain verification code)

        Returns:
            tuple: (success, message)
        """
        from urllib.parse import urlparse

        self._log(
            "Register state machine parameters: "
            f"stop_before_about_you_submission={'on' if stop_before_about_you_submission else 'off'}, "
            f"otp_wait_timeout={otp_wait_timeout}s, otp_resend_wait_timeout={otp_resend_wait_timeout}s"
        )

        try:
            otp_wait_timeout = max(30, int(otp_wait_timeout or 600))
        except Exception:
            otp_wait_timeout = 600
        try:
            otp_resend_wait_timeout = max(30, int(otp_resend_wait_timeout or 300))
        except Exception:
            otp_resend_wait_timeout = 300

        max_auth_attempts = 3
        final_url = ""
        final_path = ""

        for auth_attempt in range(max_auth_attempts):
            if auth_attempt > 0:
                self._log(f"Pre-authorization phase retry {auth_attempt + 1}/{max_auth_attempts}...")
                self._reset_session()

            # 1. Visit home page
            if not self.visit_homepage():
                if auth_attempt < max_auth_attempts - 1:
                    continue
                return False, "Failed to access home page"

            # 2. get CSRF token
            csrf_token = self.get_csrf_token()
            if not csrf_token:
                if auth_attempt < max_auth_attempts - 1:
                    continue
                return False, "get CSRF token fail"

            # 3. Submit your email and get authorize URL
            auth_url = self.signin(email, csrf_token)
            if not auth_url:
                if auth_attempt < max_auth_attempts - 1:
                    continue
                return False, "Failed to submit email"

            # 4. access authorize URL(Critical step!)
            final_url = self.authorize(auth_url)
            if not final_url:
                if auth_attempt < max_auth_attempts - 1:
                    continue
                return False, "Authorize fail"

            final_path = urlparse(final_url).path
            self._log(f"Authorize -> {final_path}")

            # /api/accounts/authorize In fact, it often corresponds to Cloudflare 403 Middle page, don’t continue walking authorize_continue.
            if "api/accounts/authorize" in final_path or final_path == "/error":
                self._log(
                    f"detected Cloudflare/SPA Intermediate page, ready to retry pre-authorization: {final_url[:160]}..."
                )
                if auth_attempt < max_auth_attempts - 1:
                    continue
                return False, f"Pre-authorization blocked: {final_path}"

            break

        state = self._state_from_url(final_url)
        self._log(f"Registration status starting point: {describe_flow_state(state)}")

        register_submitted = False
        otp_verified = False
        account_created = False
        seen_states = {}

        otp_send_attempts = 0

        for _ in range(12):
            signature = self._state_signature(state)
            seen_states[signature] = seen_states.get(signature, 0) + 1
            self._log(
                f"Registration status advancement: step={sum(seen_states.values())} "
                f"state={describe_flow_state(state)} seen={seen_states[signature]}"
            )
            if seen_states[signature] > 2:
                return False, f"Registration status stuck: {describe_flow_state(state)}"

            if self._is_registration_complete_state(state):
                self.last_registration_state = state
                self._log("[OK] Registration process completed")
                return True, "Registration successful"

            if self._state_is_password_registration(state):
                self._enter_stage("authorize_continue", describe_flow_state(state))
                self._log("New registration process")
                if register_submitted:
                    return False, "Repeated entry during the password registration phase"
                success, msg = self.register_user(email, password)
                if not success:
                    return False, f"Registration failed: {msg}"
                register_submitted = True
                otp_send_attempts += 1
                self._log(f"Send registration verification code: attempt={otp_send_attempts}")
                if not self.send_email_otp(
                    referer=state.current_url or state.continue_url or f"{self.AUTH}/create-account/password"
                ):
                    self._log("The interface for sending the verification code returns failure and continues to wait for the verification code in the mailbox....")
                else:
                    self._log("The registration verification code is sent successfully and the code collection stage is entered.")
                state = self._state_from_url(f"{self.AUTH}/email-verification")
                continue

            if self._state_is_email_otp(state):
                self._enter_stage("otp", describe_flow_state(state))
                self._log("Waiting for email verification code...")
                otp_code = skymail_client.wait_for_verification_code(
                    email, timeout=otp_wait_timeout
                )
                if not otp_code:
                    self._log(
                        "If the verification code is not received after waiting for the first time, try to resend it again. email-otp/send "
                        f"wait later {otp_resend_wait_timeout}s"
                    )
                    otp_send_attempts += 1
                    resend_ok = self.send_email_otp(
                        referer=state.current_url or state.continue_url or f"{self.AUTH}/email-verification"
                    )
                    if resend_ok:
                        self._log(f"Resend verification code successfully: attempt={otp_send_attempts}")
                    else:
                        self._log(f"Failed to resend verification code: attempt={otp_send_attempts}")
                    otp_code = skymail_client.wait_for_verification_code(
                        email, timeout=otp_resend_wait_timeout
                    )
                if not otp_code:
                    return False, "Verification code not received"

                success, next_state = self.verify_email_otp(otp_code, return_state=True)
                if not success:
                    return False, f"Verification code failed: {next_state}"
                otp_verified = True
                state = next_state
                self.last_registration_state = state
                continue

            if self._state_is_about_you(state):
                self._enter_stage("about_you", describe_flow_state(state))
                if stop_before_about_you_submission:
                    self.last_registration_state = state
                    self._log(
                        "Registration link has arrived about_you,according to interrupt The process stops."
                        "Next step is handed over to OAuth New session submission name+Birthday."
                    )
                    return True, "pending_about_you_submission"
                if account_created:
                    return False, "Repeat the filling in information stage"
                success, next_state = self.create_account(
                    first_name,
                    last_name,
                    birthdate,
                    return_state=True,
                )
                if not success:
                    return False, f"Failed to create account: {next_state}"
                account_created = True
                state = next_state
                self.last_registration_state = state
                continue

            if self._state_requires_navigation(state):
                if "workspace" in f"{state.continue_url} {state.current_url}".lower() or "consent" in f"{state.continue_url} {state.current_url}".lower():
                    self._enter_stage("workspace_select", describe_flow_state(state))
                elif state.page_type == "external_url":
                    self._enter_stage("token_exchange", describe_flow_state(state))
                success, next_state = self._follow_flow_state(
                    state,
                    referer=state.current_url or f"{self.AUTH}/about-you",
                )
                if not success:
                    return False, f"Jump failed: {next_state}"
                state = next_state
                self.last_registration_state = state
                continue

            if (
                (not register_submitted)
                and (not otp_verified)
                and (not account_created)
            ):
                self._log(
                    f"Unknown starting status, falling back to a new registration process: {describe_flow_state(state)}"
                )
                state = self._state_from_url(f"{self.AUTH}/create-account/password")
                continue

            return False, f"Unsupported registration status: {describe_flow_state(state)}"

        return False, "Registered state machine exceeds maximum number of steps"
