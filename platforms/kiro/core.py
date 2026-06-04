"""
Kiro / AWS Builder ID Automatic registration v11 (Playwright Refactored version)
Comprehensive use of real sandbox simulation to avoid AWS Builder ID Advanced front desk risk control (FWCIM / JWE / CSRF springboard).
"""

import uuid
import time
import json
import random
import logging
import re
import hashlib
import threading
import base64
import os
import importlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional, Tuple, Union
from urllib.parse import urlencode, urlparse, parse_qs
from core.browser_runtime import (
    ensure_browser_display_available,
    resolve_browser_headless,
)
from urllib.request import Request, build_opener
from core.proxy_utils import build_requests_proxy_config, build_playwright_proxy_config, resolve_us_profile

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests: Any = None

from playwright.sync_api import sync_playwright, TimeoutError, Page, Locator

try:
    stealth_sync = importlib.import_module("playwright_stealth").stealth_sync
except Exception:
    stealth_sync = None

# If there is a global turnstile_strategy, can be borrowed, leave one here stub

KIRO_SIGNIN_URL = "https://app.kiro.dev/signin"
KIRO_IDC_REGION = "us-east-1"
KIRO_IDC_START_URL = "https://view.awsapps.com/start"
KIRO_IDC_SCOPES = [
    "codewhisperer:completions",
    "codewhisperer:analysis",
    "codewhisperer:conversations",
    "codewhisperer:transformations",
    "codewhisperer:taskassist",
]
logger = logging.getLogger("kiro.playwright")

_UA_TEMPLATES = [
    {
        "name": "win_chrome",
        "template": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
    },
    {
        "name": "mac_chrome",
        "template": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_{minor}_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
    },
    {
        "name": "linux_chrome",
        "template": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36",
    },
]

_LOCALE_TIMEZONE_POOLS = [
    (
        "en-US",
        [
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
        ],
    ),
    ("en-GB", ["Europe/London"]),
    ("en-CA", ["America/Toronto", "America/Vancouver"]),
    ("en-AU", ["Australia/Sydney", "Australia/Melbourne"]),
]

_VIEWPORT_PRESETS = [
    (1366, 768),
    (1440, 900),
    (1536, 864),
    (1600, 900),
    (1680, 1050),
    (1920, 1080),
]

_FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "David",
    "William", "Richard", "Joseph", "Thomas", "Christopher",
    "Charles", "Daniel", "Matthew", "Anthony", "Mark",
    "Steven", "Andrew", "Joshua", "Kenneth", "Kevin",
    "Brian", "George", "Timothy", "Ronald", "Jason",
    "Mary", "Patricia", "Jennifer", "Linda", "Barbara",
    "Elizabeth", "Susan", "Jessica", "Sarah", "Karen",
    "Lisa", "Nancy", "Amanda", "Emily", "Melissa",
    "Stephanie", "Rebecca", "Laura", "Sharon", "Cynthia",
    "Dorothy", "Amy", "Angela", "Michelle", "Donna",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones",
    "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Anderson", "Taylor", "Thomas", "Moore", "Jackson",
    "Martin", "Lee", "Thompson", "White", "Harris",
    "Clark", "Lewis", "Robinson", "Walker", "Young",
    "Allen", "King", "Wright", "Scott", "Hill",
    "Green", "Adams", "Baker", "Nelson", "Carter",
    "Mitchell", "Roberts", "Turner", "Phillips", "Campbell",
    "Parker", "Evans", "Edwards", "Collins", "Stewart",
    "Morris", "Reed", "Cook", "Morgan", "Bell",
]


