"""
OAuth client module - deal with Codex OAuth Login process
"""

import time
import secrets
import uuid
import json
import random
from urllib.parse import urlparse, parse_qs
from core.proxy_utils import build_requests_proxy_config
from core.task_runtime import TaskInterruption

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    import requests as curl_requests

from .phone_service import SMSToMePhoneService
from .smspool_service import SMSPoolPhoneService
from .utils import (
    FlowState,
    build_browser_headers,
    describe_flow_state,
    extract_flow_state,
    generate_datadog_trace,
    generate_pkce,
    normalize_flow_url,
    random_delay,
    seed_oai_device_cookie,
)
from .sentinel_token import build_sentinel_token
from .sentinel_browser import get_sentinel_token_via_browser


class OAuthClient:
    """OAuth client - used to get Access Token and Refresh Token"""

    def __init__(self, config, proxy=None, verbose=True, browser_mode="protocol"):
        """
        initialization OAuth client

        Args:
            config: Configuration dictionary
            proxy: proxy address
            verbose: Whether to output detailed logs
            browser_mode: protocol | headless | headed
        """
        self.config = dict(config or {})
        self.oauth_issuer = self.config.get("oauth_issuer", "https://auth.openai.com")
        self.oauth_client_id = self.config.get(
            "oauth_client_id", "app_EMoamEEZ73f0CkXaXp7hrann"
        )
        self.oauth_redirect_uri = self.config.get(
            "oauth_redirect_uri", "http://localhost:1455/auth/callback"
        )
        self.proxy = proxy
        self.verbose = verbose
        self.browser_mode = browser_mode or "protocol"
        self.last_error = ""
        self.last_workspace_id = ""
        self.last_state = FlowState()
        self.last_stage = ""
        self.device_id = ""
        self.ua = ""
        self.sec_ch_ua = ""
        self.impersonate = ""

        # create session
        self.session = curl_requests.Session(verify=False)
        if self.proxy:
            self.session.proxies = build_requests_proxy_config(self.proxy)

    def adopt_browser_context(
        self,
        session,
        *,
        device_id: str = "",
        user_agent: str | None = None,
        sec_ch_ua: str | None = None,
        accept_language: str | None = None,
    ):
        """Inherit the previous browser context and continue the established cookie / session."""
        if session is not None:
            self.session = session

        if self.proxy:
            try:
                if not getattr(self.session, "proxies", None):
                    self.session.proxies = build_requests_proxy_config(self.proxy)
            except Exception:
                pass

        header_updates = {}
        if user_agent:
            header_updates["User-Agent"] = user_agent
        if sec_ch_ua:
            header_updates["sec-ch-ua"] = sec_ch_ua
        if accept_language:
            header_updates["Accept-Language"] = accept_language

        if header_updates:
            try:
                self.session.headers.update(header_updates)
            except Exception:
                pass

        if device_id:
            self.device_id = str(device_id or "").strip()
            seed_oai_device_cookie(self.session, device_id)
            self._log(f"Accessed preorder browser context: device_id={device_id}")
        if user_agent:
            self.ua = str(user_agent or "").strip()
        if sec_ch_ua:
            self.sec_ch_ua = str(sec_ch_ua or "").strip()

    def _log(self, msg):
        """Output log"""
        if self.verbose:
            print(f"  [OAuth] {msg}")

    def _enter_stage(self, stage: str, detail: str = ""):
        self.last_stage = str(stage or "").strip()
        if self.last_stage:
            message = f"[stage={self.last_stage}]"
            if detail:
                message += f" {detail}"
            self._log(message)

    def _set_error(self, message):
        raw_message = str(message or "").strip()
        if self.last_stage and raw_message and f"[stage={self.last_stage}]" not in raw_message:
            self.last_error = f"[stage={self.last_stage}] {raw_message}"
        else:
            self.last_error = raw_message
        if self.last_error:
            self._log(self.last_error)

    def _browser_pause(self, low=0.15, high=0.4):
        """exist headed Mode injects a slight delay to simulate the rhythm of real browser operation."""
        if self.browser_mode == "headed":
            random_delay(low, high)

    @staticmethod
    def _random_chrome_fingerprint():
        profiles = [
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
        profile = random.choice(profiles)
        major = profile["major"]
        build = profile["build"]
        patch = random.randint(*profile["patch_range"])
        full_ver = f"{major}.0.{build}.{patch}"
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{full_ver} Safari/537.36"
        )
        return ua, profile["sec_ch_ua"], profile["impersonate"]

    def _ensure_oauth_fingerprint(self, user_agent, sec_ch_ua, impersonate):
        if user_agent and sec_ch_ua and impersonate:
            return user_agent, sec_ch_ua, impersonate

        ua, ch_ua, imp = self._random_chrome_fingerprint()
        user_agent = user_agent or ua
        sec_ch_ua = sec_ch_ua or ch_ua
        impersonate = impersonate or imp
        self.ua = str(user_agent or "").strip()
        self.sec_ch_ua = str(sec_ch_ua or "").strip()
        self.impersonate = str(impersonate or "").strip()

        try:
            self.session.headers.update(
                {
                    "User-Agent": user_agent,
                    "Accept-Language": random.choice(
                        [
                            "en-US,en;q=0.9",
                            "en-US,en;q=0.9,zh-CN;q=0.8",
                            "en,en-US;q=0.9",
                            "en-US,en;q=0.8",
                        ]
                    ),
                    "sec-ch-ua": sec_ch_ua,
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "sec-ch-ua-arch": '"x86"',
                    "sec-ch-ua-bitness": '"64"',
                }
            )
        except Exception:
            pass

        self._log(
            f"OAuth fingerprint: ua={user_agent.split('Chrome/')[-1][:24]}..., sec-ch-ua={sec_ch_ua}, impersonate={impersonate}"
        )
        return user_agent, sec_ch_ua, impersonate


    @staticmethod
    def _iter_text_fragments(value):
        if isinstance(value, str):
            text = value.strip()
            if text:
                yield text
            return
        if isinstance(value, dict):
            for item in value.values():
                yield from OAuthClient._iter_text_fragments(item)
            return
        if isinstance(value, (list, tuple, set)):
            for item in value:
                yield from OAuthClient._iter_text_fragments(item)

    @classmethod
    def _should_blacklist_phone_failure(cls, detail="", state: FlowState | None = None):
        fragments = [str(detail or "").strip()]
        if state is not None:
            fragments.extend(
                cls._iter_text_fragments(
                    {
                        "page_type": state.page_type,
                        "continue_url": state.continue_url,
                        "current_url": state.current_url,
                        "payload": state.payload,
                        "raw": state.raw,
                    }
                )
            )

        combined = " | ".join(fragment for fragment in fragments if fragment).lower()
        if not combined:
            return False

        non_blacklist_markers = (
            "whatsapp",
            "Did not receive SMS verification code",
            "Mobile phone number verification code is wrong",
            "phone-otp/resend",
            "phone-otp/validate abnormal",
            "phone-otp/validate The response is not json",
            "phone-otp/validate fail",
            "timeout",
            "timed out",
            "network",
            "connection",
            "proxy",
            "ssl",
            "tls",
            "captcha",
            "too many phone",
            "too many phone numbers",
            "too many verification requests",
            "Too many verification requests",
            "Received too many text messages",
            "session limit",
            "rate limit",
        )
        if any(marker in combined for marker in non_blacklist_markers):
            return False

        blacklist_markers = (
            "phone number is invalid",
            "invalid phone number",
            "invalid phone",
            "phone number invalid",
            "sms verification failed",
            "send sms verification failed",
            "unable to send sms",
            "not a valid mobile number",
            "unsupported phone number",
            "phone number not supported",
            "carrier not supported",
            "Invalid phone number",
            "Invalid mobile number",
            "Sending SMS verification failed",
            "Invalid number",
            "Number not supported",
            "Mobile phone number is not supported",
        )
        return any(marker in combined for marker in blacklist_markers)

    @classmethod
    def _is_otp_network_error(cls, detail=""):
        msg = str(detail or "").lower()
        if not msg:
            return False
        markers = (
            "connect tunnel failed",
            "tunnel connection failed",
            "connection refused",
            "couldn't connect",
            "could not connect",
            "recv failure",
            "failed to perform",
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "proxy",
            "ssl",
            "tls",
            "no route",
            "host unreachable",
            "broken pipe",
        )
        return any(marker in msg for marker in markers)

    def _blacklist_phone_if_needed(
        self, phone_service, entry, detail="", state: FlowState | None = None
    ):
        if not entry or not self._should_blacklist_phone_failure(detail, state):
            return False
        try:
            phone_service.mark_blacklisted(entry.phone)
            self._log(f"Mobile phone number has been added to the blacklist: {entry.phone}")
            return True
        except Exception as e:
            self._log(f"Failed to write mobile phone number blacklist: {e}")
            return False

    def _headers(
        self,
        url,
        *,
        user_agent=None,
        sec_ch_ua=None,
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
        accept_language = None
        try:
            accept_language = self.session.headers.get("Accept-Language")
        except Exception:
            accept_language = None

        return build_browser_headers(
            url=url,
            user_agent=user_agent or "Mozilla/5.0",
            sec_ch_ua=sec_ch_ua,
            accept=accept,
            accept_language=accept_language or "en-US,en;q=0.9",
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

    def _state_from_url(self, url, method="GET"):
        state = extract_flow_state(
            current_url=normalize_flow_url(url, auth_base=self.oauth_issuer),
            auth_base=self.oauth_issuer,
            default_method=method,
        )
        if method:
            state.method = str(method).upper()
        return state

    def _state_from_payload(self, data, current_url=""):
        return extract_flow_state(
            data=data,
            current_url=current_url,
            auth_base=self.oauth_issuer,
        )

    def _get_cookie_value(self, name, domain_hint=None):
        """Read the current session Cookie."""
        try:
            for cookie in self.session.cookies:
                cookie_name = cookie.name if hasattr(cookie, "name") else str(cookie)
                if cookie_name != name:
                    continue
                cookie_domain = cookie.domain if hasattr(cookie, "domain") else ""
                if domain_hint and domain_hint not in (cookie_domain or ""):
                    continue
                return cookie.value if hasattr(cookie, "value") else ""
        except Exception:
            pass
        return ""

    def _state_signature(self, state: FlowState):
        return (
            state.page_type or "",
            state.method or "",
            state.continue_url or "",
            state.current_url or "",
        )

    def _extract_code_from_state(self, state: FlowState):
        for candidate in (
            state.continue_url,
            state.current_url,
            (state.payload or {}).get("url", ""),
        ):
            code = self._extract_code_from_url(candidate)
            if code:
                return code
        return None

    def _state_is_login_password(self, state: FlowState):
        return state.page_type == "login_password"

    def _state_is_create_account_password(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return state.page_type == "create_account_password" or "create-account/password" in target

    def _state_is_email_otp(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return (
            state.page_type == "email_otp_verification"
            or "email-verification" in target
            or "email-otp" in target
        )

    def _state_is_add_phone(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return state.page_type == "add_phone" or "add-phone" in target

    def _state_is_about_you(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        return state.page_type == "about_you" or "about-you" in target

    def _state_requires_navigation(self, state: FlowState):
        method = (state.method or "GET").upper()
        if method != "GET":
            return False
        if (
            state.source == "api"
            and state.current_url
            and state.page_type not in {"login_password", "email_otp_verification"}
        ):
            return True
        if state.page_type == "external_url" and state.continue_url:
            return True
        if state.continue_url and state.continue_url != state.current_url:
            return True
        return False

    def _state_supports_workspace_resolution(self, state: FlowState):
        target = f"{state.continue_url} {state.current_url}".lower()
        if state.page_type in {
            "consent",
            "workspace_selection",
            "organization_selection",
        }:
            return True
        if any(
            marker in target
            for marker in (
                "sign-in-with-chatgpt",
                "consent",
                "workspace",
                "organization",
            )
        ):
            return True
        session_data = self._decode_oauth_session_cookie() or {}
        return bool(session_data.get("workspaces"))

    def _follow_flow_state(
        self,
        state: FlowState,
        referer=None,
        user_agent=None,
        impersonate=None,
        max_hops=16,
    ):
        """Following the return from the server continue_url / current_url, returns the new state or authorization code."""
        import re

        current_url = state.continue_url or state.current_url
        last_url = current_url or ""
        referer_url = referer

        if not current_url:
            return None, state

        initial_code = self._extract_code_from_url(current_url)
        if initial_code:
            return initial_code, self._state_from_url(current_url)

        for hop in range(max_hops):
            try:
                headers = self._headers(
                    current_url,
                    user_agent=user_agent,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=referer_url,
                    navigation=True,
                )
                kwargs = {"headers": headers, "allow_redirects": False, "timeout": 30}
                if impersonate:
                    kwargs["impersonate"] = impersonate

                self._browser_pause(0.12, 0.3)
                r = self.session.get(current_url, **kwargs)
                last_url = str(r.url)
                self._log(f"follow[{hop + 1}] {r.status_code} {last_url[:120]}")
            except Exception as e:
                maybe_localhost = re.search(r"(https?://localhost[^\s\'\"]+)", str(e))
                if maybe_localhost:
                    location = maybe_localhost.group(1)
                    code = self._extract_code_from_url(location)
                    if code:
                        self._log("from localhost Exception extracted to authorization code")
                        return code, self._state_from_url(location)
                self._log(f"follow[{hop + 1}] abnormal: {str(e)[:160]}")
                return None, self._state_from_url(last_url or current_url)

            code = self._extract_code_from_url(last_url)
            if code:
                return code, self._state_from_url(last_url)

            if r.status_code in (301, 302, 303, 307, 308):
                location = normalize_flow_url(
                    r.headers.get("Location", ""), auth_base=self.oauth_issuer
                )
                if not location:
                    return None, self._state_from_url(last_url or current_url)
                code = self._extract_code_from_url(location)
                if code:
                    return code, self._state_from_url(location)
                referer_url = last_url or referer_url
                current_url = location
                continue

            content_type = (r.headers.get("content-type", "") or "").lower()
            if "application/json" in content_type:
                try:
                    next_state = self._state_from_payload(
                        r.json(), current_url=last_url or current_url
                    )
                except Exception:
                    next_state = self._state_from_url(last_url or current_url)
            else:
                next_state = self._state_from_url(last_url or current_url)

            return None, next_state

        return None, self._state_from_url(last_url or current_url)

    def _bootstrap_oauth_session(
        self,
        authorize_url,
        authorize_params,
        device_id=None,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
    ):
        """start up OAuth session, make sure auth domain login_session Established."""
        if device_id:
            seed_oai_device_cookie(self.session, device_id)

        has_login_session = False
        authorize_final_url = ""

        try:
            headers = self._headers(
                authorize_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                referer="https://chatgpt.com/",
                navigation=True,
            )
            kwargs = {
                "params": authorize_params,
                "headers": headers,
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.get(authorize_url, **kwargs)
            authorize_final_url = str(r.url)
            redirects = len(getattr(r, "history", []) or [])
            self._log(f"/oauth/authorize -> {r.status_code}, redirects={redirects}")

            has_login_session = any(
                (cookie.name if hasattr(cookie, "name") else str(cookie))
                == "login_session"
                for cookie in self.session.cookies
            )
            self._log(f"login_session: {'Obtained' if has_login_session else 'Not obtained'}")
        except Exception as e:
            self._log(f"/oauth/authorize abnormal: {e}")

        if has_login_session:
            return authorize_final_url

        self._log("Not obtained login_session,try /api/oauth/oauth2/auth...")
        try:
            oauth2_url = f"{self.oauth_issuer}/api/oauth/oauth2/auth"
            kwargs = {
                "params": authorize_params,
                "headers": self._headers(
                    oauth2_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer="https://chatgpt.com/",
                    navigation=True,
                ),
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r2 = self.session.get(oauth2_url, **kwargs)
            authorize_final_url = str(r2.url)
            redirects2 = len(getattr(r2, "history", []) or [])
            self._log(
                f"/api/oauth/oauth2/auth -> {r2.status_code}, redirects={redirects2}"
            )

            has_login_session = any(
                (cookie.name if hasattr(cookie, "name") else str(cookie))
                == "login_session"
                for cookie in self.session.cookies
            )
            self._log(
                f"login_session(Try again): {'Obtained' if has_login_session else 'Not obtained'}"
            )
        except Exception as e:
            self._log(f"/api/oauth/oauth2/auth abnormal: {e}")

        return authorize_final_url

    def _bootstrap_chatgpt_entry(
        self,
        email: str,
        device_id: str,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
    ) -> str:
        """Simulate the registration link to be consistent ChatGPT front page -> CSRF -> signin/openai."""
        homepage_url = "https://chatgpt.com/"
        csrf_url = "https://chatgpt.com/api/auth/csrf"
        signin_url = "https://chatgpt.com/api/auth/signin/openai"

        try:
            self._log("force_chatgpt_entry: access ChatGPT front page...")
            self._browser_pause()
            r_home = self.session.get(
                homepage_url,
                headers=self._headers(
                    homepage_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    navigation=True,
                ),
                allow_redirects=True,
                timeout=30,
            )
            self._log(f"force_chatgpt_entry: Home page status {r_home.status_code}")
        except Exception as e:
            self._log(f"force_chatgpt_entry: Home page access abnormality: {e}")

        csrf_token = ""
        try:
            self._log("force_chatgpt_entry: get CSRF token...")
            r_csrf = self.session.get(
                csrf_url,
                headers=self._headers(
                    csrf_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="application/json",
                    referer=homepage_url,
                    fetch_site="same-origin",
                ),
                timeout=30,
            )
            if r_csrf.status_code == 200:
                csrf_token = (r_csrf.json() or {}).get("csrfToken", "") or ""
                if csrf_token:
                    self._log(f"force_chatgpt_entry: CSRF token={csrf_token[:16]}...")
        except Exception as e:
            self._log(f"force_chatgpt_entry: get CSRF abnormal: {e}")

        authorize_url = ""
        try:
            self._log("force_chatgpt_entry: Submit email to get authorize URL...")
            params = {
                "prompt": "login",
                "ext-oai-did": device_id,
                "auth_session_logging_id": str(uuid.uuid4()),
                "screen_hint": "login_or_signup",
                "login_hint": email,
            }
            form_data = {
                "callbackUrl": "https://chatgpt.com/",
                "csrfToken": csrf_token,
                "json": "true",
            }
            r_signin = self.session.post(
                signin_url,
                params=params,
                data=form_data,
                headers=self._headers(
                    signin_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="application/json",
                    referer=homepage_url,
                    origin="https://chatgpt.com",
                    content_type="application/x-www-form-urlencoded",
                    fetch_site="same-origin",
                ),
                timeout=30,
            )
            if r_signin.status_code == 200:
                authorize_url = (r_signin.json() or {}).get("url", "") or ""
                if authorize_url:
                    self._log("force_chatgpt_entry: Obtained authorize URL")
            else:
                self._log(
                    f"force_chatgpt_entry: authorize URL Failed to obtain {r_signin.status_code}"
                )
        except Exception as e:
            self._log(f"force_chatgpt_entry: Submit email exception: {e}")

        if not authorize_url:
            return ""

        try:
            self._log("force_chatgpt_entry: access authorize URL...")
            self._browser_pause()
            kwargs = {
                "headers": self._headers(
                    authorize_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    referer=homepage_url,
                    navigation=True,
                ),
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate
            r_auth = self.session.get(authorize_url, **kwargs)
            final_url = str(r_auth.url)
            self._log(
                f"force_chatgpt_entry: authorize final jump {final_url[:160]}"
            )
            return final_url
        except Exception as e:
            self._log(f"force_chatgpt_entry: access authorize abnormal: {e}")
            return authorize_url

    def _submit_authorize_continue(
        self,
        email,
        device_id,
        continue_referer,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        authorize_url=None,
        authorize_params=None,
        screen_hint=None,
    ):
        """Submit your email and get OAuth The first page status of the process."""
        self._enter_stage("authorize_continue", f"email={email}")
        self._log("step2: POST /api/accounts/authorize/continue")

        self._log(f"authorize_continue: device_id={device_id}")
        sentinel_token = None
        for _sentinel_attempt in range(2):
            sentinel_token = get_sentinel_token_via_browser(
                flow="authorize_continue",
                proxy=self.proxy,
                page_url=continue_referer or f"{self.oauth_issuer}/log-in",
                headless=self.browser_mode != "headed",
                device_id=device_id,
                log_fn=lambda msg: self._log(f"authorize_continue: {msg}"),
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
            )
            if sentinel_token:
                self._log("authorize_continue: Passed Playwright SentinelSDK get token")
                break
            sentinel_token = build_sentinel_token(
                self.session,
                device_id,
                flow="authorize_continue",
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                impersonate=impersonate,
            )
            if sentinel_token:
                self._log("authorize_continue: Passed HTTP PoW get token")
                break
            if _sentinel_attempt == 0:
                self._log("authorize_continue: sentinel token Failed to obtain, try again...")
        if not sentinel_token:
            self._set_error("Unable to obtain sentinel token (authorize_continue)")
            return None

        request_url = f"{self.oauth_issuer}/api/accounts/authorize/continue"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=continue_referer,
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
                "openai-sentinel-token": sentinel_token,
            },
        )
        headers.update(generate_datadog_trace())
        payload = {"username": {"kind": "email", "value": email}}
        if screen_hint:
            payload["screen_hint"] = str(screen_hint).strip()

        try:
            kwargs = {
                "json": payload,
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(request_url, **kwargs)
            self._log(f"/authorize/continue -> {r.status_code}")
            self._log(
                "authorize_continue response: "
                f"referer={(continue_referer or '')[:100]} "
                f"current_url={str(r.url)[:120]}"
            )

            if (
                r.status_code == 400
                and "invalid_auth_step" in (r.text or "")
                and authorize_url
                and authorize_params
            ):
                self._log("invalid_auth_step,again bootstrap...")
                authorize_final_url = self._bootstrap_oauth_session(
                    authorize_url,
                    authorize_params,
                    device_id=device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                )
                continue_referer = (
                    authorize_final_url
                    if authorize_final_url.startswith(self.oauth_issuer)
                    else f"{self.oauth_issuer}/log-in"
                )
                headers["Referer"] = continue_referer
                headers["Sec-Fetch-Site"] = "same-origin"
                headers.update(generate_datadog_trace())
                kwargs = {
                    "json": payload,
                    "headers": headers,
                    "timeout": 30,
                    "allow_redirects": False,
                }
                if impersonate:
                    kwargs["impersonate"] = impersonate
                self._browser_pause()
                r = self.session.post(request_url, **kwargs)
                self._log(f"/authorize/continue(Try again) -> {r.status_code}")

            if r.status_code != 200:
                self._set_error(f"Failed to submit email: {r.status_code} - {r.text[:180]}")
                return None

            data = r.json()
            flow_state = self._state_from_payload(
                data, current_url=str(r.url) or request_url
            )
            self._log(describe_flow_state(flow_state))
            return flow_state
        except Exception as e:
            self._set_error(f"Submit email exception: {e}")
            return None

    def _submit_password_verify(
        self,
        password,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """Submit the password and get the next step status."""
        self._log("step3: POST /api/accounts/password/verify")

        self._log(f"password_verify: device_id={device_id}")
        sentinel_pwd = get_sentinel_token_via_browser(
            flow="password_verify",
            proxy=self.proxy,
            page_url=referer or f"{self.oauth_issuer}/log-in/password",
            headless=self.browser_mode != "headed",
            device_id=device_id,
            log_fn=lambda msg: self._log(f"password_verify: {msg}"),
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
        )
        if sentinel_pwd:
            self._log("password_verify: Passed Playwright SentinelSDK get token")
        else:
            sentinel_pwd = build_sentinel_token(
                self.session,
                device_id,
                flow="password_verify",
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                impersonate=impersonate,
            )
            if sentinel_pwd:
                self._log("password_verify: Passed HTTP PoW get token")
            else:
                self._set_error("Unable to obtain sentinel token (password_verify)")
                return None

        request_url = f"{self.oauth_issuer}/api/accounts/password/verify"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=referer or f"{self.oauth_issuer}/log-in/password",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
                "openai-sentinel-token": sentinel_pwd,
            },
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"password": password},
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(request_url, **kwargs)
            self._log(f"/password/verify -> {r.status_code}")

            if r.status_code != 200:
                self._set_error(f"Password verification failed: {r.status_code} - {r.text[:180]}")
                return None

            data = r.json()
            flow_state = self._state_from_payload(
                data, current_url=str(r.url) or request_url
            )
            self._log(f"verify {describe_flow_state(flow_state)}")
            return flow_state
        except Exception as e:
            self._set_error(f"Password verification exception: {e}")
            return None

    def _send_passwordless_login_otp(
        self,
        email,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """exist login_password Cut directly to passwordless OTP."""
        self._log("step3: hit login_password, trigger directly by pressing the new link passwordless OTP")

        request_url = f"{self.oauth_issuer}/api/accounts/passwordless/send-otp"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=referer or f"{self.oauth_issuer}/log-in/password",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
            },
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(request_url, **kwargs)
            self._log(f"/passwordless/send-otp -> {r.status_code}")

            if r.status_code != 200:
                self._set_error(f"trigger passwordless OTP fail: {r.status_code} - {r.text[:180]}")
                return None

            try:
                data = r.json()
            except Exception:
                data = {}

            flow_state = self._state_from_payload(
                data,
                current_url=str(r.url) or f"{self.oauth_issuer}/email-verification",
            )
            if not self._state_is_email_otp(flow_state):
                flow_state = self._state_from_url(f"{self.oauth_issuer}/email-verification")
            self._log(f"passwordless OTP Triggered {describe_flow_state(flow_state)}")
            return flow_state
        except Exception as e:
            self._set_error(f"trigger passwordless OTP abnormal: {e}")
            return None

    def _submit_signup_register(
        self,
        email,
        password,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """exist OAuth signup Submit email during the process+password."""
        self._enter_stage("authorize_continue", f"register_user email={email}")
        self._log("step3: hit create_account_password, submit the registration password")

        request_url = f"{self.oauth_issuer}/api/accounts/user/register"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=referer or f"{self.oauth_issuer}/create-account/password",
            content_type="application/json",
        )
        headers.update(generate_datadog_trace())

        sentinel_token = get_sentinel_token_via_browser(
            flow="username_password_create",
            proxy=self.proxy,
            page_url=referer or f"{self.oauth_issuer}/create-account/password",
            headless=self.browser_mode != "headed",
            device_id=device_id,
            log_fn=lambda msg: self._log(f"username_password_create: {msg}"),
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
        )
        if sentinel_token:
            self._log("username_password_create: Passed Playwright SentinelSDK get token")
        else:
            sentinel_token = build_sentinel_token(
                self.session,
                device_id,
                flow="username_password_create",
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                impersonate=impersonate,
            )
            if sentinel_token:
                self._log("username_password_create: Passed HTTP PoW get token")
        if sentinel_token:
            headers["openai-sentinel-token"] = sentinel_token

        payload = {
            "username": email,
            "password": password,
        }

        try:
            kwargs = {
                "data": json.dumps(payload),
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(request_url, **kwargs)
            self._log(f"/user/register -> {r.status_code}")

            if r.status_code != 200:
                self._set_error(f"Registration failed: {r.status_code} - {r.text[:180]}")
                return False

            self._log("Registration successful")
            self._log(
                f"signup/register response: referer={(referer or '')[:100]} current_url={str(r.url)[:120]}"
            )
            return True
        except Exception as e:
            self._set_error(f"Registration exception: {e}")
            return False

    def _send_signup_email_otp(
        self,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """exist OAuth signup An email verification code is triggered during the process."""
        self._enter_stage("otp", "send signup email otp")
        self._log("step4: Trigger registration email OTP")

        request_url = f"{self.oauth_issuer}/api/accounts/email-otp/send"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            referer=referer or f"{self.oauth_issuer}/create-account/password",
            navigation=True,
            fetch_site="same-origin",
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "headers": headers,
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.get(request_url, **kwargs)
            self._log(f"/email-otp/send -> {r.status_code}")
            if r.status_code != 200:
                self._set_error(f"Send registration OTP fail: {r.status_code} - {r.text[:180]}")
                return None

            verify_url = f"{self.oauth_issuer}/email-verification"
            verify_headers = self._headers(
                verify_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                referer=referer or f"{self.oauth_issuer}/create-account/password",
                navigation=True,
            )
            verify_kwargs = {
                "headers": verify_headers,
                "allow_redirects": True,
                "timeout": 30,
            }
            if impersonate:
                verify_kwargs["impersonate"] = impersonate

            self._browser_pause(0.12, 0.25)
            r_verify = self.session.get(verify_url, **verify_kwargs)
            self._log(f"/email-verification -> {r_verify.status_code}")

            content_type = (r_verify.headers.get("content-type", "") or "").lower()
            if "application/json" in content_type:
                try:
                    flow_state = self._state_from_payload(
                        r_verify.json(),
                        current_url=str(r_verify.url) or verify_url,
                    )
                except Exception:
                    flow_state = self._state_from_url(str(r_verify.url) or verify_url)
            else:
                flow_state = self._state_from_url(str(r_verify.url) or verify_url)

            if not self._state_is_email_otp(flow_state):
                flow_state = self._state_from_url(verify_url)
            self._log(f"register OTP Triggered {describe_flow_state(flow_state)}")
            return flow_state
        except Exception as e:
            self._set_error(f"Send registration OTP abnormal: {e}")
            return None

    def signup_and_get_tokens(
        self,
        email,
        password,
        first_name,
        last_name,
        birthdate,
        *,
        device_id="",
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        skymail_client=None,
        allow_phone_verification=False,
        signup_source="",
    ):
        """Finish OAuth Single chain registration and exchange refresh token."""
        self.last_error = ""
        self.last_workspace_id = ""
        self.last_state = FlowState()
        self._log(
            "start OAuth Registration process..."
            + (f" (source={signup_source})" if signup_source else "")
        )
        self._log(
            "OAuth Registration strategy: single link signup -> otp -> about_you -> phone(If required) -> consent/workspace -> token"
        )

        if not skymail_client:
            self._set_error("OAuth The registration process lacks a code receiving client")
            return None

        device_id = str(device_id or "").strip() or str(uuid.uuid4())
        self.device_id = device_id
        user_agent, sec_ch_ua, impersonate = self._ensure_oauth_fingerprint(
            user_agent, sec_ch_ua, impersonate
        )

        code_verifier, code_challenge = generate_pkce()
        oauth_state = secrets.token_urlsafe(32)
        authorize_params = {
            "response_type": "code",
            "client_id": self.oauth_client_id,
            "audience": "https://api.openai.com/v1",
            "redirect_uri": self.oauth_redirect_uri,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": oauth_state,
            "prompt": "login",
            "login_hint": email,
            "screen_hint": "login_or_signup",
            "ext-oai-did": device_id,
            "auth_session_logging_id": str(uuid.uuid4()),
            "ext-passkey-client-capabilities": "1111",
            "codex_cli_simplified_flow": "true",
            "id_token_add_organizations": "true",
        }
        authorize_url = f"{self.oauth_issuer}/oauth/authorize"

        seed_oai_device_cookie(self.session, device_id)

        self._log("step1: Bootstrap OAuth session...")
        authorize_final_url = self._bootstrap_oauth_session(
            authorize_url,
            authorize_params,
            device_id=device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
        )
        if not authorize_final_url:
            self._set_error("Bootstrap fail")
            return None

        continue_referer = f"{self.oauth_issuer}/create-account"
        state = self._submit_authorize_continue(
            email,
            device_id,
            continue_referer,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            authorize_url=authorize_url,
            authorize_params=authorize_params,
            screen_hint="signup",
        )
        if not state:
            if not self.last_error:
                self._set_error("After submitting the email, no valid entry was entered. OAuth Registration status")
            return None

        self._log(f"OAuth Registration status starting point: {describe_flow_state(state)}")
        referer = continue_referer
        seen_states = {}
        register_submitted = False

        for step in range(24):
            self.last_state = state
            self._log(f"Registration status step[{step + 1}/24]: {describe_flow_state(state)}")
            signature = self._state_signature(state)
            seen_states[signature] = seen_states.get(signature, 0) + 1
            if seen_states[signature] > 2:
                self._set_error(f"OAuth Registration status stuck: {describe_flow_state(state)}")
                return None

            code = self._extract_code_from_state(state)
            if code:
                self._log(f"Get authorization code: {code[:20]}...")
                self._log("step7: POST /oauth/token")
                tokens = self._exchange_code_for_tokens(
                    code, code_verifier, user_agent, impersonate
                )
                if tokens:
                    self._log("[OK] OAuth Registration successful")
                else:
                    self._log("exchange tokens fail")
                return tokens

            if self._state_is_create_account_password(state):
                if register_submitted:
                    self._set_error("Repeated entry during the password registration phase")
                    return None
                ok = self._submit_signup_register(
                    email,
                    password,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not ok:
                    return None
                register_submitted = True
                state = self._send_signup_email_otp(
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not state:
                    if not self.last_error:
                        self._set_error("register OTP Did not enter the email verification code state after triggering")
                    return None
                referer = state.current_url or referer
                continue

            if self._state_is_email_otp(state):
                next_state = self._handle_otp_verification(
                    email,
                    device_id,
                    user_agent,
                    sec_ch_ua,
                    impersonate,
                    skymail_client,
                    state,
                    prefer_passwordless_login=False,
                    allow_cached_code_retry=False,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("register OTP Did not enter the next step after verification")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_about_you(state):
                next_state = self._submit_about_you_create_account(
                    first_name,
                    last_name,
                    birthdate,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("about_you Did not proceed to the next step after submission OAuth state")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_add_phone(state):
                try:
                    raw_dump = json.dumps(state.raw or {}, ensure_ascii=False)
                except Exception:
                    raw_dump = ""
                if raw_dump:
                    self._log(f"add_phone status response body(raw): {raw_dump}")
                if not allow_phone_verification:
                    if not self.last_error:
                        self._set_error("signup link hit add_phone")
                    return None

                next_state = self._handle_add_phone_verification(
                    device_id,
                    user_agent,
                    sec_ch_ua,
                    impersonate,
                    state,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("Did not proceed to the next step after verifying the mobile phone number OAuth state")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_requires_navigation(state):
                code, next_state = self._follow_flow_state(
                    state,
                    referer=referer,
                    user_agent=user_agent,
                    impersonate=impersonate,
                )
                if code:
                    self._log(f"Get authorization code: {code[:20]}...")
                    self._log("step7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth Registration successful")
                    else:
                        self._log("exchange tokens fail")
                    return tokens
                referer = state.current_url or referer
                state = next_state
                self._log(f"follow state -> {describe_flow_state(state)}")
                continue

            if self._state_supports_workspace_resolution(state):
                self._log("step6: implement workspace/org choose")
                consent_entry = (
                    state.continue_url
                    or state.current_url
                    or f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                )
                if self._state_is_add_phone(state):
                    consent_entry = f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                    self._log("step6: Currently in add_phone, use canonical consent URL continue")
                code, next_state = self._oauth_submit_workspace_and_org(
                    consent_entry,
                    device_id,
                    user_agent,
                    impersonate,
                )
                if code:
                    self._log(f"Get authorization code: {code[:20]}...")
                    self._log("step7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth Registration successful")
                    else:
                        self._log("exchange tokens fail")
                    return tokens
                if next_state:
                    referer = state.current_url or referer
                    state = next_state
                    self._log(f"workspace state -> {describe_flow_state(state)}")
                    continue
                if not self.last_error:
                    self._set_error(f"workspace/org Selection failed: {describe_flow_state(state)}")
                return None

            self._set_error(f"Not supported OAuth Registration status: {describe_flow_state(state)}")
            return None

        self._set_error("OAuth Registered state machine exceeds maximum number of steps")
        return None

    def _submit_about_you_create_account(
        self,
        first_name,
        last_name,
        birthdate,
        device_id,
        *,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        referer=None,
    ):
        """exist OAuth Login status hit about_you Submit the information and complete the account creation."""
        self._enter_stage("about_you", "submit create_account")
        self._log("step5: hit about_you, submit your name and birthday to complete registration")
        self._log(
            "about_you parameter: "
            f"first_name={'Already set' if str(first_name or '').strip() else 'Missing'}, "
            f"last_name={'Already set' if str(last_name or '').strip() else 'Missing'}, "
            f"birthdate={str(birthdate or '').strip() or 'Missing'}"
        )

        full_name = f"{str(first_name or '').strip()} {str(last_name or '').strip()}".strip()
        if not full_name or not str(birthdate or "").strip():
            self._set_error("about_you Incomplete information: Missing name or birthday")
            return None

        about_you_url = f"{self.oauth_issuer}/about-you"
        request_url = f"{self.oauth_issuer}/api/accounts/create_account"
        payload = {
            "name": full_name,
            "birthdate": str(birthdate).strip(),
        }
        self._log("about_you The request body has been constructed and prepared POST /api/accounts/create_account")

        def _build_create_headers(sentinel_token: str = ""):
            extra_headers = {
                "oai-device-id": device_id,
            }
            if sentinel_token:
                extra_headers["openai-sentinel-token"] = sentinel_token
            headers_local = self._headers(
                request_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="application/json",
                referer=referer or about_you_url,
                origin=self.oauth_issuer,
                content_type="application/json",
                fetch_site="same-origin",
                extra_headers=extra_headers,
            )
            headers_local.update(generate_datadog_trace())
            return headers_local

        def _post_create(sentinel_token: str = ""):
            kwargs = {
                "json": payload,
                "headers": _build_create_headers(sentinel_token),
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate
            self._browser_pause()
            return self.session.post(request_url, **kwargs)

        try:
            r = _post_create()
            self._log(f"/create_account -> {r.status_code}")
            self._log(
                "about_you response: "
                f"current_url={str(r.url)[:120]} referer={(referer or '')[:100]}"
            )

            need_sentinel_retry = (
                r.status_code in (401, 403, 400)
                or "sentinel" in (r.text or "").lower()
                or "challenge" in (r.text or "").lower()
            )

            if need_sentinel_retry:
                self._log(f"create_account The first request requires additional challenge (HTTP {r.status_code}), acquiring sentinel token...")
                sentinel_token = build_sentinel_token(
                    self.session,
                    device_id,
                    flow="oauth_create_account",
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                )
                if not sentinel_token:
                    self._set_error("Unable to obtain sentinel token (oauth_create_account)")
                    return None

                r = _post_create(sentinel_token)
                self._log(f"/create_account(Try again) -> {r.status_code}")
                self._log(
                    "about_you Retry response: "
                    f"current_url={str(r.url)[:120]} referer={(referer or '')[:100]}"
                )

            if r.status_code == 400:
                error_lower = (r.text or "").lower()
                if "already_exists" in error_lower:
                    consent_state = self._state_from_url(
                        f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                    )
                    self._log(f"about_you hit already_exists, transfer to {describe_flow_state(consent_state)}")
                    return consent_state
                if "registration_" in error_lower or "cannot create" in error_lower:
                    # Account was already partially created by register_user flow.
                    # The OAuth session is reusing the existing account, so skip
                    # create_account and treat as already_exists.
                    consent_state = self._state_from_url(
                        f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                    )
                    self._log(f"about_you hit existing account (HTTP {r.status_code}), treating as already_exists, transferring to {describe_flow_state(consent_state)}")
                    return consent_state

            if r.status_code != 200:
                self._set_error(f"about_you Submission failed: {r.status_code} - {r.text[:180]}")
                return None

            try:
                data = r.json()
            except Exception:
                data = {}

            flow_state = self._state_from_payload(
                data,
                current_url=str(r.url) or request_url,
            )
            if self._state_is_add_phone(flow_state):
                try:
                    raw_text = r.text or ""
                except Exception:
                    raw_text = ""
                try:
                    raw_json = json.dumps(data, ensure_ascii=False)
                except Exception:
                    raw_json = ""
                if raw_text:
                    self._log("add_phone Trigger response body(raw): " + raw_text)
                if raw_json and raw_json != raw_text:
                    self._log("add_phone Trigger response body(json): " + raw_json)
            self._log(f"about_you Submission successful {describe_flow_state(flow_state)}")
            return flow_state
        except Exception as e:
            self._set_error(f"about_you Submit exception: {e}")
            return None

    def _recreate_session(self):
        """Re-create the session container."""
        self.session = curl_requests.Session(verify=False)
        if self.proxy:
            self.session.proxies = build_requests_proxy_config(self.proxy)

    def login_and_get_tokens(
        self,
        email,
        password,
        device_id,
        user_agent=None,
        sec_ch_ua=None,
        impersonate=None,
        skymail_client=None,
        prefer_passwordless_login=False,
        allow_phone_verification=True,
        force_new_browser=False,
        force_password_login=False,
        force_chatgpt_entry=False,
        screen_hint="login",
        complete_about_you_if_needed=False,
        first_name="",
        last_name="",
        birthdate="",
        login_source="",
        stop_after_login=False,
        _continue_depth=0,
    ):
        """
        complete OAuth Login process, get tokens

        Args:
            email: Mail
            password: password
            device_id: equipment ID
            user_agent: User-Agent
            sec_ch_ua: sec-ch-ua header
            impersonate: curl_cffi impersonate parameter
            skymail_client: Skymail Client (used to get OTP, if needed)
            prefer_passwordless_login: Is it forced to leave? passwordless OTP link
            allow_phone_verification: add_phone Whether to allow access to the mobile phone number verification code branch
            force_password_login: even though prefer_passwordless_login=true, and also force password login.
            force_chatgpt_entry: exist OAuth Go first ChatGPT front page -> CSRF -> signin/openai
            complete_about_you_if_needed: hit about_you Whether to automatically submit information to complete registration
            screen_hint: authorize/continue of screen_hint(login/signup)
            first_name: about_you name
            last_name: about_you Last name
            birthdate: about_you birthday, format YYYY-MM-DD
            login_source: Current login scenario, only used for logs

        Returns:
            dict: tokens dictionary, containing access_token, refresh_token, id_token
        """
        self.last_error = ""
        self.last_workspace_id = ""
        self.last_state = FlowState()
        self._log(
            "start OAuth Login process..."
            + (f" (source={login_source})" if login_source else "")
        )
        self._log(
            "OAuth Strategy: "
            f"prefer_passwordless_login={'on' if prefer_passwordless_login else 'off'}, "
            f"allow_phone_verification={'on' if allow_phone_verification else 'off'}, "
            f"complete_about_you_if_needed={'on' if complete_about_you_if_needed else 'off'}, "
            f"force_new_browser={'on' if force_new_browser else 'off'}, "
            f"force_password_login={'on' if force_password_login else 'off'}, "
            f"force_chatgpt_entry={'on' if force_chatgpt_entry else 'off'}, "
            f"screen_hint={screen_hint or 'login'}, "
            f"stop_after_login={'on' if stop_after_login else 'off'}"
        )

        if force_new_browser:
            self._log("force_new_browser: Recreate OAuth session container")
            self._recreate_session()
            device_id = str(uuid.uuid4())
            self._log(f"force_new_browser: new device_id={device_id}")
        else:
            if not device_id:
                device_id = str(uuid.uuid4())
                self._log(f"OAuth device_id Missing, a new one has been generated device_id={device_id}")
        self.device_id = str(device_id or "").strip()

        user_agent, sec_ch_ua, impersonate = self._ensure_oauth_fingerprint(
            user_agent, sec_ch_ua, impersonate
        )

        code_verifier, code_challenge = generate_pkce()
        oauth_state = secrets.token_urlsafe(32)
        authorize_params = {
            "response_type": "code",
            "client_id": self.oauth_client_id,
            "redirect_uri": self.oauth_redirect_uri,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": oauth_state,
        }
        authorize_url = f"{self.oauth_issuer}/oauth/authorize"

        seed_oai_device_cookie(self.session, device_id)

        if force_chatgpt_entry:
            self._log("force_chatgpt_entry: start up ChatGPT Home page link (does not affect OAuth PKCE)")
            _ = self._bootstrap_chatgpt_entry(
                email,
                device_id,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                impersonate=impersonate,
            )

        self._log("step1: Bootstrap OAuth session...")
        authorize_final_url = self._bootstrap_oauth_session(
            authorize_url,
            authorize_params,
            device_id=device_id,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
        )
        if not authorize_final_url:
            self._set_error("Bootstrap fail")
            return None

        continue_referer = (
            authorize_final_url
            if authorize_final_url.startswith(self.oauth_issuer)
            else f"{self.oauth_issuer}/log-in"
        )

        state = self._submit_authorize_continue(
            email,
            device_id,
            continue_referer,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            impersonate=impersonate,
            authorize_url=authorize_url,
            authorize_params=authorize_params,
            screen_hint=str(screen_hint or "login"),
        )
        if not state:
            if not self.last_error:
                self._set_error("After submitting the email, no valid entry was entered. OAuth state")
            return None

        self._log(f"OAuth state starting point: {describe_flow_state(state)}")
        seen_states = {}
        referer = continue_referer

        def _should_stop_after_login(state_to_check: FlowState):
            if not stop_after_login:
                return False
            if self._state_is_login_password(state_to_check):
                return False
            if self._state_is_email_otp(state_to_check):
                return False
            if self._state_is_create_account_password(state_to_check):
                return False
            return True

        for step in range(20):
            self.last_state = state
            self._log(f"state stepping[{step + 1}/20]: {describe_flow_state(state)}")
            signature = self._state_signature(state)
            seen_states[signature] = seen_states.get(signature, 0) + 1
            if seen_states[signature] > 2:
                self._set_error(f"OAuth Status stuck: {describe_flow_state(state)}")
                return None

            code = self._extract_code_from_state(state)
            if code:
                self._log(f"Get authorization code: {code[:20]}...")
                self._log("step7: POST /oauth/token")
                tokens = self._exchange_code_for_tokens(
                    code, code_verifier, user_agent, impersonate
                )
                if tokens:
                    self._log("[OK] OAuth Login successful")
                else:
                    self._log("exchange tokens fail")
                return tokens

            if prefer_passwordless_login and (not force_password_login) and self._state_is_login_password(state):
                next_state = self._send_passwordless_login_otp(
                    email,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("passwordless OTP Did not enter the email verification code state after triggering")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_create_account_password(state) and force_password_login:
                self._log("hit create_account_password, continue according to the forced password login path")
                next_state = self._submit_password_verify(
                    password,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or f"{self.oauth_issuer}/log-in/password",
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("Did not proceed to the next step after password verification OAuth state")
                    return None
                if _should_stop_after_login(next_state):
                    self._log(
                        "The login link is completed (enters the next state after password verification) and stops as required."
                    )
                    self.last_state = next_state
                    self._set_error("Login link completed, stopped as required")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_login_password(state):
                next_state = self._submit_password_verify(
                    password,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("Did not proceed to the next step after password verification OAuth state")
                    return None
                if _should_stop_after_login(next_state):
                    self._log(
                        "The login link is completed (enters the next state after password verification) and stops as required."
                    )
                    self.last_state = next_state
                    self._set_error("Login link completed, stopped as required")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if (
                prefer_passwordless_login
                and self._state_is_add_phone(state)
                and self._state_requires_navigation(state)
            ):
                self._log("step5: OTP hit later add_phone, first actually visit continue_url Seek re-signing workspace Cookie")
                code, next_state = self._follow_flow_state(
                    state,
                    referer=referer,
                    user_agent=user_agent,
                    impersonate=impersonate,
                )
                if code:
                    self._log(f"Get authorization code: {code[:20]}...")
                    self._log("step7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth Login successful")
                    else:
                        self._log("exchange tokens fail")
                    return tokens
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_email_otp(state):
                if not skymail_client:
                    self._set_error("The current process requires an email address OTP, but lacks the code receiving client")
                    return None
                next_state = self._handle_otp_verification(
                    email,
                    device_id,
                    user_agent,
                    sec_ch_ua,
                    impersonate,
                    skymail_client,
                    state,
                    prefer_passwordless_login=prefer_passwordless_login,
                    allow_cached_code_retry=_continue_depth > 0,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("Mail OTP Did not proceed to the next step after verification OAuth state")
                    return None
                if _should_stop_after_login(next_state):
                    self._log(
                        "Login link completed (OTP After verification, enter the next state) and stop as required."
                    )
                    self.last_state = next_state
                    self._set_error("Login link completed, stopped as required")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if complete_about_you_if_needed and self._state_is_about_you(state):
                self._log("step5: hit about_you,implement interrupt Completion and submission of information for new links")
                next_state = self._submit_about_you_create_account(
                    first_name,
                    last_name,
                    birthdate,
                    device_id,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    impersonate=impersonate,
                    referer=state.current_url or state.continue_url or referer,
                )
                if not next_state:
                    if not self.last_error:
                        self._set_error("about_you Did not proceed to the next step after submission OAuth state")
                    return None
                referer = state.current_url or referer
                state = next_state
                continue

            if self._state_is_add_phone(state):
                try:
                    raw_dump = json.dumps(state.raw or {}, ensure_ascii=False)
                except Exception:
                    raw_dump = ""
                if raw_dump:
                    self._log(f"add_phone status response body(raw): {raw_dump}")
                if not allow_phone_verification:
                    if self._state_supports_workspace_resolution(state):
                        self._log(
                            "step5: add_phone hit but detected workspace clues, keep trying workspace/org choose"
                        )
                    else:
                        self._log(
                            "step5: add_phone No explicit yet workspace clue, try first canonical consent URL rescue"
                        )
                    code, next_state = self._oauth_submit_workspace_and_org(
                        f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent",
                        device_id,
                        user_agent,
                        impersonate,
                    )
                    if code:
                        self._log(f"Get authorization code: {code[:20]}...")
                        self._log("step7: POST /oauth/token")
                        tokens = self._exchange_code_for_tokens(
                            code, code_verifier, user_agent, impersonate
                        )
                        if tokens:
                            self._log("[OK] OAuth Login successful")
                        else:
                            self._log("exchange tokens fail")
                        return tokens
                    if next_state:
                        referer = state.current_url or referer
                        state = next_state
                        self._log(f"add_phone -> workspace state -> {describe_flow_state(state)}")
                        continue

                    workspace_error = str(self.last_error or "").strip()
                    if prefer_passwordless_login and _continue_depth < 1:
                        self._log(
                            "step5: canonical consent Still haven't got it workspace/callback"
                            + (
                                f" ({workspace_error})"
                                if workspace_error
                                else ""
                            )
                            + ", restart a new OAuth session + new PKCE"
                        )
                        self._recreate_session()
                        return self.login_and_get_tokens(
                            email,
                            password,
                            device_id,
                            user_agent=user_agent,
                            sec_ch_ua=sec_ch_ua,
                            impersonate=impersonate,
                            skymail_client=skymail_client,
                            prefer_passwordless_login=prefer_passwordless_login,
                            allow_phone_verification=allow_phone_verification,
                            complete_about_you_if_needed=complete_about_you_if_needed,
                            first_name=first_name,
                            last_name=last_name,
                            birthdate=birthdate,
                            login_source=(
                                f"{login_source}:add_phone_continue"
                                if login_source
                                else "add_phone_continue"
                            ),
                            _continue_depth=_continue_depth + 1,
                        )
                    else:
                        self._set_error(
                            "passwordless Still stuck on after logging in add_phone, not obtained workspace / callback"
                            + (f" ({workspace_error})" if workspace_error else "")
                        )
                        return None
                else:
                    next_state = self._handle_add_phone_verification(
                        device_id,
                        user_agent,
                        sec_ch_ua,
                        impersonate,
                        state,
                    )
                    if not next_state:
                        if not self.last_error:
                            self._set_error("Did not proceed to the next step after verifying the mobile phone number OAuth state")
                        return None
                    referer = state.current_url or referer
                    state = next_state
                    continue

            if self._state_requires_navigation(state):
                code, next_state = self._follow_flow_state(
                    state,
                    referer=referer,
                    user_agent=user_agent,
                    impersonate=impersonate,
                )
                if code:
                    self._log(f"Get authorization code: {code[:20]}...")
                    self._log("step7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth Login successful")
                    else:
                        self._log("exchange tokens fail")
                    return tokens
                referer = state.current_url or referer
                state = next_state
                self._log(f"follow state -> {describe_flow_state(state)}")
                continue

            if self._state_supports_workspace_resolution(state):
                self._log("step6: implement workspace/org choose")
                consent_entry = (
                    state.continue_url
                    or state.current_url
                    or f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                )
                if self._state_is_add_phone(state):
                    consent_entry = (
                        f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent"
                    )
                    self._log("step6: Currently in add_phone, use canonical consent URL continue")
                code, next_state = self._oauth_submit_workspace_and_org(
                    consent_entry,
                    device_id,
                    user_agent,
                    impersonate,
                )
                if code:
                    self._log(f"Get authorization code: {code[:20]}...")
                    self._log("step7: POST /oauth/token")
                    tokens = self._exchange_code_for_tokens(
                        code, code_verifier, user_agent, impersonate
                    )
                    if tokens:
                        self._log("[OK] OAuth Login successful")
                    else:
                        self._log("exchange tokens fail")
                    return tokens
                if next_state:
                    referer = state.current_url or referer
                    state = next_state
                    self._log(f"workspace state -> {describe_flow_state(state)}")
                    continue

                if not self.last_error:
                    self._set_error(
                        f"workspace/org Selection failed: {describe_flow_state(state)}"
                    )
                return None

            self._set_error(f"Not supported OAuth state: {describe_flow_state(state)}")
            return None

        self._set_error("OAuth State machine exceeds maximum number of steps")
        return None

    def _extract_code_from_url(self, url):
        """from URL extracted from code"""
        if not url or "code=" not in url:
            return None
        try:
            return parse_qs(urlparse(url).query).get("code", [None])[0]
        except Exception:
            return None

    def _oauth_follow_for_code(
        self, start_url, referer, user_agent, impersonate, max_hops=16
    ):
        """follow URL get authorization code(Follow redirects manually)"""
        code, next_state = self._follow_flow_state(
            self._state_from_url(start_url),
            referer=referer,
            user_agent=user_agent,
            impersonate=impersonate,
            max_hops=max_hops,
        )
        return code, (next_state.current_url or next_state.continue_url or start_url)

    def _oauth_submit_workspace_and_org(
        self, consent_url, device_id, user_agent, impersonate, max_retries=3
    ):
        """submit workspace and organization Select (with retry)"""
        self._enter_stage("workspace_select", consent_url[:120] if consent_url else "")
        session_data = None

        for attempt in range(max_retries):
            session_data = self._load_workspace_session_data(
                consent_url=consent_url,
                user_agent=user_agent,
                impersonate=impersonate,
            )
            if session_data:
                break

            if attempt < max_retries - 1:
                self._log(
                    f"Unable to obtain consent session data (try {attempt + 1}/{max_retries})"
                )
                time.sleep(0.3)
            else:
                self._set_error("Unable to obtain consent session data")
                return None, None

        workspaces = session_data.get("workspaces", [])
        if not workspaces:
            self._set_error("session None workspace information")
            return None, None

        workspace_id = (workspaces[0] or {}).get("id")
        if not workspace_id:
            self._set_error("workspace_id is empty")
            return None, None

        self.last_workspace_id = str(workspace_id).strip()
        self._log(f"choose workspace: {workspace_id}")

        headers = self._headers(
            f"{self.oauth_issuer}/api/accounts/workspace/select",
            user_agent=user_agent,
            accept="application/json",
            referer=consent_url,
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={
                "oai-device-id": device_id,
            },
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"workspace_id": workspace_id},
                "headers": headers,
                "allow_redirects": False,
                "timeout": 30,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(
                f"{self.oauth_issuer}/api/accounts/workspace/select", **kwargs
            )

            self._log(f"workspace/select -> {r.status_code}")
            self._log(
                f"workspace/select ask: workspace_id={workspace_id} consent_url={consent_url[:120]}"
            )

            # Check redirects
            if r.status_code in (301, 302, 303, 307, 308):
                location = normalize_flow_url(
                    r.headers.get("Location", ""), auth_base=self.oauth_issuer
                )
                if "code=" in location:
                    code = self._extract_code_from_url(location)
                    if code:
                        self._log("from workspace/select Redirected to get code")
                        return code, self._state_from_url(location)
                if location:
                    return None, self._state_from_url(location)

            # Handle 400: consent acceptance may be required first
            if r.status_code == 400:
                try:
                    err_body = r.text[:500]
                except Exception:
                    err_body = ""
                
                is_duplicate = "duplicate" in err_body or "Organization already has a default project" in err_body
                
                if is_duplicate:
                    self._log("workspace/select returned duplicate/already has default project, ignoring and proceeding...")
                    # Strategy A: Try to follow the consent URL directly to see if it redirects to code
                    code, state = self._oauth_follow_for_code(
                        consent_url, f"{self.oauth_issuer}/about-you", user_agent, impersonate
                    )
                    if code:
                        self._log("Recovered code after duplicate workspace error via redirect follow")
                        return code, state
                    
                    # Strategy B: Try to call organization/select if we have an org_id
                    org_id = (workspaces[0] or {}).get("org_id") if workspaces else None
                    if not org_id and workspace_id:
                        # Fallback: assume workspace_id is also the org_id (common in some OpenAI flows)
                        org_id = workspace_id
                        
                    if org_id:
                        self._log(f"Attempting organization/select with org_id: {org_id}")
                        org_headers = self._headers(
                            f"{self.oauth_issuer}/api/accounts/organization/select",
                            user_agent=user_agent,
                            accept="application/json",
                            referer=consent_url,
                            origin=self.oauth_issuer,
                            content_type="application/json",
                            extra_headers={"oai-device-id": device_id},
                        )
                        org_headers.update(generate_datadog_trace())
                        
                        r_org = self.session.post(
                            f"{self.oauth_issuer}/api/accounts/organization/select",
                            headers=org_headers,
                            json={"org_id": org_id},
                            allow_redirects=False,
                            timeout=30,
                        )
                        if r_org.status_code in (301, 302, 303, 307, 308):
                            location = normalize_flow_url(r_org.headers.get("Location", ""), auth_base=self.oauth_issuer)
                            if "code=" in location:
                                return self._extract_code_from_url(location), self._state_from_url(location)
                        elif r_org.status_code == 200:
                            org_state = self._state_from_payload(r_org.json(), current_url=str(r_org.url))
                            code = self._extract_code_from_state(org_state)
                            if code:
                                return code, org_state

                self._log(
                    f"workspace/select 400 response: {err_body}"
                )
                self._log(
                    "workspace/select returned 400, trying consent acceptance fallback..."
                )
                fallback_result = self._consent_accept_fallback(
                    consent_url=consent_url,
                    workspace_id=workspace_id,
                    device_id=device_id,
                    user_agent=user_agent,
                    impersonate=impersonate,
                    session_data=session_data,
                )
                if fallback_result is not None:
                    return fallback_result

            # if return 200, check the response for orgs
            if r.status_code == 200:
                try:
                    data = r.json()
                    orgs = data.get("data", {}).get("orgs", [])
                    workspace_state = self._state_from_payload(
                        data, current_url=str(r.url)
                    )
                    continue_url = workspace_state.continue_url

                    if orgs:
                        org_id = (orgs[0] or {}).get("id")
                        projects = (orgs[0] or {}).get("projects", [])
                        project_id = (projects[0] or {}).get("id") if projects else None

                        if org_id:
                            self._log(f"choose organization: {org_id}")

                            org_body = {"org_id": org_id}
                            if project_id:
                                org_body["project_id"] = project_id

                            org_referer = (
                                continue_url
                                if continue_url and continue_url.startswith("http")
                                else consent_url
                            )
                            headers = self._headers(
                                f"{self.oauth_issuer}/api/accounts/organization/select",
                                user_agent=user_agent,
                                accept="application/json",
                                referer=org_referer,
                                origin=self.oauth_issuer,
                                content_type="application/json",
                                fetch_site="same-origin",
                                extra_headers={
                                    "oai-device-id": device_id,
                                },
                            )
                            headers.update(generate_datadog_trace())

                            kwargs = {
                                "json": org_body,
                                "headers": headers,
                                "allow_redirects": False,
                                "timeout": 30,
                            }
                            if impersonate:
                                kwargs["impersonate"] = impersonate

                            self._browser_pause()
                            r_org = self.session.post(
                                f"{self.oauth_issuer}/api/accounts/organization/select",
                                **kwargs,
                            )

                            self._log(f"organization/select -> {r_org.status_code}")
                            self._log(
                                f"organization/select ask: org_id={org_id} project_id={project_id or '-'}"
                            )

                            # Check redirects
                            if r_org.status_code in (301, 302, 303, 307, 308):
                                location = normalize_flow_url(
                                    r_org.headers.get("Location", ""),
                                    auth_base=self.oauth_issuer,
                                )
                                if "code=" in location:
                                    code = self._extract_code_from_url(location)
                                    if code:
                                        self._log(
                                            "from organization/select Redirected to get code"
                                        )
                                        return code, self._state_from_url(location)
                                if location:
                                    return None, self._state_from_url(location)

                            # examine continue_url
                            if r_org.status_code == 200:
                                try:
                                    org_state = self._state_from_payload(
                                        r_org.json(), current_url=str(r_org.url)
                                    )
                                    self._log(
                                        f"organization/select -> {describe_flow_state(org_state)}"
                                    )
                                    if self._extract_code_from_state(org_state):
                                        return self._extract_code_from_state(
                                            org_state
                                        ), org_state
                                    return None, org_state
                                except Exception as e:
                                    self._set_error(
                                        f"parse organization/select Abnormal response: {e}"
                                    )

                    # if there is continue_url, follow it
                    if continue_url:
                        code, redirect_url = self._oauth_follow_for_code(
                            continue_url, consent_url, user_agent, impersonate
                        )
                        if code:
                            return code, self._state_from_url(continue_url)
                        if redirect_url and self.browser_mode != "protocol" and hasattr(self, "_browser_capture_callback"):
                            self._log("API redirection follow didn't return code. Falling back to browser capture callback...")
                            callback_url = self._browser_capture_callback(redirect_url, user_agent, impersonate)
                            if callback_url and "code=" in callback_url:
                                code = self._extract_code_from_url(callback_url)
                                if code:
                                    return code, self._state_from_url(callback_url)
                    return None, workspace_state

                except Exception as e:
                    self._set_error(f"deal with workspace/select Abnormal response: {e}")
                    return None, None

        except Exception as e:
            self._set_error(f"workspace/select abnormal: {e}")
            return None, None

        return None, None

    def _consent_accept_fallback(
        self, consent_url, workspace_id, device_id, user_agent, impersonate, session_data=None
    ):
        """Fallback for when workspace/select returns 400 on a consent page."""
        
        # Strategy 1: GET consent URL to trigger natural flow (sometimes redirects to code if already accepted)
        self._log("consent fallback strategy 1: GET consent URL to trigger natural flow")
        try:
            headers = self._headers(
                consent_url,
                user_agent=user_agent,
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                referer=f"{self.oauth_issuer}/email-verification",
                navigation=True,
            )
            kwargs = {"headers": headers, "allow_redirects": True, "timeout": 30}
            if impersonate:
                kwargs["impersonate"] = impersonate
            
            r_get = self.session.get(consent_url, **kwargs)
            self._log(f"consent GET -> {r_get.status_code}, final_url={r_get.url}")
            if "code=" in str(r_get.url):
                return self._extract_code_from_url(str(r_get.url)), self._state_from_url(str(r_get.url))
        except Exception as e:
            self._log(f"consent fallback strategy 1 error: {e}")

        # Strategy 2: POST to consent URL with workspace_id
        self._log("consent fallback strategy 2: POST consent URL with workspace_id")
        try:
            consent_headers = self._headers(
                consent_url,
                user_agent=user_agent,
                accept="application/json",
                referer=consent_url,
                origin=self.oauth_issuer,
                content_type="application/json",
                fetch_site="same-origin",
                extra_headers={
                    "oai-device-id": device_id,
                },
            )
            consent_headers.update(generate_datadog_trace())

            consent_body = {"workspace_id": workspace_id}
            if session_data:
                for k in ["session_id", "openai_client_id"]:
                    if session_data.get(k):
                        consent_body[k] = session_data[k]

            r_consent = self.session.post(consent_url, json=consent_body, headers=consent_headers, allow_redirects=False, timeout=30, impersonate=impersonate if impersonate else None)
            self._log(f"consent POST -> {r_consent.status_code}")

            if r_consent.status_code in (301, 302, 303, 307, 308):
                loc = normalize_flow_url(r_consent.headers.get("Location", ""), auth_base=self.oauth_issuer)
                if "code=" in loc:
                    return self._extract_code_from_url(loc), self._state_from_url(loc)
                code, _ = self._oauth_follow_for_code(loc, consent_url, user_agent, impersonate)
                if code:
                    return code, self._state_from_url(loc)

            if r_consent.status_code == 200:
                data = r_consent.json()
                state = self._state_from_payload(data, current_url=str(r_consent.url))
                code = self._extract_code_from_state(state)
                if code: return code, state
        except Exception as e:
            self._log(f"consent fallback strategy 2 error: {e}")

        # Strategy 3: Follow consent URL redirect chain
        self._log("consent fallback strategy 3: follow consent URL redirect chain")
        try:
            code, _ = self._oauth_follow_for_code(consent_url, f"{self.oauth_issuer}/about-you", user_agent, impersonate)
            if code: return code, self._state_from_url(consent_url)
        except Exception as e:
            self._log(f"consent fallback strategy 3 error: {e}")

        # Strategy 4: Try workspace/select with consent flag
        self._log("consent fallback strategy 4: workspace/select with consent flag")
        try:
            ws_headers = self._headers(f"{self.oauth_issuer}/api/accounts/workspace/select", user_agent=user_agent, accept="application/json", referer=consent_url, origin=self.oauth_issuer, content_type="application/json", extra_headers={"oai-device-id": device_id})
            r_ws = self.session.post(f"{self.oauth_issuer}/api/accounts/workspace/select", json={"workspace_id": workspace_id, "consent": True}, headers=ws_headers, allow_redirects=False, timeout=30, impersonate=impersonate if impersonate else None)
            self._log(f"workspace/select(+consent) -> {r_ws.status_code}")
            if r_ws.status_code in (301, 302, 303, 307, 308):
                loc = normalize_flow_url(r_ws.headers.get("Location", ""), auth_base=self.oauth_issuer)
                if "code=" in loc: return self._extract_code_from_url(loc), self._state_from_url(loc)
        except Exception as e:
            self._log(f"consent fallback strategy 4 error: {e}")

        # Strategy 5: organization/select
        self._log("consent fallback strategy 5: organization/select")
        try:
            org_id = session_data.get("workspaces", [{}])[0].get("org_id") if session_data else None
            if not org_id: org_id = workspace_id
            org_headers = self._headers(f"{self.oauth_issuer}/api/accounts/organization/select", user_agent=user_agent, accept="application/json", referer=consent_url, origin=self.oauth_issuer, content_type="application/json", extra_headers={"oai-device-id": device_id})
            r_org = self.session.post(f"{self.oauth_issuer}/api/accounts/organization/select", json={"org_id": org_id}, headers=org_headers, allow_redirects=False, timeout=30, impersonate=impersonate if impersonate else None)
            self._log(f"organization/select -> {r_org.status_code}")
            if r_org.status_code in (301, 302, 303, 307, 308):
                loc = normalize_flow_url(r_org.headers.get("Location", ""), auth_base=self.oauth_issuer)
                if "code=" in loc: return self._extract_code_from_url(loc), self._state_from_url(loc)
        except Exception as e:
            self._log(f"consent fallback strategy 5 error: {e}")

        self._log("All consent acceptance fallback strategies exhausted")
        return None

    def _load_workspace_session_data(self, consent_url, user_agent, impersonate):
        """Prioritize from cookie decoding session, fallback to consent HTML extracted from workspace data."""
        session_data = self._decode_oauth_session_cookie()
        if session_data and session_data.get("workspaces"):
            return session_data

        if self.browser_mode != "protocol":
            self._log("Workspace data not found in cookies, falling back to browser warm page...")
            self._browser_warm_page(consent_url, user_agent, impersonate)
            session_data = self._decode_oauth_session_cookie()
            if session_data and session_data.get("workspaces"):
                return session_data

        html = self._fetch_consent_page_html(consent_url, user_agent, impersonate)
        if not html:
            return session_data

        parsed = self._extract_session_data_from_consent_html(html)
        if parsed and parsed.get("workspaces"):
            self._log(
                f"from consent HTML Extract to {len(parsed.get('workspaces', []))} indivual workspace"
            )
            return parsed

        return session_data

    def _browser_warm_page(self, consent_url, user_agent, impersonate):
        """Use Playwright browser to load consent_url to bypass CF and acquire cookies"""
        from playwright.sync_api import sync_playwright
        from core.browser_runtime import resolve_browser_headless, ensure_browser_display_available
        from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

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
                    user_agent=user_agent or self.ua,
                    locale=us_loc["locale"],
                    timezone_id=us_loc["timezone"],
                    geolocation={"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
                    permissions=["geolocation"],
                    ignore_https_errors=True,
                )

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
                page.goto(consent_url, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(5000)

                updated_cookies = context.cookies()
                for c in updated_cookies:
                    self.session.cookies.set(
                        c["name"],
                        c["value"],
                        domain=c["domain"],
                        path=c["path"],
                    )
                return {"url": page.url, "html": page.content()}

            except Exception as e:
                self._log(f"Browser warm page exception: {e}")
                return None
            finally:
                browser.close()

    def _browser_capture_callback(self, redirect_url, user_agent, impersonate):
        """Use Playwright browser context to load redirect_url and capture final auth code"""
        from playwright.sync_api import sync_playwright
        from core.browser_runtime import resolve_browser_headless, ensure_browser_display_available
        from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile
        import time

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
                    user_agent=user_agent or self.ua,
                    locale=us_loc["locale"],
                    timezone_id=us_loc["timezone"],
                    geolocation={"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
                    permissions=["geolocation"],
                    ignore_https_errors=True,
                )

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
                captured_url = None

                def on_request(request):
                    nonlocal captured_url
                    url = request.url
                    if "code=" in url and ("callback" in url or "localhost" in url):
                        captured_url = url
                        self._log(f"Captured code URL from request: {url}")

                page.on("request", on_request)

                try:
                    page.goto(redirect_url, wait_until="commit", timeout=20000)
                except Exception as ex:
                    self._log(f"Navigation completed/halted: {ex}")

                for _ in range(25):
                    if captured_url:
                        break
                    time.sleep(0.2)

                if not captured_url:
                    final_url = page.url
                    if "code=" in final_url:
                        captured_url = final_url

                return captured_url

            except Exception as e:
                self._log(f"Browser capture callback exception: {e}")
                return None
            finally:
                browser.close()

    def _fetch_consent_page_html(self, consent_url, user_agent, impersonate):
        """get consent Page HTML, used to parse React Router stream in session data."""
        try:
            headers = self._headers(
                consent_url,
                user_agent=user_agent,
                accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                referer=f"{self.oauth_issuer}/email-verification",
                navigation=True,
            )
            kwargs = {"headers": headers, "allow_redirects": False, "timeout": 30}
            if impersonate:
                kwargs["impersonate"] = impersonate
            self._browser_pause(0.12, 0.3)
            r = self.session.get(consent_url, **kwargs)
            if r.status_code == 200 and "text/html" in (
                r.headers.get("content-type", "").lower()
            ):
                return r.text
        except Exception:
            pass
        return ""

    def _extract_session_data_from_consent_html(self, html):
        """from consent HTML of React Router stream extracted from workspace session data."""
        import json
        import re
        
        try:
            with open("consent_page_debug.html", "w", encoding="utf-8") as f:
                f.write(html)
        except:
            pass

        if not html or "workspaces" not in html:
            return None

        def _first_match(patterns, text):
            for pattern in patterns:
                m = re.search(pattern, text, re.S)
                if m:
                    return m.group(1)
            return ""

        def _build_from_text(text):
            if not text or "workspaces" not in text:
                return None

            normalized = text.replace('\\"', '"')

            session_id = _first_match(
                [
                    r'"session_id"\s*,\s*"([^"]+)"',
                    r'"session_id"\s*:\s*"([^"]+)"',
                ],
                normalized,
            )
            client_id = _first_match(
                [
                    r'"openai_client_id"\s*,\s*"([^"]+)"',
                    r'"openai_client_id"\s*:\s*"([^"]+)"',
                ],
                normalized,
            )

            start = normalized.find('"workspaces"')
            if start < 0:
                start = normalized.find("workspaces")
            if start < 0:
                return None

            end = normalized.find('"openai_client_id"', start)
            if end < 0:
                end = normalized.find("openai_client_id", start)
            if end < 0:
                end = min(len(normalized), start + 8000)
            else:
                end = min(len(normalized), end + 1000)

            workspace_chunk = normalized[start:end]
            
            workspaces = []
            seen = set()
            
            # Find all potential UUIDs as IDs
            ids = re.findall(r'"id"\s*(?:,|:)\s*"([0-9a-fA-F-]{36})"', workspace_chunk)
            org_ids = re.findall(r'"org_id"\s*(?:,|:)\s*"([0-9a-fA-F-]{36})"', workspace_chunk)
            kinds = re.findall(r'"kind"\s*(?:,|:)\s*"([^"]+)"', workspace_chunk)
            
            for idx, wid in enumerate(ids):
                if wid in seen:
                    continue
                seen.add(wid)
                item = {"id": wid}
                if idx < len(kinds):
                    item["kind"] = kinds[idx]
                if idx < len(org_ids):
                    item["org_id"] = org_ids[idx]
                workspaces.append(item)

            if not workspaces:
                return None

            return {
                "session_id": session_id,
                "openai_client_id": client_id,
                "workspaces": workspaces,
            }

        candidates = [html]

        # Extract from streamController.enqueue or other JS patterns
        for quoted in re.findall(
            r'streamController\.enqueue\((["\'])(.*?)\1\)',
            html,
            re.S,
        ):
            quoted_text = quoted[1]
            try:
                if quoted[0] == "'":
                    quoted_text = quoted_text.replace("\\'", "'").replace('"', '\\"')
                    decoded = json.loads('"' + quoted_text + '"')
                else:
                    decoded = json.loads('"' + quoted_text + '"')
            except Exception:
                decoded = quoted_text
            
            if decoded:
                candidates.append(decoded)

        if '\\"workspaces\\"' in html:
            candidates.append(html.replace('\\"', '"'))

        for candidate in candidates:
            parsed = _build_from_text(candidate)
            if parsed and parsed.get("workspaces"):
                return parsed

        return None

    def _decode_oauth_session_cookie(self):
        """decoding oai-client-auth-session cookie"""
        try:
            for cookie in self.session.cookies:
                try:
                    name = cookie.name if hasattr(cookie, "name") else str(cookie)
                    if name == "oai-client-auth-session":
                        value = (
                            cookie.value
                            if hasattr(cookie, "value")
                            else self.session.cookies.get(name)
                        )
                        if value:
                            data = self._decode_cookie_json_value(value)
                            if data:
                                return data
                except Exception:
                    continue
        except Exception:
            pass

        return None

    @staticmethod
    def _decode_cookie_json_value(value):
        import base64
        import json

        raw_value = str(value or "").strip()
        if not raw_value:
            return None

        candidates = [raw_value]
        if "." in raw_value:
            candidates.insert(0, raw_value.split(".", 1)[0])

        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            padded = candidate + "=" * (-len(candidate) % 4)
            for decoder in (base64.urlsafe_b64decode, base64.b64decode):
                try:
                    decoded = decoder(padded).decode("utf-8")
                    parsed = json.loads(decoded)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    return parsed

        return None

    def _exchange_code_for_tokens(self, code, code_verifier, user_agent, impersonate):
        """use authorization code exchange tokens"""
        self._enter_stage("token_exchange", f"code={str(code or '')[:24]}...")
        url = f"{self.oauth_issuer}/oauth/token"

        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.oauth_redirect_uri,
            "client_id": self.oauth_client_id,
            "code_verifier": code_verifier,
        }

        headers = self._headers(
            url,
            user_agent=user_agent,
            accept="application/json",
            referer=f"{self.oauth_issuer}/sign-in-with-chatgpt/codex/consent",
            origin=self.oauth_issuer,
            content_type="application/x-www-form-urlencoded",
            fetch_site="same-origin",
        )

        try:
            kwargs = {"data": payload, "headers": headers, "timeout": 60}
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause()
            r = self.session.post(url, **kwargs)

            if r.status_code == 200:
                self._log("token_exchange success")
                return r.json()
            else:
                self._set_error(f"exchange tokens fail: {r.status_code} - {r.text[:200]}")

        except Exception as e:
            self._set_error(f"exchange tokens abnormal: {e}")

        return None

    def _send_phone_number(self, phone, device_id, user_agent, sec_ch_ua, impersonate):
        request_url = f"{self.oauth_issuer}/api/accounts/add-phone/send"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=f"{self.oauth_issuer}/add-phone",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={"oai-device-id": device_id},
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"phone_number": phone},
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate

            self._browser_pause(0.12, 0.25)
            resp = self.session.post(request_url, **kwargs)
        except Exception as e:
            return False, None, f"add-phone/send abnormal: {e}"

        self._log(f"/add-phone/send -> {resp.status_code}")
        if resp.status_code != 200:
            return (
                False,
                None,
                f"add-phone/send fail: {resp.status_code} - {resp.text[:180]}",
            )

        try:
            data = resp.json()
        except Exception:
            return False, None, "add-phone/send The response is not JSON"

        next_state = self._state_from_payload(
            data, current_url=str(resp.url) or request_url
        )
        self._log(f"add-phone/send {describe_flow_state(next_state)}")
        return True, next_state, ""

    def _resend_phone_otp(
        self,
        phone_number,
        device_id,
        user_agent,
        sec_ch_ua,
        impersonate,
        state: FlowState,
    ):
        request_url = f"{self.oauth_issuer}/api/accounts/add-phone/send"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=state.current_url
            or state.continue_url
            or f"{self.oauth_issuer}/add-phone",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={"oai-device-id": device_id},
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"phone_number": phone_number},
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate
            self._browser_pause(0.12, 0.25)
            resp = self.session.post(request_url, **kwargs)
        except Exception as e:
            return False, f"add-phone/send Retransmission exception: {e}"

        self._log(f"/add-phone/send(resend) -> {resp.status_code}")
        if resp.status_code == 200:
            return True, ""
        return False, f"add-phone/send Resend failed: {resp.status_code} - {resp.text[:180]}"

    def _get_config_value(self, *keys):
        for key in keys:
            value = str(self.config.get(key, "") or "").strip()
            if value:
                return value
        return ""

    def _get_configured_phone_number(self) -> str:
        return self._get_config_value(
            "chatgpt_phone_number",
            "openai_phone_number",
            "phone_number",
        )

    def _get_configured_phone_codes(self) -> list[str]:
        raw = self._get_config_value(
            "chatgpt_phone_otp_codes",
            "chatgpt_phone_otp_code",
            "openai_phone_otp_codes",
            "openai_phone_otp_code",
            "phone_otp_codes",
            "phone_otp_code",
        )
        if not raw:
            return []
        parts = []
        for chunk in raw.replace("\n", ",").replace(";", ",").split(","):
            code = str(chunk or "").strip()
            if code:
                parts.append(code)
        return parts

    def _validate_phone_otp(
        self, code, device_id, user_agent, sec_ch_ua, impersonate, state: FlowState
    ):
        request_url = f"{self.oauth_issuer}/api/accounts/phone-otp/validate"
        headers = self._headers(
            request_url,
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
            accept="application/json",
            referer=state.current_url
            or state.continue_url
            or f"{self.oauth_issuer}/phone-verification",
            origin=self.oauth_issuer,
            content_type="application/json",
            fetch_site="same-origin",
            extra_headers={"oai-device-id": device_id},
        )
        headers.update(generate_datadog_trace())

        try:
            kwargs = {
                "json": {"code": code},
                "headers": headers,
                "timeout": 30,
                "allow_redirects": False,
            }
            if impersonate:
                kwargs["impersonate"] = impersonate
            self._browser_pause(0.12, 0.25)
            resp = self.session.post(request_url, **kwargs)
        except Exception as e:
            return False, None, f"phone-otp/validate abnormal: {e}"

        self._log(f"/phone-otp/validate -> {resp.status_code}")
        if resp.status_code != 200:
            if resp.status_code == 401:
                return False, None, "Mobile phone number verification code is wrong"
            return (
                False,
                None,
                f"phone-otp/validate fail: {resp.status_code} - {resp.text[:180]}",
            )

        try:
            data = resp.json()
        except Exception:
            return False, None, "phone-otp/validate The response is not JSON"

        next_state = self._state_from_payload(
            data, current_url=str(resp.url) or request_url
        )
        self._log(f"Phone number OTP Verification passed {describe_flow_state(next_state)}")
        return True, next_state, ""

    def _handle_add_phone_verification(
        self, device_id, user_agent, sec_ch_ua, impersonate, state: FlowState
    ):
        configured_phone = self._get_configured_phone_number()
        configured_codes = self._get_configured_phone_codes()

        if configured_phone:
            self._log(f"step5: add_phone Use configure mobile phone number: {configured_phone}")
            sent, next_state, detail = self._send_phone_number(
                configured_phone,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
            )
            if not sent or not next_state:
                self._set_error(detail or "add-phone/send No valid status returned")
                return None

            if (
                next_state.page_type != "phone_otp_verification"
                and "phone-verification"
                not in f"{next_state.continue_url} {next_state.current_url}".lower()
            ):
                if self._state_supports_workspace_resolution(next_state) or self._state_requires_navigation(next_state):
                    self._log(f"add_phone After submission, it has entered the follow-up state: {describe_flow_state(next_state)}")
                    return next_state
                self._set_error(
                    f"add-phone/send Did not enter the mobile phone verification code page: {describe_flow_state(next_state)}"
                )
                return None

            if configured_codes:
                for idx, code in enumerate(configured_codes, start=1):
                    self._log(
                        f"step5: Use configured mobile phone number verification code {idx}/{len(configured_codes)}: {code}"
                    )
                    valid, validated_state, detail = self._validate_phone_otp(
                        code,
                        device_id,
                        user_agent,
                        sec_ch_ua,
                        impersonate,
                        next_state,
                    )
                    if valid and validated_state:
                        return validated_state
                    self._log(detail or "Phone number OTP Authentication failed")

                self._set_error("The configured mobile phone number verification code did not pass verification.")
                return None

            self._set_error(
                "Configuring mobile phone number has been submitted but not provided chatgpt_phone_otp_code, the current process cannot continue"
            )
            return None

        # ── Try SMSToMe first ──
        phone_service = SMSToMePhoneService(self.config, log_fn=self._log)
        smspool_service = SMSPoolPhoneService(self.config, log_fn=self._log)

        if not phone_service.enabled and not smspool_service.enabled:
            self._set_error(
                "The current link requires mobile phone number verification, but no phone provider is configured "
                "(SMSToMe, SMSPool, or fixed mobile phone number)"
            )
            return None

        # ── Phase 1: try SMSToMe if enabled ──
        if phone_service.enabled:
            self._log("add_phone: Trying SMSToMe phone provider...")
            smstome_result = self._try_smstome_phone_verification(
                phone_service, device_id, user_agent, sec_ch_ua, impersonate
            )
            if smstome_result is not None:
                return smstome_result
            self._log("SMSToMe phone verification did not succeed, checking SMSPool fallback...")

        # ── Phase 2: try SMSPool if enabled ──
        if smspool_service.enabled:
            self._log("add_phone: Trying SMSPool phone provider...")
            smspool_result = self._try_smspool_phone_verification(
                smspool_service, device_id, user_agent, sec_ch_ua, impersonate
            )
            if smspool_result is not None:
                return smspool_result
            self._log("SMSPool phone verification did not succeed.")

        self._set_error("add_phone stage failed: All phone providers exhausted without successful verification")
        return None

    def _try_smstome_phone_verification(
        self, phone_service, device_id, user_agent, sec_ch_ua, impersonate
    ):
        """Attempt phone verification using the SMSToMe provider. Returns next FlowState or None."""
        excluded_prefixes = set()
        last_failure = ""

        for attempt in range(phone_service.max_attempts):
            try:
                entry = phone_service.acquire_phone(exclude_prefixes=excluded_prefixes)
            except Exception as e:
                last_failure = f"Failed to obtain mobile phone number: {e}"
                self._log(last_failure)
                break

            if not entry:
                last_failure = last_failure or "SMSToMe There is no available mobile phone number in the number pool"
                break

            prefix = phone_service.prefix_hint(entry.phone)
            self._log(
                f"step5: add_phone Select mobile number {attempt + 1}/{phone_service.max_attempts}: {entry.phone} ({entry.country_slug})"
            )

            sent, next_state, detail = self._send_phone_number(
                entry.phone,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
            )
            if not sent or not next_state:
                last_failure = detail or "add-phone/send No valid status returned"
                self._log(last_failure)
                self._blacklist_phone_if_needed(phone_service, entry, last_failure)
                excluded_prefixes.add(prefix)
                continue

            if (
                next_state.page_type != "phone_otp_verification"
                and "phone-verification"
                not in f"{next_state.continue_url} {next_state.current_url}".lower()
            ):
                last_failure = f"add-phone/send Did not enter the mobile phone verification code page: {describe_flow_state(next_state)}"
                self._log(last_failure)
                self._blacklist_phone_if_needed(
                    phone_service, entry, last_failure, next_state
                )
                excluded_prefixes.add(prefix)
                continue

            session_data = self._decode_oauth_session_cookie() or {}
            verification_channel = (
                str(session_data.get("phone_verification_channel") or "sms")
                .strip()
                .lower()
                or "sms"
            )
            bound_phone = (
                str(session_data.get("phone_number") or entry.phone).strip()
                or entry.phone
            )
            self._log(
                f"add_phone Code sent successfully: phone={bound_phone}, channel={verification_channel}"
            )

            if verification_channel != "sms":
                last_failure = f"add_phone Cut to {verification_channel} channel, current SMSToMe Only supports SMS code receiving"
                self._log(last_failure)
                excluded_prefixes.add(prefix)
                continue

            code = phone_service.wait_for_code(entry)
            if not code:
                self._log("The mobile phone number verification code has not been received yet, please try to resend it....")
                resend_ok, resend_detail = self._resend_phone_otp(
                    entry.phone,
                    device_id,
                    user_agent,
                    sec_ch_ua,
                    impersonate,
                    next_state,
                )
                if resend_ok:
                    code = phone_service.wait_for_code(entry)
                if not code:
                    last_failure = (
                        resend_detail or f"Phone number {entry.phone} Did not receive SMS verification code"
                    )
                    self._log(last_failure)
                    excluded_prefixes.add(prefix)
                    continue

            valid, validated_state, detail = self._validate_phone_otp(
                code,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
                next_state,
            )
            if not valid or not validated_state:
                last_failure = detail or "Phone number OTP Authentication failed"
                self._log(last_failure)
                excluded_prefixes.add(prefix)
                continue

            return validated_state

        self._log(f"SMSToMe exhausted: {last_failure or 'No numbers available'}")
        return None

    def _try_smspool_phone_verification(
        self, smspool_service, device_id, user_agent, sec_ch_ua, impersonate
    ):
        """Attempt phone verification using SMSPool. Returns next FlowState or None."""
        last_failure = ""

        for attempt in range(smspool_service.max_attempts):
            order = None
            try:
                order = smspool_service.purchase_number()
            except Exception as e:
                last_failure = f"SMSPool order failed: {e}"
                self._log(last_failure)
                if attempt + 1 < smspool_service.max_attempts:
                    time.sleep(3)
                continue

            phone = smspool_service.format_phone_for_openai(order.phone_number)
            self._log(
                f"step5: add_phone SMSPool number {attempt + 1}/{smspool_service.max_attempts}: "
                f"{phone} (order={order.order_id})"
            )

            sent, next_state, detail = self._send_phone_number(
                phone,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
            )
            if not sent or not next_state:
                last_failure = detail or "add-phone/send No valid status returned"
                self._log(last_failure)
                smspool_service.cancel_order(order.order_id)
                continue

            if (
                next_state.page_type != "phone_otp_verification"
                and "phone-verification"
                not in f"{next_state.continue_url} {next_state.current_url}".lower()
            ):
                if (
                    self._state_supports_workspace_resolution(next_state)
                    or self._state_requires_navigation(next_state)
                ):
                    self._log(
                        f"add_phone After SMSPool submission, entered follow-up state: "
                        f"{describe_flow_state(next_state)}"
                    )
                    smspool_service.cancel_order(order.order_id)
                    return next_state
                last_failure = (
                    f"add-phone/send Did not enter phone verification page: "
                    f"{describe_flow_state(next_state)}"
                )
                self._log(last_failure)
                smspool_service.cancel_order(order.order_id)
                continue

            session_data = self._decode_oauth_session_cookie() or {}
            verification_channel = (
                str(session_data.get("phone_verification_channel") or "sms")
                .strip()
                .lower()
                or "sms"
            )
            self._log(
                f"add_phone SMSPool code sent: phone={phone}, channel={verification_channel}"
            )

            if verification_channel != "sms":
                last_failure = (
                    f"add_phone switched to {verification_channel} channel, "
                    "SMSPool only supports SMS"
                )
                self._log(last_failure)
                smspool_service.cancel_order(order.order_id)
                continue

            # Wait for the SMS code via SMSPool polling
            code = smspool_service.wait_for_code(order.order_id)
            if not code:
                self._log("SMSPool: No code received, trying resend...")
                resend_ok, resend_detail = self._resend_phone_otp(
                    phone,
                    device_id,
                    user_agent,
                    sec_ch_ua,
                    impersonate,
                    next_state,
                )
                if resend_ok:
                    code = smspool_service.wait_for_code(order.order_id)
                if not code:
                    last_failure = (
                        resend_detail
                        or f"SMSPool phone {phone} did not receive SMS code"
                    )
                    self._log(last_failure)
                    smspool_service.cancel_order(order.order_id)
                    continue

            valid, validated_state, detail = self._validate_phone_otp(
                code,
                device_id,
                user_agent,
                sec_ch_ua,
                impersonate,
                next_state,
            )
            if not valid or not validated_state:
                last_failure = detail or "Phone OTP validation failed"
                self._log(last_failure)
                continue

            self._log(f"SMSPool phone verification successful: {phone}")
            return validated_state

        self._log(f"SMSPool exhausted: {last_failure or 'No successful verification'}")
        return None

    def _handle_otp_verification(
        self,
        email,
        device_id,
        user_agent,
        sec_ch_ua,
        impersonate,
        skymail_client,
        state,
        *,
        prefer_passwordless_login=False,
        allow_cached_code_retry=False,
    ):
        """deal with OAuth stage mailbox OTP Verify and return the next state declared by the server."""
        self._enter_stage("otp", f"email={email}")
        self._log("step4: Mailbox detected OTP verify")
        # Record OTP Send time baseline——must be in sentinel token Before waiting for time-consuming operations,
        # Otherwise mail created_at will be earlier than otp_cutoff As a result, the verification code is misjudged as an old email.
        _otp_sent_at_baseline = time.time()

        def _resend_email_otp() -> bool:
            prefer_passwordless = bool(
                prefer_passwordless_login
                or allow_cached_code_retry
                or self.config.get("prefer_passwordless_login")
                or self.config.get("force_passwordless_login")
            )
            resend_ok = False
            if prefer_passwordless:
                request_url = f"{self.oauth_issuer}/api/accounts/passwordless/send-otp"
                headers = self._headers(
                    request_url,
                    user_agent=user_agent,
                    sec_ch_ua=sec_ch_ua,
                    accept="application/json",
                    referer=state.current_url
                    or state.continue_url
                    or f"{self.oauth_issuer}/log-in/password",
                    origin=self.oauth_issuer,
                    content_type="application/json",
                    fetch_site="same-origin",
                    extra_headers={
                        "oai-device-id": device_id,
                    },
                )
                headers.update(generate_datadog_trace())
                try:
                    kwargs = {"headers": headers, "timeout": 30, "allow_redirects": False}
                    if impersonate:
                        kwargs["impersonate"] = impersonate
                    self._browser_pause()
                    resp = self.session.post(request_url, **kwargs)
                    self._log(f"/passwordless/send-otp -> {resp.status_code}")
                    if resp.status_code == 200:
                        resend_ok = True
                except Exception as e:
                    self._log(f"passwordless resend abnormal: {e}")

            if resend_ok:
                self._log("Triggered passwordless OTP Resend")
                return True

            request_url = f"{self.oauth_issuer}/api/accounts/email-otp/send"
            headers = self._headers(
                request_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="application/json, text/plain, */*",
                referer=state.current_url
                or state.continue_url
                or f"{self.oauth_issuer}/email-verification",
                fetch_site="same-origin",
                extra_headers={
                    "oai-device-id": device_id,
                },
            )
            headers.update(generate_datadog_trace())
            try:
                kwargs = {"headers": headers, "timeout": 30, "allow_redirects": True}
                if impersonate:
                    kwargs["impersonate"] = impersonate
                self._browser_pause()
                resp = self.session.get(request_url, **kwargs)
                self._log(f"/email-otp/send -> {resp.status_code}")
                if resp.status_code == 200:
                    self._log("Triggered email-otp Resend")
                    return True
                self._log(f"email-otp/send Resend failed: {resp.text[:120]}")
            except Exception as e:
                self._log(f"email-otp/send Retransmission exception: {e}")
            return False

        request_url = f"{self.oauth_issuer}/api/accounts/email-otp/validate"
        self._log(f"email_otp_validate: device_id={device_id}")
        otp_referer = (
            state.current_url
            or state.continue_url
            or f"{self.oauth_issuer}/email-verification"
        )
        sentinel_otp = get_sentinel_token_via_browser(
            flow="email_otp_validate",
            proxy=self.proxy,
            page_url=otp_referer,
            headless=self.browser_mode != "headed",
            device_id=device_id,
            log_fn=lambda msg: self._log(f"email_otp_validate: {msg}"),
            user_agent=user_agent,
            sec_ch_ua=sec_ch_ua,
        )
        if sentinel_otp:
            self._log("email_otp_validate: Passed Playwright SentinelSDK get token")
        else:
            sentinel_otp = build_sentinel_token(
                self.session,
                device_id,
                flow="email_otp_validate",
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                impersonate=impersonate,
            )
            if sentinel_otp:
                self._log("email_otp_validate: Passed HTTP PoW get token")
            else:
                self._log("email_otp_validate: Not generated sentinel token(keep trying)")

        def _build_otp_headers():
            extra_headers = {
                "oai-device-id": device_id,
            }
            if sentinel_otp:
                extra_headers["openai-sentinel-token"] = sentinel_otp
            headers_otp = self._headers(
                request_url,
                user_agent=user_agent,
                sec_ch_ua=sec_ch_ua,
                accept="application/json",
                referer=otp_referer,
                origin=self.oauth_issuer,
                content_type="application/json",
                fetch_site="same-origin",
                extra_headers=extra_headers,
            )
            headers_otp.update(generate_datadog_trace())
            return headers_otp

        if not hasattr(skymail_client, "_used_codes"):
            skymail_client._used_codes = set()

        tried_codes = set()
        try:
            otp_wait_seconds = int(
                self.config.get(
                    "chatgpt_oauth_otp_wait_seconds",
                    self.config.get("chatgpt_otp_wait_seconds", 600),
                )
                or 600
            )
        except Exception:
            otp_wait_seconds = 600
        otp_wait_seconds = max(30, min(otp_wait_seconds, 3600))
        otp_poll_window = min(30, max(10, otp_wait_seconds))
        try:
            default_resend_wait_seconds = 45 if prefer_passwordless_login else 120
            otp_resend_wait_seconds = int(
                self.config.get(
                    "chatgpt_oauth_otp_resend_wait_seconds",
                    self.config.get(
                        "chatgpt_otp_resend_wait_seconds",
                        default_resend_wait_seconds,
                    ),
                )
                or default_resend_wait_seconds
            )
        except Exception:
            otp_resend_wait_seconds = 45 if prefer_passwordless_login else 120
        otp_resend_wait_seconds = max(30, min(otp_resend_wait_seconds, 900))
        otp_deadline = time.time() + otp_wait_seconds
        otp_sent_at = _otp_sent_at_baseline
        self._log(
            f"OAuth OTP waiting window: total={otp_wait_seconds}s, poll_window={otp_poll_window}s, "
            f"Maximum per round 5 Resend after no response times, up to 3 wheel"
        )

        otp_net_retry_counts = {}
        _max_net_retries = 3

        def validate_otp(code):
            self._log(f"try OTP: {code}")

            try:
                kwargs = {
                    "json": {"code": code},
                    "headers": _build_otp_headers(),
                    "timeout": 30,
                    "allow_redirects": False,
                }
                if impersonate:
                    kwargs["impersonate"] = impersonate
                self._browser_pause(0.12, 0.25)
                resp_otp = self.session.post(request_url, **kwargs)
            except Exception as e:
                if self._is_otp_network_error(e):
                    otp_net_retry_counts[code] = otp_net_retry_counts.get(code, 0) + 1
                    if otp_net_retry_counts[code] <= _max_net_retries:
                        self._log(
                            f"email-otp/validate network/proxy error, will retry same code "
                            f"({otp_net_retry_counts[code]}/{_max_net_retries}): {e}"
                        )
                        time.sleep(min(6, 3 + otp_net_retry_counts[code]))
                        return None
                    self._log(
                        f"email-otp/validate network/proxy error, retries exhausted, "
                        f"skip this code: {e}"
                    )
                else:
                    self._log(f"email-otp/validate abnormal: {e}")
                tried_codes.add(code)
                return None

            self._log(f"/email-otp/validate -> {resp_otp.status_code}")
            if resp_otp.status_code != 200:
                err_text = resp_otp.text[:160]
                self._log(f"OTP invalid: {err_text}")
                tried_codes.add(code)
                # If OpenAI returns "Too many tries" or rate-limit message,
                # bail out immediately instead of looping on stale codes.
                if "too many tries" in err_text.lower() or "rate_limit" in err_text.lower():
                    err_msg = "OTP rate-limit hit, aborting OTP phase"
                    self._log(err_msg)
                    self._set_error(err_msg)
                    return None
                return None

            try:
                otp_data = resp_otp.json()
            except Exception:
                self._log("email-otp/validate The response is not JSON")
                tried_codes.add(code)
                return None

            next_state = self._state_from_payload(
                otp_data,
                current_url=str(resp_otp.url)
                or (state.current_url or state.continue_url or request_url),
            )
            self._log(f"OTP Verification passed {describe_flow_state(next_state)}")
            tried_codes.add(code)
            self._log(
                f"otp Response details: current_url={str(resp_otp.url)[:120]} tried_codes={len(tried_codes)}"
            )
            remember_successful_code = getattr(
                skymail_client, "remember_successful_code", None
            )
            if callable(remember_successful_code):
                remember_successful_code(code)
            else:
                skymail_client._used_codes.add(code)
                setattr(skymail_client, "_last_success_code", code)
                setattr(skymail_client, "_last_success_code_at", time.time())
            return next_state

        if allow_cached_code_retry:
            cached_code = ""
            cached_age = None
            get_recent_code = getattr(skymail_client, "get_recent_code", None)
            if callable(get_recent_code):
                cached_code = str(
                    get_recent_code(
                        max_age_seconds=min(180, otp_wait_seconds),
                        prefer_successful=True,
                    )
                    or ""
                ).strip()
                cached_age = (
                    time.time() - float(getattr(skymail_client, "_last_success_code_at", 0) or 0)
                    if cached_code
                    else None
                )
            else:
                cached_code = str(
                    getattr(skymail_client, "_last_success_code", "")
                    or getattr(skymail_client, "_last_code", "")
                    or ""
                ).strip()
                cached_ts = float(
                    getattr(skymail_client, "_last_success_code_at", 0)
                    or getattr(skymail_client, "_last_code_at", 0)
                    or 0
                )
                if cached_code and cached_ts:
                    cached_age = time.time() - cached_ts
                    if cached_age > min(180, otp_wait_seconds):
                        cached_code = ""

            if cached_code:
                age_text = (
                    f"{int(max(0, cached_age or 0))}sforward"
                    if cached_age is not None
                    else "Recently"
                )
                self._log(
                    f"Recent cache detected OTP, try directly first: {cached_code} ({age_text})"
                )
                next_state = validate_otp(cached_code)
                if next_state:
                    return next_state
                self._log("cache OTP Failed, continue to wait for new OTP...")

        if hasattr(skymail_client, "wait_for_verification_code"):
            self._log("use wait_for_verification_code Perform blocking method to obtain new verification code...")
            no_new_count = 0
            resend_round = 0
            _max_no_new = 5
            _max_resend_rounds = 3
            while time.time() < otp_deadline:
                remaining = max(1, int(otp_deadline - time.time()))
                wait_time = min(otp_poll_window, remaining)
                try:
                    code = skymail_client.wait_for_verification_code(
                        email,
                        timeout=wait_time,
                        otp_sent_at=otp_sent_at,
                        exclude_codes=tried_codes,
                    )
                except TaskInterruption:
                    self._set_error("Task has been stopped manually")
                    return None
                except Exception as e:
                    if "manual stop" in str(e):
                        self._set_error("Task has been stopped manually")
                        return None
                    self._log(f"wait OTP abnormal: {e}")
                    code = None

                if not code:
                    no_new_count += 1
                    self._log(
                        f"No new ones have been received yet OTP, continue to wait... (No. of this round {no_new_count}/{_max_no_new} Second-rate)"
                    )
                    if no_new_count >= _max_no_new:
                        if resend_round < _max_resend_rounds:
                            resend_round += 1
                            self._log(
                                f"continuous {_max_no_new} No new ones received OTP,"
                                f"Trigger the first {resend_round}/{_max_resend_rounds} round reissue..."
                            )
                            if _resend_email_otp():
                                otp_sent_at = time.time()
                            no_new_count = 0
                        else:
                            self._log(
                                f"Completed {_max_resend_rounds} The resend has not been received yet OTP, give up waiting"
                            )
                            break
                    if self.last_error:
                        break
                    continue

                if code in tried_codes:
                    self._log(f"Skip attempted verification codes: {code}")
                    continue

                no_new_count = 0
                next_state = validate_otp(code)
                if next_state:
                    return next_state
                if self.last_error:
                    break
        else:
            while time.time() < otp_deadline:
                messages = skymail_client.fetch_emails(email) or []
                candidate_codes = []

                for msg in messages[:12]:
                    content = msg.get("content") or msg.get("text") or ""
                    code = skymail_client.extract_verification_code(content)
                    if code and code not in tried_codes:
                        candidate_codes.append(code)

                if not candidate_codes:
                    elapsed = int(otp_wait_seconds - max(0, otp_deadline - time.time()))
                    self._log(f"waiting for new OTP... ({elapsed}s/{otp_wait_seconds}s)")
                    time.sleep(2)
                    continue

                for otp_code in candidate_codes:
                    next_state = validate_otp(otp_code)
                    if next_state:
                        return next_state

                time.sleep(2)
                if self.last_error:
                    break

        if not self.last_error:
            self._set_error(
                f"OAuth stage OTP Authentication failed, tried {len(tried_codes)} Verification code, waiting window {otp_wait_seconds}s"
            )
        return None

