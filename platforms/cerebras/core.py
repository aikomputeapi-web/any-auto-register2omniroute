"""
Cerebras AI Cloud Automatic registration with API key generation
"""

import re
import os
import time
import random
import string
import ctypes
import urllib.parse
from typing import Optional, Tuple, Callable, Any
from playwright.sync_api import sync_playwright, TimeoutError, Page
from core.browser_runtime import ensure_browser_display_available, resolve_browser_headless
from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

CEREBRAS_BASE = "https://cloud.cerebras.ai"
CEREBRAS_API_KEYS = f"{CEREBRAS_BASE}/api-keys"


def _rand_password(n=16):
    chars = string.ascii_letters + string.digits + "!@#$%"
    pw = (
        random.choice(string.ascii_uppercase)
        + random.choice(string.ascii_lowercase)
        + random.choice(string.digits)
        + random.choice("!@#$%")
        + "".join(random.choices(chars, k=n - 4))
    )
    lst = list(pw)
    random.shuffle(lst)
    return "".join(lst)


class CerebrasRegister:
    def __init__(self, proxy: str = None, headless: bool = True, captcha_solver = None, cdp_endpoint: str = None, use_real_chrome: bool = True):
        self.proxy = proxy
        self.headless = headless
        self.captcha_solver = captcha_solver
        self.cdp_endpoint = cdp_endpoint
        self.use_real_chrome = use_real_chrome
        self.pw = None
        self.browser = None
        self.context = None
        self._chrome_proc = None
        self._cdp_port = None
        self._using_real_chrome = False
        self._chrome_profile = None

    def log(self, msg):
        safe = str(msg).encode("ascii", "replace").decode("ascii")
        print(f"[Cerebras] {safe}")

    def _human_sleep(self, min_sec: float = 0.5, max_sec: float = 1.5):
        time.sleep(random.uniform(min_sec, max_sec))

    @staticmethod
    def _find_chrome_path() -> str:
        """Locate a system Chrome/Edge binary."""
        import shutil
        candidates = []
        if os.name == "nt":
            for p in [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ]:
                candidates.append(p)
        else:
            for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"]:
                p = shutil.which(name)
                if p:
                    candidates.append(p)
        for c in candidates:
            if os.path.isfile(c):
                return c
        return ""

    def _launch_real_chrome(self) -> str:
        """Launch a real Chrome with --remote-debugging-port and return the CDP endpoint."""
        import subprocess
        import socket
        import urllib.request as _urlreq

        chrome_path = self._find_chrome_path()
        if not chrome_path:
            return ""

        # Pick a free port for the debugging endpoint.
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        # Use a fresh temp profile each run to avoid stale sessions and
        # reCAPTCHA rate-limiting tied to a single profile.
        import tempfile
        profile_dir = tempfile.mkdtemp(prefix="cerebras-chrome-")

        args = [
            chrome_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--disable-sync",
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--window-size=1280,800",
        ]
        if self.headless:
            args.append("--headless=new")
        if self.proxy:
            args.append(f"--proxy-server={self.proxy}")
        args.append("about:blank")

        self._chrome_proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._cdp_port = port
        self._chrome_profile = profile_dir

        # Wait for the CDP endpoint to be ready.
        endpoint = f"http://127.0.0.1:{port}"
        for _ in range(30):
            try:
                _urlreq.urlopen(f"{endpoint}/json/version", timeout=2)
                return endpoint
            except Exception:
                if self._chrome_proc.poll() is not None:
                    break
                time.sleep(0.5)
        return ""

    def _init_browser(self):
        self.pw = sync_playwright().start()
        us_loc = resolve_us_profile(self.proxy)

        # Prefer a real Chrome (launched with --remote-debugging-port) because
        # Playwright's bundled Chromium is flagged by reCAPTCHA/Clerk bot
        # detection, which blocks registration. Fall back to an explicit CDP
        # endpoint, then to Playwright Chromium.
        endpoint = self.cdp_endpoint
        if not endpoint and self.use_real_chrome:
            endpoint = self._launch_real_chrome()
            if endpoint:
                self.log(f"Launched real Chrome on {endpoint}")

        if endpoint:
            self.log(f"Connecting to real Chrome via CDP: {endpoint}")
            self.browser = self.pw.chromium.connect_over_cdp(endpoint)
            existing = self.browser.contexts
            if existing:
                self.context = existing[0]
            else:
                self.context = self.browser.new_context()
            self._using_real_chrome = True
            self.log("Connected to real Chrome via CDP (less detectable)")
            return

        headless, reason = resolve_browser_headless(self.headless, default_headless=True)
        ensure_browser_display_available(headless)

        launch_opts = {
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        }
        if self.proxy:
            proxy_cfg = build_playwright_proxy_config(self.proxy)
            if proxy_cfg:
                launch_opts["proxy"] = proxy_cfg

        self.browser = self.pw.chromium.launch(**launch_opts)
        self.context = self.browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            locale=us_loc["locale"],
            timezone_id=us_loc["timezone"],
            geolocation={"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
            permissions=["geolocation"],
        )
        self.log(f"Browser mode: {'headless' if headless else 'headed'} ({reason})")

    def _log_page_state(self, page: Page, label: str = ""):
        try:
            url = page.url
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=2000)[:400]
            except Exception:
                pass
            self.log(f"Page state{' (' + label + ')' if label else ''}: url={url} body={body!r}")
        except Exception:
            pass

    def _close_browser(self):
        # When connected via CDP the browser is external; do not close it via
        # Playwright. If we launched the Chrome ourselves, terminate it.
        if self.cdp_endpoint or self._chrome_proc:
            if self.pw:
                try:
                    self.pw.stop()
                except:
                    pass
            if self._chrome_proc:
                try:
                    self._chrome_proc.terminate()
                    self._chrome_proc.wait(timeout=5)
                except Exception:
                    try:
                        self._chrome_proc.kill()
                    except Exception:
                        pass
                self._chrome_proc = None
            # Clean up the temp profile directory.
            if self._chrome_profile:
                try:
                    import shutil
                    shutil.rmtree(self._chrome_profile, ignore_errors=True)
                except Exception:
                    pass
                self._chrome_profile = None
            return
        if self.context:
            try:
                self.context.close()
            except:
                pass
        if self.browser:
            try:
                self.browser.close()
            except:
                pass
        if self.pw:
            try:
                self.pw.stop()
            except:
                pass

    def _type_human(self, page: Page, selector: str, text: str):
        self._human_sleep(0.3, 0.7)
        el = page.locator(selector).first
        el.click()
        el.fill("")
        for char in text:
            page.keyboard.type(char, delay=random.randint(50, 150))
        self._human_sleep(0.2, 0.5)

    def _extract_site_key(self, page: Page) -> str:
        # Check if we can find reCAPTCHA sitekey dynamically
        site_keys = []
        try:
            iframes = page.locator('iframe[src*="recaptcha"]').all()
            for iframe in iframes:
                src = iframe.get_attribute("src")
                if src:
                    parsed = urllib.parse.urlparse(src)
                    params = urllib.parse.parse_qs(parsed.query)
                    if "k" in params:
                        sk = params["k"][0]
                        visible = iframe.is_visible()
                        site_keys.append({"key": sk, "visible": visible})
        except Exception as e:
            self.log(f"Error extracting sitekey dynamically: {e}")

        # Choose the best sitekey: prefer visible iframes
        for entry in site_keys:
            if entry["visible"]:
                self.log(f"Extracted visible reCAPTCHA sitekey dynamically: {entry['key']}")
                return entry["key"]
                
        if site_keys:
            self.log(f"Extracted first reCAPTCHA sitekey dynamically: {site_keys[0]['key']}")
            return site_keys[0]["key"]

        default_key = "6LdnMCUrAAAAAJ7n8mbQNU6YbWxxARSlZC3Mkuv9"
        self.log(f"Using default reCAPTCHA sitekey: {default_key}")
        return default_key

    def _extract_all_recaptcha_info(self, page: Page) -> list:
        """Return a list of {sitekey, invisible, enterprise, visible} for every
        reCAPTCHA iframe currently in the DOM."""
        results = []
        try:
            iframes = page.locator('iframe[src*="recaptcha"]').all()
            for iframe in iframes:
                src = iframe.get_attribute("src") or ""
                parsed = urllib.parse.urlparse(src)
                params = urllib.parse.parse_qs(parsed.query)
                sk = params.get("k", [""])[0]
                if not sk:
                    continue
                try:
                    visible = iframe.is_visible()
                except Exception:
                    visible = False
                results.append({
                    "sitekey": sk,
                    "invisible": params.get("size", [""])[0] == "invisible",
                    "enterprise": "enterprise" in src,
                    "visible": visible,
                })
        except Exception as e:
            self.log(f"Error extracting reCAPTCHA info: {e}")
        return results

    def _solve_recaptcha_robust(self, page: Page, sitekey: str, invisible: bool, enterprise: bool) -> str:
        """Solve a reCAPTCHA, retrying with the opposite invisible flag if the
        solver rejects the task data (some widgets report the wrong size)."""
        for inv in ([invisible, not invisible] if invisible else [invisible, True]):
            try:
                self.log(f"Solving reCAPTCHA (enterprise={enterprise}, invisible={inv})...")
                token = self.captcha_solver.solve_recaptcha(
                    page.url, sitekey, enterprise=enterprise, invisible=inv
                )
                if token:
                    return token
            except Exception as e:
                msg = str(e)
                self.log(f"  Solve with invisible={inv} failed: {msg[:160]}")
                if "ERROR_INVALID_TASK_DATA" not in msg and "invisible" not in msg.lower():
                    raise
        return ""

    def _inject_recaptcha_response(self, page: Page, token: str, site_key: str) -> bool:
        self.log("Injecting reCAPTCHA token and hooking execute method...")
        js_code = """(args) => {
            const token = args.token;
            const site_key = args.site_key;
            
            // 1. Inject into textareas
            const textareas = document.querySelectorAll('textarea[id^="g-recaptcha-response"], textarea[name="g-recaptcha-response"]');
            textareas.forEach(ta => {
                ta.value = token;
                ta.dispatchEvent(new Event('input', { bubbles: true }));
                ta.dispatchEvent(new Event('change', { bubbles: true }));
            });
            
            // 2. Hook grecaptcha.enterprise.execute/getResponse and grecaptcha.execute/getResponse
            if (typeof grecaptcha !== 'undefined') {
                if (grecaptcha.enterprise) {
                    if (typeof grecaptcha.enterprise.execute === 'function') {
                        grecaptcha.enterprise.execute = () => Promise.resolve(token);
                    }
                    if (typeof grecaptcha.enterprise.getResponse === 'function') {
                        grecaptcha.enterprise.getResponse = () => token;
                    }
                }
                if (typeof grecaptcha.execute === 'function') {
                    grecaptcha.execute = () => Promise.resolve(token);
                }
                if (typeof grecaptcha.getResponse === 'function') {
                    grecaptcha.getResponse = () => token;
                }
            }
            
            // Helper to recursively find sitekey in a client object
            function findSitekeyInObject(obj, targetSitekey, depth = 0) {
                if (depth > 8) return false;
                if (!obj || typeof obj !== 'object') return false;
                for (const key in obj) {
                    try {
                        const val = obj[key];
                        if (typeof val === 'string' && val === targetSitekey) {
                            return true;
                        } else if (typeof val === 'object' && val !== null) {
                            if (!(val instanceof HTMLElement)) {
                                if (findSitekeyInObject(val, targetSitekey, depth + 1)) {
                                    return true;
                                }
                            }
                        }
                    } catch(e) {}
                }
                return false;
            }
            
            // Helper to recursively find and execute callbacks
            function triggerCallbacks(obj, depth = 0) {
                if (depth > 8) return;
                if (!obj || typeof obj !== 'object') return;
                
                for (const key in obj) {
                    try {
                        const val = obj[key];
                        if (typeof val === 'function') {
                            const lk = key.toLowerCase();
                            if (lk === 'callback' || lk === 'promise-callback'
                                || lk === 'success-callback' || lk === 'cb'
                                || lk.indexOf('callback') !== -1) {
                                val(token);
                                called = true;
                            }
                        } else if (typeof val === 'object' && val !== null) {
                            if (!(val instanceof HTMLElement)) {
                                triggerCallbacks(val, depth + 1);
                            }
                        }
                    } catch (e) {}
                }
            }
            
            // 3. Robust traversal of ___grecaptcha_cfg.clients matching site_key
            let called = false;
            if (window.___grecaptcha_cfg && window.___grecaptcha_cfg.clients) {
                const clients = window.___grecaptcha_cfg.clients;
                for (const clientKey in clients) {
                    const client = clients[clientKey];
                    if (findSitekeyInObject(client, site_key)) {
                        triggerCallbacks(client);
                    }
                }
            }
            return called;
        }"""
        result = page.evaluate(js_code, {"token": token, "site_key": site_key})
        self.log(f"reCAPTCHA callback injection result: {result}")
        return result

    # ------------------------------------------------------------------
    # Cloudflare Turnstile helpers (ported from grok/openrouter platforms).
    # Cerebras fronts its Clerk-powered signup with Cloudflare Turnstile;
    # without solving it, the #clerk-components container stays empty and
    # the OTP/magic-link screen never renders.
    # ------------------------------------------------------------------
    @staticmethod
    def _find_turnstile_widget(page) -> Tuple[Optional[Any], Optional[dict]]:
        """Locate the visible Cloudflare Turnstile iframe and its bounding box."""
        for frame in page.frames:
            if "challenges.cloudflare.com" not in frame.url:
                continue
            try:
                frame_el = frame.frame_element()
                box = frame_el.bounding_box()
            except Exception:
                box = None
            if box and box["width"] > 100 and box["height"] >= 50:
                return frame, box
        return None, None

    @staticmethod
    def _read_turnstile_token(page) -> str:
        return page.evaluate(
            """() => {
                return (
                    document.querySelector('input[id^="cf-chl-widget-"]')?.value ||
                    document.querySelector('input[name="cf-turnstile-response"]')?.value ||
                    ''
                );
            }"""
        )

    def _read_turnstile_sitekey(self, page) -> str:
        sitekey = page.evaluate(
            """() => {
                const byData = document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey');
                if (byData) return byData;
                for (const iframe of document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]')) {
                    try {
                        const u = new URL(iframe.src, location.href);
                        const k = u.searchParams.get('k');
                        if (k) return k;
                    } catch (_) {}
                }
                return '';
            }"""
        )
        if sitekey:
            return sitekey

        # Search across all frames (Clerk renders Turnstile inside nested iframes)
        for frame in page.frames:
            if "challenges.cloudflare.com" in frame.url:
                try:
                    parsed = urllib.parse.urlparse(frame.url)
                    k = urllib.parse.parse_qs(parsed.query).get("k", [""])[0]
                    if k:
                        return k
                except Exception:
                    pass
            try:
                k = frame.evaluate(
                    """() => {
                        const byData = document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey');
                        if (byData) return byData;
                        for (const iframe of document.querySelectorAll('iframe[src*="challenges.cloudflare.com"]')) {
                            try {
                                const u = new URL(iframe.src, location.href);
                                const k = u.searchParams.get('k');
                                if (k) return k;
                            } catch (_) {}
                        }
                        return '';
                    }"""
                )
                if k:
                    return k
            except Exception:
                pass

        # Last resort: search page source for a Turnstile sitekey (starts with 0x)
        try:
            src = page.content()
            matches = re.findall(r'["\']?(0x[A-Za-z0-9_-]{20,})["\']?', src)
            for m in matches:
                if len(m) >= 20:
                    return m
        except Exception:
            pass
        return ""

    @staticmethod
    def _has_turnstile_error(page) -> bool:
        keywords = [
            "Authentication failed",
            "troubleshooting",
            "verification failed",
            "troubleshoot",
            "try again",
        ]
        texts = []
        try:
            texts.append(page.locator("body").inner_text(timeout=800))
        except Exception:
            pass
        for frame in page.frames:
            if "challenges.cloudflare.com" not in frame.url:
                continue
            try:
                texts.append(frame.locator("body").inner_text(timeout=500))
            except Exception:
                continue
        merged = "\n".join(texts).lower()
        return any(k.lower() in merged for k in keywords)

    @staticmethod
    def _inject_turnstile_token(page, token: str) -> bool:
        return bool(
            page.evaluate(
                """(token) => {
                    const selectors = [
                        'input[id^="cf-chl-widget-"]',
                        'input[name="cf-turnstile-response"]',
                        'textarea[name="cf-turnstile-response"]',
                        'textarea[name="g-recaptcha-response"]',
                    ];
                    const inputs = [];
                    for (const sel of selectors) {
                        document.querySelectorAll(sel).forEach((el) => inputs.push(el));
                    }
                    if (!inputs.length) {
                        const fallback = document.createElement('input');
                        fallback.type = 'hidden';
                        fallback.name = 'cf-turnstile-response';
                        document.body.appendChild(fallback);
                        inputs.push(fallback);
                    }
                    for (const el of inputs) {
                        el.value = token;
                        el.setAttribute('value', token);
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    return inputs.length > 0;
                }""",
                token,
            )
        )

    def _wait_turnstile_token(self, page, wait_rounds: int = 25, wait_ms: int = 500) -> str:
        for _ in range(wait_rounds):
            token = self._read_turnstile_token(page)
            if token and len(token) > 20:
                return token
            page.wait_for_timeout(wait_ms)
        return ""

    def _native_click_turnstile(self, page, box, offset_x: float) -> str:
        try:
            user32 = ctypes.windll.user32
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
        except Exception as e:
            raise RuntimeError(f"Native clicks not supported on this system: {e}") from e

        page.bring_to_front()
        metrics = page.evaluate(
            """() => ({
                screenX,
                screenY,
                outerWidth,
                outerHeight,
                innerWidth,
                innerHeight,
                dpr: window.devicePixelRatio,
            })"""
        )
        border_x = max(0, (metrics["outerWidth"] - metrics["innerWidth"]) / 2)
        chrome_y = max(0, metrics["outerHeight"] - metrics["innerHeight"] - border_x)
        raw_x = metrics["screenX"] + border_x + box["x"] + offset_x
        raw_y = metrics["screenY"] + chrome_y + box["y"] + box["height"] / 2
        dpr = float(metrics.get("dpr") or 1.0)
        points = [(raw_x, raw_y)]
        if abs(dpr - 1.0) > 0.05:
            points.append((raw_x * dpr, raw_y * dpr))
        for idx, (screen_x, screen_y) in enumerate(points, start=1):
            self.log(f"  Native click #{idx}: ({screen_x:.1f}, {screen_y:.1f})")
            user32.SetCursorPos(int(screen_x), int(screen_y))
            time.sleep(0.15)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            time.sleep(0.12)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            token = self._wait_turnstile_token(page, wait_rounds=18, wait_ms=450)
            if token:
                return token
        raise RuntimeError("Native click did not produce a Turnstile token")

    def _solve_turnstile_by_solver(self, page) -> str:
        if not self.captcha_solver:
            return ""
        solver_name = type(self.captcha_solver).__name__.lower()
        if "manual" in solver_name:
            return ""
        client_key = getattr(self.captcha_solver, "client_key", None)
        if client_key is not None and not str(client_key).strip():
            self.log("  No captcha solver key configured, skipping solver service")
            return ""
        sitekey = self._read_turnstile_sitekey(page)
        if not sitekey:
            self.log("  Could not extract Turnstile sitekey, skipping solver service")
            return ""
        self.log(f"  Calling captcha service to solve Turnstile (sitekey={sitekey[:8]}...)")
        try:
            token = self.captcha_solver.solve_turnstile(page.url, sitekey)
        except Exception as e:
            self.log(f"  Solver raised: {e}")
            return ""
        if not token:
            return ""
        if self._inject_turnstile_token(page, token):
            page.wait_for_timeout(400)
            return self._read_turnstile_token(page) or token
        return ""

    def _solve_turnstile_on_page(self, page) -> str:
        self.log("Solving Cloudflare Turnstile challenge...")
        last_error = None

        # 1. Try the captcha solver service first (fastest and most reliable)
        try:
            token = self._solve_turnstile_by_solver(page)
            if token:
                self.log(f"  Turnstile token (solver): {token[:40]}...")
                return token
        except Exception as e:
            last_error = str(e)
            self.log(f"  Solver failed ({e}), falling back to click method...")

        # 2. Fall back to click-based solving
        for attempt in range(8):
            frame, box = self._find_turnstile_widget(page)
            if not box:
                page.wait_for_timeout(1000)
                if last_error is None:
                    last_error = "No clickable Turnstile iframe found"
                continue

            click_x = box["x"] + min(28, max(18, box["width"] * 0.08))
            click_y = box["y"] + box["height"] / 2
            self.log(f"  Turnstile click #{attempt + 1}: ({click_x:.1f}, {click_y:.1f})")
            try:
                if frame:
                    frame.locator("body").click(
                        position={
                            "x": min(28, max(18, box["width"] * 0.08)),
                            "y": box["height"] / 2,
                        },
                        timeout=2500,
                    )
                    page.wait_for_timeout(120)
                page.mouse.move(click_x, click_y)
                page.mouse.down()
                page.wait_for_timeout(120)
                page.mouse.up()
                token = self._wait_turnstile_token(page, wait_rounds=28, wait_ms=450)
                if token:
                    self.log(f"  Turnstile token: {token[:40]}...")
                    return token
            except Exception as e:
                last_error = str(e)

            try:
                token = self._native_click_turnstile(
                    page, box, min(28, max(18, box["width"] * 0.08))
                )
                if token:
                    self.log(f"  Turnstile token: {token[:40]}...")
                    return token
            except Exception as e:
                last_error = str(e)

            if self._has_turnstile_error(page):
                self.log("  Turnstile verification failed prompt detected, retrying...")
            page.wait_for_timeout(500)

        if last_error:
            self.log(f"  Turnstile solving exhausted: {last_error}")
        return ""

    def _complete_onboarding(self, page: Page, max_steps: int = 8):
        """Walk through Cerebras new-account onboarding screens."""
        for step in range(max_steps):
            curr_url = page.url
            if "onboarding" not in curr_url:
                self.log(f"Onboarding complete (url={curr_url})")
                return
            self.log(f"Onboarding step {step + 1} (url={curr_url})")

            # Fill any visible text inputs (name, org, etc.)
            try:
                for inp in page.locator('input[type="text"], input:not([type])').all():
                    try:
                        if inp.is_visible():
                            ph = (inp.get_attribute("placeholder") or "").lower()
                            name_attr = (inp.get_attribute("name") or "").lower()
                            if "name" in ph or "name" in name_attr:
                                if "first" in ph or "first" in name_attr:
                                    inp.fill("Alex")
                                elif "last" in ph or "last" in name_attr:
                                    inp.fill("Morgan")
                                else:
                                    inp.fill("Alex Morgan")
                            elif "org" in ph or "company" in ph or "organization" in name_attr:
                                inp.fill("AutoOrg")
                            elif not inp.input_value():
                                inp.fill("Alex")
                    except Exception:
                        pass
            except Exception:
                pass

            # Check any terms/consent checkboxes
            try:
                for cb in page.locator('input[type="checkbox"]').all():
                    try:
                        if cb.is_visible() and not cb.is_checked():
                            cb.check()
                    except Exception:
                        pass
            except Exception:
                pass

            # Click the primary action button to advance
            advanced = False
            for sel in [
                'button:has-text("Continue")',
                'button:has-text("Next")',
                'button:has-text("Get Started")',
                'button:has-text("Agree")',
                'button:has-text("Accept")',
                'button:has-text("Finish")',
                'button:has-text("Complete")',
                'button:has-text("Submit")',
                'button:has-text("Start")',
                'button[type="submit"]',
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.count() > 0 and btn.is_visible() and not btn.is_disabled():
                        self.log(f"  Clicking onboarding button: {sel}")
                        btn.click()
                        advanced = True
                        break
                except Exception:
                    pass

            if not advanced:
                # Page might still be rendering; wait and retry once.
                page.wait_for_timeout(2000)
                continue

            # Wait for the URL to change or the page to settle.
            prev_url = curr_url
            for _ in range(8):
                self._human_sleep(0.5, 1)
                if page.url != prev_url:
                    break
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

    def register(
        self,
        email: str,
        password: Optional[str] = None,
        otp_callback: Optional[Callable[[], str]] = None,
    ) -> Tuple[bool, dict]:
        if not password:
            password = _rand_password()

        page = None
        try:
            self._init_browser()
            page = self.context.new_page()

            # Clear any stale session so we always land on the signup form.
            try:
                self.context.clear_cookies()
            except Exception:
                pass

            # Step 1: Navigate to signup page
            self.log(f"Navigating to Cerebras signup page for {email}")
            page.goto(CEREBRAS_BASE, wait_until="domcontentloaded", timeout=30000)
            self._human_sleep(2, 4)

            # Accept cookies if present
            try:
                cookie_btn = page.locator('button:has-text("Accept All"), button:has-text("Accept"), button:has-text("Reject All")').first
                if cookie_btn.count() > 0 and cookie_btn.is_visible():
                    self.log("Accepting cookie consent...")
                    cookie_btn.click()
                    self._human_sleep(0.5, 1)
            except Exception as e:
                self.log(f"Failed to handle cookie consent: {e}")

            # Check if email input is already there
            page.wait_for_selector('input[type="email"], input#email', timeout=15000)
            self.log("Filling email...")
            self._type_human(page, 'input[type="email"], input#email', email)
            self._human_sleep(1, 2)

            # Pre-solve the invisible reCAPTCHA Enterprise before submitting.
            # Cerebras uses an invisible enterprise reCAPTCHA executed via
            # grecaptcha.enterprise.execute() on form submit. Solving up front
            # and hooking execute() to return our token lets the submit handler
            # receive a valid token on the first try.
            # When using a real Chrome via CDP, skip this — the browser solves
            # reCAPTCHA naturally with a high score, and hooking execute() would
            # replace that token with a lower-score solver token.
            recaptcha_ready = False
            if not self._using_real_chrome:
                for _ in range(10):
                    recaptcha_ready = page.evaluate(
                        "() => typeof grecaptcha !== 'undefined' && !!grecaptcha.enterprise"
                    )
                    if recaptcha_ready:
                        break
                    page.wait_for_timeout(500)

            landing_sitekey = ""
            if recaptcha_ready and self.captcha_solver:
                self.log("reCAPTCHA Enterprise detected, pre-solving before submit...")
                landing_sitekey = self._extract_site_key(page)
                captcha_token = self.captcha_solver.solve_recaptcha(
                    page.url, landing_sitekey, enterprise=True, invisible=True
                )
                self.log("reCAPTCHA solved successfully")
                self._inject_recaptcha_response(page, captcha_token, landing_sitekey)
                self._human_sleep(1, 2)
            else:
                self.log("reCAPTCHA not ready or no solver; submitting without pre-solve")

            # Submit the sign up form (the hooked execute() returns our token).
            # The callback injection may auto-submit the form, so guard the click.
            self.log("Submitting sign up form...")
            try:
                submit_btn = page.locator('button[type="submit"]').first
                if submit_btn.count() > 0 and submit_btn.is_visible():
                    if submit_btn.is_disabled():
                        self.log("Submit button is disabled, attempting to force click via JS...")
                        page.evaluate("el => el.removeAttribute('disabled')", submit_btn.element_handle())
                        page.evaluate("el => el.click()", submit_btn.element_handle())
                    else:
                        submit_btn.click()
                else:
                    self.log("Submit button not visible (form may have auto-submitted)")
            except Exception as se:
                self.log(f"Submit click skipped: {se}")

            self._human_sleep(2, 4)

            # Wait for Clerk OTP inputs or Magic Link screen to appear.
            # NOTE: the reCAPTCHA iframe is always present in the DOM, so its
            # visibility is NOT a reliable signal of a captcha block. We wait
            # for the actual verification screen and only fall back to
            # re-solving if it never appears.
            otp_selectors = [
                'input[maxlength="1"][type="text"]',
                '.cl-otpCodeField input',
                '.cl-otpCodeFieldInput',
                'input[autocomplete="one-time-code"]',
                'input[name="code"]',
            ]
            magic_link_selectors = [
                'text="Check your email"',
                'h1:has-text("Check your email")',
                'button:has-text("Go back")',
            ]

            code_input_found = False
            magic_link_screen_found = False

            for _w in range(20):
                for sel in otp_selectors:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        code_input_found = True
                        break
                if code_input_found:
                    break
                for sel in magic_link_selectors:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        magic_link_screen_found = True
                        break
                if magic_link_screen_found:
                    break
                if _w % 5 == 0:
                    self._log_page_state(page, f"waiting for verification screen ({_w}s)")
                page.wait_for_timeout(1000)

            # Fallback: if the verification screen never appeared, Clerk likely
            # raised a visible reCAPTCHA challenge (bot detection). Detect any
            # challenge widget (a reCAPTCHA whose sitekey differs from the
            # landing page, or any visible one), solve it, inject the token and
            # trigger its callback, then wait for the verification screen.
            if not code_input_found and not magic_link_screen_found:
                if not self.captcha_solver:
                    raise RuntimeError("No captcha solver configured for reCAPTCHA")

                all_captchas = self._extract_all_recaptcha_info(page)
                self.log(f"reCAPTCHA widgets on page: {all_captchas}")

                # Prioritise challenge widgets: a visible widget, or one whose
                # sitekey differs from the (known) landing-page sitekey. When
                # the landing sitekey is unknown (pre-solve skipped), only
                # visible widgets count — the invisible landing-page reCAPTCHA
                # is always present and is NOT a challenge.
                challenges = [
                    c for c in all_captchas
                    if c["visible"] or (landing_sitekey and c["sitekey"] != landing_sitekey)
                ]

                for ch in challenges:
                    self.log(
                        f"Solving challenge reCAPTCHA sitekey={ch['sitekey'][:12]}... "
                        f"(invisible={ch['invisible']}, enterprise={ch['enterprise']}, visible={ch['visible']})"
                    )
                    token = self._solve_recaptcha_robust(
                        page, ch["sitekey"], ch["invisible"], ch["enterprise"]
                    )
                    if not token:
                        continue
                    self.log("reCAPTCHA challenge solved successfully")
                    self._inject_recaptcha_response(page, token, ch["sitekey"])
                    self._human_sleep(2, 4)

                    # Some flows need an explicit re-submit / continue click.
                    try:
                        for sel in [
                            'button:has-text("Continue")',
                            'button:has-text("Verify")',
                            'button:has-text("Submit")',
                            'button[type="submit"]',
                        ]:
                            btn = page.locator(sel).first
                            if btn.count() > 0 and btn.is_visible() and not btn.is_disabled():
                                self.log(f"Clicking '{sel}' after challenge solve...")
                                btn.click()
                                break
                    except Exception as se:
                        self.log(f"Post-challenge click skipped: {se}")

                    self._human_sleep(3, 5)

                    # Re-check for the verification screen.
                    for _ in range(20):
                        for sel in otp_selectors:
                            if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                                code_input_found = True
                                break
                        if code_input_found:
                            break
                        for sel in magic_link_selectors:
                            if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                                magic_link_screen_found = True
                                break
                        if magic_link_screen_found:
                            break
                        page.wait_for_timeout(1000)
                    if code_input_found or magic_link_screen_found:
                        break

            # Step 3: Handle Verification (OTP or Magic Link)
            if not otp_callback:
                raise RuntimeError("OTP callback is required for passwordless registration")

            if not code_input_found and not magic_link_screen_found:
                self._log_page_state(page, "verification screen not found")
                try:
                    page.screenshot(path="cerebras_otp_input_not_found.png", timeout=5000)
                except Exception:
                    pass
                raise RuntimeError("Neither OTP verification inputs nor Magic Link screen found. Screenshot saved.")

            if magic_link_screen_found:
                self.log("Magic Link screen detected. Requesting verification magic link...")
                verify_link = otp_callback()
                if not verify_link:
                    raise RuntimeError("Failed to retrieve magic link from mailbox")
                if not verify_link.startswith("http"):
                    raise RuntimeError(f"Expected verification URL, but got: {verify_link}")
                # Decode HTML entities (e.g. &amp; -> &) that may remain from the email body
                import html as _html
                verify_link = _html.unescape(verify_link)
                
                self.log(f"Navigating to Magic Link: {verify_link[:40]}...")
                page.goto(verify_link, wait_until="domcontentloaded", timeout=30000)
                self._human_sleep(3, 5)
            else:
                self.log("OTP verification screen detected. Requesting code...")
                otp_code = otp_callback()
                if not otp_code:
                    raise RuntimeError("Failed to retrieve OTP code from mailbox")

                self.log(f"Received OTP: {otp_code}. Entering code...")
                
                # Find the active selector and fill the code
                entered = False
                for sel in otp_selectors:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        if loc.count() == 6:
                            # 6 distinct input fields
                            for idx in range(6):
                                loc.nth(idx).fill(otp_code[idx])
                                self._human_sleep(0.1, 0.2)
                            entered = True
                        else:
                            loc.first.fill("")
                            self._type_human(page, sel, otp_code)
                            entered = True
                        break

                if not entered:
                    raise RuntimeError("Could not enter OTP code")

                self._human_sleep(3, 5)

            # Wait for dashboard page url. The magic-link URL
            # (/auth/magic-link?...#token=...) redirects to the dashboard, so we
            # must wait for that redirect to complete before navigating further.
            self.log("Waiting for dashboard/navigation...")
            for _ in range(20):
                curr_url = page.url
                is_auth_page = ("/sign-in" in curr_url or "/sign-up" in curr_url
                                or "/auth/" in curr_url)
                if ("/workspaces" in curr_url
                        or "api-keys" in curr_url
                        or ("cloud.cerebras.ai" in curr_url and not is_auth_page)):
                    self.log(f"Successfully authenticated. Current URL: {curr_url}")
                    break
                page.wait_for_timeout(1000)

            # Let any in-flight redirect finish before we navigate again.
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            self._human_sleep(1, 2)

            # Complete the new-account onboarding flow if present. New Cerebras
            # accounts land on /onboarding and must fill in profile info / accept
            # terms before the API keys page is usable.
            self._complete_onboarding(page)

            # Step 4: Navigate to API Keys page and create a key.
            # The platform URL includes the org id (e.g.
            # /platform/org_xxx/...). The bare /api-keys path 404s, so we go to
            # the dashboard and find the API keys link in the navigation.
            cur = page.url
            m = re.search(r"(https://cloud\.cerebras\.ai/platform/org_[^/]+)", cur)
            dashboard_url = m.group(1) if m else CEREBRAS_BASE

            # Navigate to the dashboard and click the "API keys" nav link. The
            # SPA needs to be on the dashboard to establish org context; a
            # direct goto /apikeys can 404 with "organization does not exist".
            self.log(f"Navigating to dashboard: {dashboard_url}")
            try:
                page.goto(dashboard_url, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            self._human_sleep(2, 4)

            # Wait for and click the API keys nav link.
            clicked = False
            for _scan in range(8):
                try:
                    for link in page.locator("a").all():
                        try:
                            href = (link.get_attribute("href") or "").lower()
                            text = (link.inner_text(timeout=1000) or "").strip()
                            if (("apikey" in href or "api-key" in href)
                                    and link.is_visible()):
                                self.log(f"Clicking API keys nav link ({href[:50]})...")
                                link.click()
                                clicked = True
                                break
                        except Exception:
                            pass
                except Exception:
                    pass
                if clicked:
                    break
                page.wait_for_timeout(1500)

            if not clicked:
                # Last resort: direct navigation (may work if org context is set).
                api_keys_url = f"{dashboard_url}/apikeys"
                self.log(f"Fallback: navigating directly to {api_keys_url}")
                try:
                    page.goto(api_keys_url, wait_until="domcontentloaded", timeout=20000)
                except Exception:
                    pass
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            self._human_sleep(2, 4)

            # Step 5: Extract the API key. Cerebras auto-creates a "Default Key"
            # on new accounts, so try to extract it first. If it is masked or
            # absent, generate a new key and extract that.
            def _extract_api_key():
                # Check input/textarea elements (keys are often in readonly inputs)
                for el in page.locator('input, textarea').all():
                    try:
                        val = el.input_value()
                        if val and re.match(r'^csk-', val):
                            return val
                    except Exception:
                        pass
                # Check visible text in code/span/td elements
                try:
                    for el in page.locator('code, span, td, div, p, pre').all():
                        try:
                            text = el.inner_text(timeout=500)
                            m = re.search(r'\bcsk-[A-Za-z0-9_-]{10,}\b', text)
                            if m:
                                return m.group(0)
                        except Exception:
                            pass
                except Exception:
                    pass
                # Fallback: regex in full page HTML
                try:
                    html = page.content()
                    m = re.search(r'\bcsk-[A-Za-z0-9_-]{10,}\b', html)
                    if m:
                        return m.group(0)
                except Exception:
                    pass
                return None

            self.log("Searching for an existing API key on the page...")
            api_key = _extract_api_key()

            if not api_key:
                # Generate a new key.
                self.log("No extractable key found; generating a new API key...")
                generate_selectors = [
                    'button:has-text("Generate API key")',
                    'button:has-text("Generate API Key")',
                    'button:has-text("Create API Key")',
                    'button:has-text("Create Key")',
                    'button:has-text("New Key")',
                    'button:has-text("Generate Key")',
                    'a:has-text("Create API Key")',
                ]
                gen_btn = None
                for sel in generate_selectors:
                    loc = page.locator(sel).first
                    if loc.count() > 0 and loc.is_visible():
                        gen_btn = loc
                        break

                if gen_btn:
                    self.log("Clicking Generate API key button...")
                    # Capture the API response that contains the full key (the
                    # table only shows a masked key after the modal closes).
                    captured_keys = []
                    def _on_resp(response):
                        try:
                            if response.ok:
                                body = response.text()
                                for m in re.finditer(r'\bcsk-[A-Za-z0-9_-]{10,}\b', body):
                                    captured_keys.append(m.group(0))
                        except Exception:
                            pass
                    page.on("response", _on_resp)

                    gen_btn.click()
                    self._human_sleep(1.5, 3)

                    # Handle possible key naming dialog/modal
                    try:
                        dialog_input = page.locator('input[placeholder*="Key" i], input[placeholder*="Name" i], input[type="text"]').first
                        if dialog_input.count() > 0 and dialog_input.is_visible():
                            self.log("Key naming dialog detected, entering name...")
                            dialog_input.fill("Auto-Key")
                            self._human_sleep(0.5, 1)
                            for s_sel in ['button:has-text("Create")', 'button:has-text("Generate")', 'button[type="submit"]']:
                                s_btn = page.locator(s_sel).first
                                if s_btn.count() > 0 and s_btn.is_visible():
                                    s_btn.click()
                                    break
                    except Exception as de:
                        self.log(f"Dialog handling skipped: {de}")

                    # Try to extract the key from the captured API response
                    # first, then from the page DOM.
                    for _ in range(20):
                        if captured_keys:
                            api_key = captured_keys[-1]
                            self.log("Captured API key from network response")
                            break
                        api_key = _extract_api_key()
                        if api_key:
                            break
                        page.wait_for_timeout(500)
                    try:
                        page.remove_listener("response", _on_resp)
                    except Exception:
                        pass
                else:
                    self.log("No generate-key button found either.")

            if not api_key:
                page.screenshot(path="cerebras_key_extraction_failed.png")
                self._log_page_state(page, "api key extraction failed")
                raise RuntimeError("API key was not found on the page. Screenshot saved.")

            self.log(f"Extracted API Key successfully: {api_key[:12]}...")
            return True, {
                "email": email,
                "password": password,
                "api_key": api_key,
            }

        except Exception as e:
            self.log(f"Registration error: {e}")
            return False, {"error": str(e)}
        finally:
            self._close_browser()