class _DesktopAuthCallbackServer:
    def __init__(self, expected_state: str):
        self.expected_state = expected_state
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self._event = threading.Event()
        self._server = None
        self._thread = None

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/oauth/callback":
                    self.send_response(404)
                    self.end_headers()
                    return

                params = parse_qs(parsed.query)
                error = params.get("error", [None])[0]
                error_description = params.get("error_description", [None])[0]
                state = params.get("state", [None])[0]
                code = params.get("code", [None])[0]

                if error:
                    outer.error = error_description or error
                elif not state:
                    outer.error = "Desktop authorization callback missing state"
                elif state != outer.expected_state:
                    outer.error = "Desktop authorization callback state no match"
                elif not code:
                    outer.error = "Desktop authorization callback missing code"
                else:
                    outer.result = {"code": code, "state": state}

                outer._event.set()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h3>Kiro desktop authentication completed.</h3></body></html>"
                )

            def log_message(self, format, *args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        if not self._server:
            raise RuntimeError("Desktop authorization callback service not started")
        port = self._server.server_address[1]
        return f"http://127.0.0.1:{port}/oauth/callback"

    def wait(self, timeout: int = 120):
        if not self._event.wait(timeout):
            raise TimeoutError("Waiting for desktop authorization callback timed out")
        if self.error:
            raise RuntimeError(self.error)
        if not self.result:
            raise RuntimeError("Desktop authorization callback not returned code")
        return self.result

    def close(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None


class KiroRegister:
    def __init__(self, proxy=None, tag="KIRO", headless=False):
        self.proxy = proxy
        self.tag = tag
        self.headless = headless
        self.log_fn = print
        self.pw = None
        self.browser = None
        self.context = None

        # Save captured Token API response
        self._captured_tokens = {}
        self._network_debug = []

    def _require_context(self):
        if self.context is None:
            raise RuntimeError("Browser context not initialized")
        return self.context

    def log(self, msg):
        self.log_fn(f"[{self.tag}] {msg}")

    def _human_sleep(self, min_seconds: float = 0.18, max_seconds: float = 0.65):
        time.sleep(random.uniform(min_seconds, max_seconds))

    def _randomize_name(self, base_name: str) -> str:
        """Generate a realistic random American name from first/last name pools."""
        first = random.choice(_FIRST_NAMES)
        last = random.choice(_LAST_NAMES)
        return f"{first} {last}"

    def _random_chrome_version(self) -> str:
        major = random.randint(130, 136)
        build = random.randint(6400, 7399)
        patch = random.randint(40, 220)
        return f"{major}.0.{build}.{patch}"

    def _build_random_profile(self) -> dict:
        ua_tmpl = random.choice(_UA_TEMPLATES)
        chrome_ver = self._random_chrome_version()

        locale, tz_pool = random.choice(_LOCALE_TIMEZONE_POOLS)
        timezone_id = random.choice(tz_pool)

        base_w, base_h = random.choice(_VIEWPORT_PRESETS)
        width = max(1100, base_w + random.randint(-72, 72))
        height = max(700, base_h + random.randint(-54, 54))

        if ua_tmpl["name"] == "mac_chrome":
            os_minor = random.choice([14, 15, 16])
            user_agent = ua_tmpl["template"].format(ver=chrome_ver, minor=os_minor)
        else:
            user_agent = ua_tmpl["template"].format(ver=chrome_ver)

        return {
            "name": f"{ua_tmpl['name']}_{chrome_ver}",
            "user_agent": user_agent,
            "locale": locale,
            "timezone_id": timezone_id,
            "viewport": {"width": width, "height": height},
        }

    def _init_browser(self):
        self.pw = sync_playwright().start()
        headless, reason = resolve_browser_headless(
            self.headless, default_headless=False
        )
        ensure_browser_display_available(headless)
        launch_opts: dict[str, Any] = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        }
        if self.proxy:
            proxy_cfg = build_playwright_proxy_config(self.proxy)
            if proxy_cfg:
                launch_opts["proxy"] = proxy_cfg

        self.browser = self.pw.chromium.launch(**launch_opts)
        profile = self._build_random_profile()
        us_loc = resolve_us_profile(self.proxy)

        env_locale = os.getenv("KIRO_LOCALE", "").strip()
        env_timezone = os.getenv("KIRO_TIMEZONE", "").strip()
        locale = env_locale or us_loc["locale"]
        timezone_id = env_timezone or us_loc["timezone"]
        viewport: dict[str, int] = dict(profile["viewport"])

        self.log(f"browser mode: {'headless' if headless else 'headed'} ({reason})")
        self.log(
            f"Browser portrait: {profile['name']} / {locale} / {timezone_id} / "
            f"{viewport['width']}x{viewport['height']}"
        )
        context_opts: dict[str, Any] = {
            "user_agent": profile["user_agent"],
            "locale": locale,
            "timezone_id": timezone_id,
            "geolocation": {"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
            "permissions": ["geolocation"],
            "viewport": viewport,
            "color_scheme": random.choice(["light", "dark"]),
            "reduced_motion": random.choice(["reduce", "no-preference"]),
        }
        self.context = self.browser.new_context(**context_opts)
        self._captured_tokens["userAgent"] = profile["user_agent"]
        self.context.set_extra_http_headers({"Accept-Language": f"{locale},en;q=0.9"})

        # intercept Kiro Requests related to successful login/response, extraction Token
        self.context.on("request", self._on_request)
        self.context.on("response", self._on_response)

    def _is_watched_url(self, url: str) -> bool:
        url = (url or "").lower()
        return any(
            keyword in url
            for keyword in [
                "kiro",
                "token",
                "oauth",
                "login",
                "complete",
                "auth",
            ]
        )

    def _append_network_debug(self, entry):
        self._network_debug.append(entry)
        if len(self._network_debug) > 60:
            self._network_debug = self._network_debug[-60:]

    def _on_request(self, request):
        try:
            url = request.url
            if not self._is_watched_url(url):
                return

            entry = {
                "type": "request",
                "method": request.method,
                "url": url,
            }
            post_data = request.post_data
            if post_data:
                entry["post_data"] = post_data[:2000]
                try:
                    parsed = json.loads(post_data)
                    interesting = self._extract_tokens_from_object(parsed)
                    if interesting:
                        self._captured_tokens.update(interesting)
                except Exception:
                    pass
            self._append_network_debug(entry)
        except Exception:
            pass

    def _on_response(self, response):
        try:
            url = response.url
            if not self._is_watched_url(url):
                return

            entry = {"type": "response", "url": url, "status": response.status}
            body = None
            try:
                body = response.json()
            except Exception:
                try:
                    text = response.text()
                    entry["text"] = text[:2000]
                    self._captured_tokens.update(self._extract_tokens_from_object(text))
                except Exception:
                    text = None

            if isinstance(body, dict):
                interesting = self._extract_tokens_from_object(body)
                entry["json_keys"] = list(body.keys())[:20]
                entry["json"] = json.dumps(body, ensure_ascii=False)[:2000]
                if interesting:
                    self._captured_tokens.update(interesting)
                    self.log(f"Successfully intercepted the suspected Token response: {url}")

            self._append_network_debug(entry)
        except Exception:
            pass

    def _extract_tokens_from_object(self, data):
        found = {}
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception:
                import re as _re

                for key in (
                    "accessToken",
                    "refreshToken",
                    "clientId",
                    "clientSecret",
                    "sessionToken",
                ):
                    m = _re.search(rf'"{key}"\s*:\s*"([^"]+)"', data)
                    if m:
                        found[key] = m.group(1)
                return found
        stack = [data]
        wanted_keys = {
            "accessToken",
            "refreshToken",
            "clientId",
            "clientSecret",
            "sessionToken",
        }

        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, value in current.items():
                    if key in wanted_keys and isinstance(value, str) and value:
                        found[key] = value
                    elif isinstance(value, (dict, list)):
                        stack.append(value)
                    elif isinstance(value, str):
                        try:
                            parsed = json.loads(value)
                        except Exception:
                            continue
                        if isinstance(parsed, (dict, list)):
                            stack.append(parsed)
            elif isinstance(current, list):
                stack.extend(current)

        return found

    def _close_browser(self):
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

    def _accept_cookie_banner_if_present(self, page: Page):
        try:
            if page.locator("text=/cookie/i").count() == 0:
                return

            selectors = [
                'button[data-id*="awsccc"]:has-text("Accept")',
                'button[id*="awsccc-accept"]',
                'button:has-text("Accept")',
            ]
            for sel in selectors:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2000)
                    self.log("Processed Cookie banner (Accept)")
                    self._human_sleep(0.2, 0.45)
                    return
        except Exception:
            pass

    def _get_aws_alert_text(self, page: Page) -> str:
        selectors = [
            ".awsui-alert-content",
            '[data-testid*="alert"]',
            '[role="alert"]',
        ]
        for sel in selectors:
            try:
                alert = page.locator(sel).first
                if alert.count() > 0 and alert.is_visible():
                    text = (alert.text_content() or "").strip()
                    if text:
                        return text
            except Exception:
                continue
        return ""

    def _type_like_human(
        self,
        page: Page,
        selector_or_locator: Union[str, Locator],
        text: str,
        clear_first: bool = True,
    ):
        if isinstance(selector_or_locator, str):
            el = page.locator(selector_or_locator).first
        else:
            # It's already a Locator, use its first match
            el = selector_or_locator.first

        # Small random delay before interacting with the field (feels more natural)
        self._human_sleep(0.3, 0.9)

        el.click(delay=random.randint(45, 160))
        if clear_first:
            try:
                el.clear()
            except Exception:
                try:
                    page.keyboard.press("Control+A")
                    page.keyboard.press("Backspace")
                except Exception:
                    pass

        # Brief pause after focusing / clearing before typing begins
        self._human_sleep(0.15, 0.4)

        for idx, char in enumerate(text):
            # Natural per-keystroke delay (~50-120ms base)
            page.keyboard.type(char, delay=random.randint(38, 125))
            # Occasional micro-pause between keystrokes to mimic real typing rhythm
            if idx > 0 and random.random() < 0.15:
                self._human_sleep(0.04, 0.18)
        self._human_sleep(0.25, 0.65)

    def _solve_captcha_if_exists(self, page: Page):
        try:
            # If you encounter CAPTCHA, here you can connect to external coding
            if (
                page.locator('iframe[src*="captcha"]').count() > 0
                or page.locator(".awsui-captcha").count() > 0
            ):
                self.log("⚠️ discover potential CAPTCHA Challenge, try to wait or need the pendant to automatically code...")
                page.wait_for_timeout(5000)
        except Exception:
            pass

    def _click_primary_button(self, page: Page):
        # give React Status synchronization time to prevent verification failure caused by clicking too fast when typing
        self._human_sleep(0.45, 1.05)

        try:
            # Test possible feed buttons on the page by priority
            selectors = [
                'button[data-testid*="verify-button"]',
                'button[data-testid*="next-button"]',
                'button[data-testid="test-primary-button"]',
                'button[type="submit"]:has-text("Continue")',
                'button[type="submit"]:has-text("Verify")',
                'button[type="submit"]:has-text("Create")',
                'button[type="submit"]:has-text("Next")',
            ]
            for sel in selectors:
                btn = page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=2000)
                    self._human_sleep(0.22, 0.65)
                    return

            # The last resort: Find the missing awsccc(Cookie Consent) is visible Submit button
            fallback = page.locator(
                'button[type="submit"]:not([data-id*="awsccc"]):visible'
            ).first
            if fallback.count() > 0 and fallback.is_visible():
                fallback.click(timeout=2000)
                self._human_sleep(0.22, 0.65)
        except Exception:
            pass

    def _get_first_visible_text(self, page: Page, patterns) -> str:
        for pattern in patterns:
            try:
                locator = page.get_by_text(pattern)
                if locator.count() > 0 and locator.first.is_visible():
                    return (locator.first.text_content() or "").strip()
            except Exception:
                continue
        return ""

    def _get_first_visible_locator(self, candidates) -> Optional[Locator]:
        for locator in candidates:
            try:
                field = locator.first
                if field.count() > 0 and field.is_visible():
                    return field
            except Exception:
                continue
        return None

    def _name_input_candidates(self, page: Page):
        return [
            page.get_by_label("Name", exact=True),
            page.get_by_label(re.compile(r"your name", re.I)),
            page.locator('input[placeholder="Maria José Silva"]'),
            page.locator('input[autocomplete="name"]'),
            page.locator('input[name="name"]'),
        ]

    def _otp_input_candidates(self, page: Page):
        return [
            page.get_by_label("Verification code", exact=True),
            page.locator('input[placeholder*="6-digit" i]'),
            page.locator('div[data-testid*="code-input"] input'),
            page.locator('input[name="code"], input[id*="code"]'),
        ]

    def _wait_for_password_step(
        self, page: Page, timeout_ms: int = 15000
    ) -> Tuple[bool, str]:
        deadline = time.time() + (timeout_ms / 1000)
        password_input = page.locator('input[type="password"]')
        error_patterns = [
            re.compile(r"code didn't work", re.I),
            re.compile(r"couldn't complete your request right now", re.I),
            re.compile(r"invalid verification code", re.I),
            re.compile(r"verify your email", re.I),
        ]

        while time.time() < deadline:
            try:
                if password_input.count() > 0 and password_input.first.is_visible():
                    return True, ""
            except Exception:
                pass

            error_text = self._get_first_visible_text(page, error_patterns)
            if error_text:
                return False, error_text

            self._human_sleep(0.2, 0.6)

        return False, "Did not enter the password setting page after submitting the verification code"

    def _wait_for_post_email_step(
        self, page: Page, timeout_ms: int = 30000
    ) -> Tuple[str, Optional[Locator], str]:
        deadline = time.time() + (timeout_ms / 1000)
        error_patterns = [
            re.compile(r"error processing your request", re.I),
            re.compile(r"couldn't complete your request", re.I),
            re.compile(r"verify your email", re.I),
            re.compile(r"invalid verification code", re.I),
        ]

        while time.time() < deadline:
            otp_field = self._get_first_visible_locator(
                self._otp_input_candidates(page)
            )
            if otp_field:
                return "otp", otp_field, ""

            name_field = self._get_first_visible_locator(
                self._name_input_candidates(page)
            )
            if name_field:
                return "name", name_field, ""

            error_text = self._get_first_visible_text(page, error_patterns)
            if not error_text:
                error_text = self._get_aws_alert_text(page)
            if error_text:
                return "error", None, error_text

            self._human_sleep(0.2, 0.6)

        return "timeout", None, "Waiting for name or OTP Input box timeout"

    def _wait_for_otp_step(
        self, page: Page, timeout_ms: int = 18000
    ) -> Tuple[bool, str, Optional[Locator]]:
        deadline = time.time() + (timeout_ms / 1000)
        error_patterns = [
            re.compile(r"error processing your request", re.I),
            re.compile(r"couldn't complete your request", re.I),
            re.compile(r"verify your email", re.I),
            re.compile(r"invalid verification code", re.I),
        ]

        while time.time() < deadline:
            field = self._get_first_visible_locator(self._otp_input_candidates(page))
            if field:
                return True, "", field

            error_text = self._get_first_visible_text(page, error_patterns)
            if not error_text:
                error_text = self._get_aws_alert_text(page)
            if error_text:
                return False, error_text, None

            self._human_sleep(0.2, 0.6)

        return False, "wait OTP Input box timeout", None

    def _fill_password_fields(self, page: Page, password: str):
        password_field = page.get_by_label("Password", exact=True)
        confirm_field = page.get_by_label("Confirm password", exact=True)

        password_field.first.wait_for(state="visible", timeout=10000)
        confirm_field.first.wait_for(state="visible", timeout=10000)

        for field in (password_field.first, confirm_field.first):
            field.click()
            try:
                field.clear()
            except Exception:
                pass
            for _ in range(2):
                field.fill(password)
                if field.input_value() == password:
                    break
                field.click()
                page.keyboard.press("Control+A")
                page.keyboard.press("Backspace")
            if field.input_value() != password:
                raise RuntimeError("Failed to write password input box")

    def _http_post_json(self, url: str, payload: dict) -> dict:
        headers = {
            "content-type": "application/json",
            "user-agent": "KiroIDE",
        }
        if cffi_requests is not None:
            kwargs: dict[str, Any] = {
                "json": payload,
                "headers": headers,
                "timeout": 30,
                "impersonate": "chrome131",
            }
            if self.proxy:
                proxies = build_requests_proxy_config(self.proxy)
                if proxies:
                    kwargs["proxies"] = proxies
            response = cffi_requests.post(url, **kwargs)
            if response.status_code != 200:
                raise RuntimeError(
                    f"HTTP {response.status_code}: {response.text[:300]}"
                )
            return response.json()

        data = json.dumps(payload).encode("utf-8")
        opener = build_opener()
        request = Request(url, data=data, headers=headers, method="POST")
        with opener.open(request, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    def _capture_kiro_web_tokens(self, page: Page):
        if not self._captured_tokens.get(
            "webAccessToken"
        ) and self._captured_tokens.get("accessToken"):
            self._captured_tokens["webAccessToken"] = self._captured_tokens[
                "accessToken"
            ]

        # Always capture portal cookies (view.awsapps.com) — do this before any early return
        # so that even when webAccessToken/sessionToken are already known, we still save the portal session.
        try:
            all_cookies = self._require_context().cookies()
            # Debug: log all unique domains to understand what's available
            all_domains = sorted(set(c.get("domain", "") for c in all_cookies))
            self.log(f"[Kiro] Cookie domains in context: {all_domains}")
            self._captured_tokens["_debug_cookie_domains"] = all_domains
            portal_cookies = []
            for c in all_cookies:
                domain = c.get("domain", "").lower()
                if "aws" in domain or "amazon" in domain:
                    cookie_dict = {
                        "name": c.get("name"),
                        "value": c.get("value"),
                        "domain": c.get("domain", ""),
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", True),
                        "httpOnly": c.get("httpOnly", False),
                        "sameSite": c.get("sameSite", "None")
                    }
                    if "expires" in c:
                        cookie_dict["expires"] = c["expires"]
                    portal_cookies.append(cookie_dict)
            if portal_cookies:
                self._captured_tokens["portalCookies"] = portal_cookies
                self.log(f"[Kiro] Captured {len(portal_cookies)} portal cookies")
            else:
                self.log("[Kiro] No AWS portal cookies found in browser context")
        except Exception as exc:
            self.log(f"[Kiro] Portal cookie capture failed: {exc}")


        if self._captured_tokens.get("webAccessToken") and self._captured_tokens.get(
            "sessionToken"
        ):
            return

        try:
            all_cookies = self._require_context().cookies()
            cookie_map = {
                c.get("name", ""): c.get("value", "")
                for c in all_cookies
                if c.get("domain", "").endswith("app.kiro.dev")
            }
            if cookie_map.get("AccessToken"):
                self._captured_tokens["webAccessToken"] = cookie_map["AccessToken"]
            if cookie_map.get("SessionToken"):
                self._captured_tokens["sessionToken"] = cookie_map["SessionToken"]
        except Exception:
            pass

        if not self._captured_tokens.get("webAccessToken"):
            try:
                ls = page.evaluate("() => JSON.stringify(window.localStorage)")
                self._captured_tokens.update(
                    self._extract_tokens_from_object(json.loads(ls))
                )
                if self._captured_tokens.get(
                    "accessToken"
                ) and not self._captured_tokens.get("webAccessToken"):
                    self._captured_tokens["webAccessToken"] = self._captured_tokens[
                        "accessToken"
                    ]
            except Exception:
                pass

        if not self._captured_tokens.get("sessionToken"):
            try:
                ss = page.evaluate("() => JSON.stringify(window.sessionStorage)")
                self._captured_tokens.update(
                    self._extract_tokens_from_object(json.loads(ss))
                )
            except Exception:
                pass

    def _register_desktop_client(self, region: str) -> dict:
        self.log("Start registering for desktop OIDC Client ...")
        response = self._http_post_json(
            f"https://oidc.{region}.amazonaws.com/client/register",
            {
                "clientName": "Kiro IDE",
                "clientType": "public",
                "scopes": KIRO_IDC_SCOPES,
                "grantTypes": ["authorization_code", "refresh_token"],
                "redirectUris": ["http://127.0.0.1/oauth/callback"],
                "issuerUrl": KIRO_IDC_START_URL,
            },
        )
        client_id = response.get("clientId", "")
        client_secret = response.get("clientSecret", "")
        if not client_id or not client_secret:
            raise RuntimeError(
                f"Desktop OIDC Client Registration failed: {json.dumps(response, ensure_ascii=False)[:300]}"
            )
        return {
            "clientId": client_id,
            "clientSecret": client_secret,
            "clientSecretExpiresAt": response.get("clientSecretExpiresAt"),
            "clientIdHash": hashlib.sha1(
                json.dumps(
                    {"startUrl": KIRO_IDC_START_URL}, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest(),
        }

    def _exchange_desktop_token(
        self,
        region: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        code: str,
        code_verifier: str,
    ) -> dict:
        self.log("Start exchanging desktop authorization_code ...")
        response = self._http_post_json(
            f"https://oidc.{region}.amazonaws.com/token",
            {
                "clientId": client_id,
                "clientSecret": client_secret,
                "grantType": "authorization_code",
                "redirectUri": redirect_uri,
                "code": code,
                "codeVerifier": code_verifier,
            },
        )
        if not response.get("accessToken") or not response.get("refreshToken"):
            raise RuntimeError(
                f"Desktop token Exchange failed: {json.dumps(response, ensure_ascii=False)[:300]}"
            )
        return response

    def _handle_desktop_auth_page(self, page: Page, email: str = "", pwd: str = ""):
        # Reuse existing AWS The session usually jumps automatically; only when the session is lost, manual login is required.
        try:
            if email:
                email_input = page.locator(
                    'input[placeholder="username@example.com"], input[type="email"]'
                ).first
                if email_input.count() > 0 and email_input.is_visible():
                    self.log("Desktop authorization page requires re-login, filling in Email ...")
                    try:
                        email_input.fill("")
                    except Exception:
                        pass
                    self._type_like_human(page, email_input, email)
                    self._click_primary_button(page)
                    self._human_sleep(0.7, 1.4)
        except Exception:
            pass

        try:
            if pwd:
                password_input = page.locator('input[type="password"]').first
                if password_input.count() > 0 and password_input.is_visible():
                    self.log("The desktop authorization page requires re-login and the password is being filled in. ...")
                    try:
                        password_input.fill("")
                    except Exception:
                        pass
                    password_input.fill(pwd)
                    self._click_primary_button(page)
                    self._human_sleep(0.7, 1.4)
        except Exception:
            pass

        for label in ("Allow", "Continue", "Authorize"):
            try:
                button = page.get_by_role("button", name=label).first
                if button.count() > 0 and button.is_visible():
                    self.log(f"Click on desktop authorization page {label} ...")
                    button.click(timeout=2000)
                    self._human_sleep(0.6, 1.2)
                    break
            except Exception:
                continue

    def _complete_desktop_idc_flow(
        self, email: str = "", pwd: str = "", otp_callback=None
    ) -> dict:
        region = KIRO_IDC_REGION
        client_registration = self._register_desktop_client(region)
        state = str(uuid.uuid4())
        code_verifier = uuid.uuid4().hex + uuid.uuid4().hex
        code_challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_verifier.encode("utf-8")).digest()
            )
            .decode("utf-8")
            .rstrip("=")
        )

        callback_server = _DesktopAuthCallbackServer(expected_state=state)
        callback_server.start()
        auth_page = None
        desktop_otp_used = False
        try:
            redirect_uri = callback_server.redirect_uri
            authorize_url = (
                f"https://oidc.{region}.amazonaws.com/authorize?"
                + urlencode(
                    {
                        "response_type": "code",
                        "client_id": client_registration["clientId"],
                        "redirect_uri": redirect_uri,
                        "scopes": ",".join(KIRO_IDC_SCOPES),
                        "state": state,
                        "code_challenge": code_challenge,
                        "code_challenge_method": "S256",
                    }
                )
            )

            self.log("Start desktop authorization jump ...")
            auth_page = self._require_context().new_page()
            auth_page.goto(authorize_url, wait_until="domcontentloaded", timeout=60000)

            started = time.time()
            while time.time() - started < 120:
                if callback_server._event.is_set():
                    break
                if otp_callback and not desktop_otp_used:
                    try:
                        otp_input = auth_page.locator(
                            'input[placeholder*="6-digit" i], input[name="code"], input[id*="code"]'
                        ).first
                        if otp_input.count() > 0 and otp_input.is_visible():
                            self.log("The desktop authorization page requires an email verification code, and the code is being retrieved. ...")
                            otp_code = otp_callback()
                            if not otp_code:
                                raise RuntimeError("Desktop authorization verification code not obtained")
                            otp_input.fill(str(otp_code))
                            self._click_primary_button(auth_page)
                            desktop_otp_used = True
                            self._human_sleep(0.7, 1.5)
                            continue
                    except Exception as otp_error:
                        raise RuntimeError(
                            f"Desktop authorization verification code processing failed: {otp_error}"
                        ) from otp_error
                self._handle_desktop_auth_page(auth_page, email=email, pwd=pwd)
                self._human_sleep(0.6, 1.3)

            callback = callback_server.wait(timeout=5)
            desktop_token = self._exchange_desktop_token(
                region=region,
                client_id=client_registration["clientId"],
                client_secret=client_registration["clientSecret"],
                redirect_uri=redirect_uri,
                code=callback["code"],
                code_verifier=code_verifier,
            )

            return {
                "accessToken": desktop_token.get("accessToken", ""),
                "refreshToken": desktop_token.get("refreshToken", ""),
                "clientId": client_registration["clientId"],
                "clientSecret": client_registration["clientSecret"],
                "clientIdHash": client_registration["clientIdHash"],
                "region": region,
            }
        finally:
            if auth_page:
                try:
                    auth_page.close()
                except Exception:
                    pass
            callback_server.close()

    def fetch_desktop_tokens(
        self, email: str, pwd: str, otp_callback=None
    ) -> Tuple[bool, dict]:
        page = None
        created_browser = False
        try:
            if not self.context:
                self._init_browser()
                created_browser = True
            page = self._require_context().new_page()
            page.goto(KIRO_SIGNIN_URL, wait_until="domcontentloaded")
            tokens = self._complete_desktop_idc_flow(
                email=email, pwd=pwd, otp_callback=otp_callback
            )
            return True, tokens
        except Exception as e:
            return False, {"error": str(e)}
        finally:
            if page:
                try:
                    page.close()
                except Exception:
                    pass
            if created_browser:
                self._close_browser()

    def register(
        self,
        email: str,
        pwd: Optional[str] = None,
        name: str = "Kiro User",
        mail_token: Optional[str] = None,
        otp_timeout: int = 120,
        otp_callback=None,
    ) -> Tuple[bool, dict]:
        if not pwd:
            pwd = f"Aa!1{uuid.uuid4().hex[:8]}"
        name = self._randomize_name(name)

        self.log(f"start Playwright process, Email: {email}")
        page = None
        try:
            self._init_browser()
            page = self._require_context().new_page()

            if stealth_sync:
                stealth_sync(page)

            self.log("load Kiro Login ...")
            page.goto(KIRO_SIGNIN_URL, wait_until="domcontentloaded")
            self._human_sleep(1.9, 3.4)

            # Debug: dump all buttons to log
            try:
                btns = page.locator("button").all_text_contents()
                links = page.locator("a").all_text_contents()
                self.log(f"Page Buttons: {btns}")
                self.log(f"Page Links: {links}")
            except Exception as e:
                self.log(f"Debug UI failed: {e}")

            if page.locator('button:has-text("Builder ID")').count() > 0:
                page.click('button:has-text("Builder ID")')
            elif page.locator('text="AWS Builder ID"').count() > 0:
                page.locator('text="AWS Builder ID"').first.click()

            self.log("Waiting to jump to AWS SSO ...")
            page.wait_for_url(re.compile(r"signin\.aws"), timeout=30000)
            self._accept_cookie_banner_if_present(page)
            self._solve_captcha_if_exists(page)

            # 1. fill in Email
            self.log("1. fill in Email...")
            # Debug: Print all occurrences of input Understand true attributes
            try:
                inputs_info = []
                for field in page.locator("input").all():
                    inputs_info.append(
                        f"id={field.get_attribute('id')} type={field.get_attribute('type')} name={field.get_attribute('name')}"
                    )
                self.log(f"Page Inputs: {inputs_info}")
            except Exception:
                pass

            # Broad locator covering a large number of aws SSO possible situations
            # AWS The most perverse thing about type="email" No need name="email", but instead dynamically generate something like id="formField14-1774542604278-6990" of type="text"
            email_input = page.locator(
                'input[placeholder="username@example.com"], input[type="email"]'
            ).first
            email_input.wait_for(state="visible", timeout=15000)
            self._type_like_human(
                page,
                'input[placeholder="username@example.com"], input[type="email"]',
                email,
            )
            self._click_primary_button(page)
            self._human_sleep(1.1, 2.4)
            self._solve_captcha_if_exists(page)

            # 2. The actual next step after waiting for the mailbox (some AWS There will be a long delay before the name input box appears on the page)
            self.log("2. Waiting for name or OTP stage...")
            stage, stage_input, stage_error = self._wait_for_post_email_step(
                page, timeout_ms=30000
            )
            if stage == "error":
                return False, {"error": f"Email After submission AWS return error: {stage_error}"}
            if stage == "timeout":
                return False, {"error": stage_error}

            otp_input = stage_input if stage == "otp" else None
            if stage == "name":
                self.log("2. Fill in the name (Your name)...")
                if stage_input is None:
                    return False, {"error": "Name input box not found"}
                self._type_like_human(page, stage_input, name)
                self._click_primary_button(page)
                self._human_sleep(1.1, 2.4)

                self.log("3. Waiting for trigger OTP...")
                otp_ready, otp_wait_error, otp_input = self._wait_for_otp_step(
                    page, timeout_ms=30000
                )
            else:
                self.log("2. Enter the current process directly OTP, skip filling in the name")
                otp_ready, otp_wait_error = True, ""

            if not otp_ready:
                return False, {"error": f"After name submission AWS return error: {otp_wait_error}"}

            otp_code = None
            if otp_callback:
                otp_code = otp_callback()

            if not otp_code:
                return False, {"error": "Email verification code not obtained(OTP Timeout)"}

            self.log(f"Get verification code: {otp_code}, filling in...")
            if otp_input is None:
                return False, {"error": "not found OTP Input box"}
            self._type_like_human(page, otp_input, otp_code)
            self._click_primary_button(page)
            self._human_sleep(1.0, 2.2)

            # 4. Set and confirm password
            self.log("4. Set and confirm password...")
            password_ready, otp_error = self._wait_for_password_step(
                page, timeout_ms=15000
            )
            if not password_ready:
                return False, {"error": f"OTP Failed after submission: {otp_error}"}

            self._fill_password_fields(page, pwd)

            self._click_primary_button(page)
            self._human_sleep(1.3, 2.8)
            self._solve_captcha_if_exists(page)

            password_error = self._get_first_visible_text(
                page,
                [
                    re.compile(r"passwords must match", re.I),
                    re.compile(r"invalid password", re.I),
                    re.compile(r"enter password", re.I),
                ],
            )
            if password_error:
                return False, {"error": f"Password setting failed: {password_error}"}

            # 5. callback authorization
            allow_btn = page.locator('text="Allow"')
            if allow_btn.count() > 0:
                self.log("Click Allow Authorize application...")
                allow_btn.click()

            # 6. Waiting for return Kiro take Token
            self.log("waiting to return Kiro...")
            try:
                # At least wait until it completes the request CompleteLogin
                page.wait_for_url(re.compile(r"kiro\.dev"), timeout=30000)
                self._human_sleep(3.0, 5.8)
            except TimeoutError:
                pass

            if "kiro.dev" not in page.url:
                err_text = ""
                # try to extract some error
                if page.locator(".awsui-alert-content").count() > 0:
                    err_text = page.locator(".awsui-alert-content").text_content()
                self.log(f"Not returned Kiro,current URL: {page.url}")
                try:
                    self.log(f"Current page title: {page.title()}")
                except Exception:
                    pass
                try:
                    self.log(
                        f"Current page button: {page.locator('button').all_text_contents()}"
                    )
                except Exception:
                    pass
                try:
                    page.screenshot(path="kiro_return_error.png")
                    self.log("The screenshot of failure to jump back has been saved as kiro_return_error.png")
                    with open("kiro_return_error.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    self.log("Rebound failed HTML saved as kiro_return_error.html")
                except Exception:
                    pass

                return False, {"error": f"Failed to return to kiro.dev - {err_text}"}

            self._capture_kiro_web_tokens(page)

            # For subsequent refreshes, etc., there must be token
            if not self._captured_tokens.get("webAccessToken"):
                self.log(f"current URL: {page.url}")
                try:
                    self.log(
                        f"localStorage: {page.evaluate('() => JSON.stringify(window.localStorage)')[:2000]}"
                    )
                except Exception:
                    pass
                try:
                    self.log(
                        f"sessionStorage: {page.evaluate('() => JSON.stringify(window.sessionStorage)')[:2000]}"
                    )
                except Exception:
                    pass
                try:
                    cookies = [
                        {
                            "name": c.get("name", ""),
                            "domain": c.get("domain", ""),
                            "path": c.get("path", ""),
                        }
                        for c in self._require_context().cookies()
                        if "kiro.dev" in c.get("domain", "")
                        or "aws" in c.get("domain", "")
                    ]
                    self.log(f"Cookies: {json.dumps(cookies[:20], ensure_ascii=False)}")
                except Exception:
                    pass
                if self._network_debug:
                    self.log(
                        f"Network debugging sample: {json.dumps(self._network_debug[-15:], ensure_ascii=False)}"
                    )
                try:
                    page.screenshot(path="kiro_token_error.png")
                    self.log("Token The screenshot of failed extraction has been saved as kiro_token_error.png")
                    with open("kiro_token_error.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    self.log("Token Failed to extract HTML saved as kiro_token_error.html")
                except Exception:
                    pass
                return False, {
                    "error": "Registration appears to be complete, but cannot be extracted OAuth Token. It may be that the network interception failed."
                }

            try:
                desktop_tokens = self._complete_desktop_idc_flow(email=email, pwd=pwd)
                self._captured_tokens.update(desktop_tokens)
                self.log("Desktop Builder ID Token The catch-up has been completed")
                try:
                    self._capture_kiro_web_tokens(page)
                except Exception as capture_err:
                    self.log(f"⚠️ Failed to recapture portal cookies: {capture_err}")
            except Exception as desktop_error:
                self.log(f"⚠️ Desktop Builder ID Token Failed to catch up: {desktop_error}")

            return True, {
                "email": email,
                "password": pwd,
                "name": name,
                "accessToken": self._captured_tokens.get("accessToken", "")
                or self._captured_tokens.get("webAccessToken", ""),
                "refreshToken": self._captured_tokens.get("refreshToken", ""),
                "clientId": self._captured_tokens.get("clientId", ""),
                "clientSecret": self._captured_tokens.get("clientSecret", ""),
                "clientIdHash": self._captured_tokens.get("clientIdHash", ""),
                "region": self._captured_tokens.get("region", KIRO_IDC_REGION),
                "sessionToken": self._captured_tokens.get("sessionToken", ""),
                "webAccessToken": self._captured_tokens.get("webAccessToken", ""),
                "portalCookies": self._captured_tokens.get("portalCookies", []),
                "userAgent": self._captured_tokens.get("userAgent", ""),
            }

        except Exception as e:
            self.log(f"❌ Playwright encountered an exception: {e}")
            # Save the screenshot for easy troubleshooting
            try:
                if page:
                    page.screenshot(path="kiro_error.png")
                    self.log("Screenshot saved as kiro_error.png")

                    with open("kiro_error.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    self.log("HTML saved as kiro_error.html")
            except Exception:
                pass
            return False, {"error": str(e)}
        finally:
            self._close_browser()
