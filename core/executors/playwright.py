"""Playwright actuator - support headless/headed model"""

import logging
from typing import Any

from ..base_executor import BaseExecutor, Response
from ..browser_runtime import ensure_browser_display_available, resolve_browser_headless
from ..proxy_utils import build_playwright_proxy_config, resolve_us_profile


logger = logging.getLogger(__name__)


class PlaywrightExecutor(BaseExecutor):
    def __init__(self, proxy: str | None = None, headless: bool = True):
        super().__init__(proxy or "")
        self.headless = headless
        self._pw: Any | None = None
        self._browser: Any | None = None
        self._context: Any | None = None
        self._page: Any | None = None
        self._init()

    def _init(self) -> None:
        from playwright.sync_api import sync_playwright
        from core.user_agent_generator import UserAgentGenerator

        self._pw = sync_playwright().start()
        headless, reason = resolve_browser_headless(self.headless)
        ensure_browser_display_available(headless)
        logger.info(
            "PlaywrightExecutor browser mode: %s (%s)",
            "headless" if headless else "headed",
            reason,
        )

        # Generate random user agent and hardware specs
        ua_data = UserAgentGenerator.generate()
        viewport_width, viewport_height = UserAgentGenerator.get_random_viewport()
        hardware = UserAgentGenerator.get_random_hardware()
        
        logger.info(
            "Browser fingerprint: Chrome %s, Viewport %dx%d, CPU cores %d, RAM %dGB",
            ua_data["chrome_version"],
            viewport_width,
            viewport_height,
            hardware["hardware_concurrency"],
            hardware["device_memory"],
        )

        launch_opts: dict[str, Any] = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--disable-infobars",
                "--window-position=0,0",
                "--ignore-certificate-errors",
                "--ignore-certificate-errors-spki-list",
                "--disable-blink-features=AutomationControlled",
                "--remote-debugging-port=9222",
            ],
        }
        if self.proxy:
            proxy_cfg = build_playwright_proxy_config(self.proxy)
            if proxy_cfg:
                launch_opts["proxy"] = proxy_cfg
        self._browser = self._pw.chromium.launch(**launch_opts)
        
        # Resolve US profile and dynamic timezone offset
        import zoneinfo
        from datetime import datetime
        us_loc = resolve_us_profile(self.proxy)
        try:
            tz_offset = -int(datetime.now(zoneinfo.ZoneInfo(us_loc["timezone"])).utcoffset().total_seconds() / 60)
        except Exception:
            tz_offset = 480

        # Create context with USA location and stealth settings
        context_opts: dict[str, Any] = {
            "locale": us_loc["locale"],
            "timezone_id": us_loc["timezone"],
            "geolocation": {"latitude": us_loc["latitude"], "longitude": us_loc["longitude"]},
            "permissions": ["geolocation"],
            "viewport": {"width": viewport_width, "height": viewport_height},
            "screen": {"width": viewport_width, "height": viewport_height},
            "user_agent": ua_data["user_agent"],
            "device_scale_factor": 1,
            "is_mobile": False,
            "has_touch": False,
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-User": "?1",
                "Sec-Fetch-Dest": "document",
                "Upgrade-Insecure-Requests": "1",
                "sec-ch-ua": ua_data["sec_ch_ua"],
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": '"Windows"',
                "sec-ch-ua-platform-version": f'"{ua_data["sec_ch_ua_platform_version"]}"',
                "sec-ch-ua-full-version-list": ua_data["sec_ch_ua_full_version_list"],
            },
        }
        self._context = self._browser.new_context(**context_opts)
        
        # Store hardware specs for injection
        self._hardware_concurrency = hardware["hardware_concurrency"]
        self._device_memory = hardware["device_memory"]
        self._chrome_version = ua_data["chrome_version"]
        self._major_version = ua_data["major_version"]
        
        # Comprehensive stealth scripts to hide automation
        stealth_script = f"""
            // Overwrite the `navigator.webdriver` property
            Object.defineProperty(navigator, 'webdriver', {{
                get: () => undefined
            }});
            
            // Mock plugins with realistic data
            Object.defineProperty(navigator, 'plugins', {{
                get: () => {{
                    const plugins = [
                        {{
                            0: {{type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"}},
                            description: "Portable Document Format",
                            filename: "internal-pdf-viewer",
                            length: 1,
                            name: "Chrome PDF Plugin"
                        }},
                        {{
                            0: {{type: "application/pdf", suffixes: "pdf", description: "Portable Document Format"}},
                            description: "Portable Document Format",
                            filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                            length: 1,
                            name: "Chrome PDF Viewer"
                        }},
                        {{
                            0: {{type: "application/x-nacl", suffixes: "", description: "Native Client Executable"}},
                            1: {{type: "application/x-pnacl", suffixes: "", description: "Portable Native Client Executable"}},
                            description: "Native Client Executable",
                            filename: "internal-nacl-plugin",
                            length: 2,
                            name: "Native Client"
                        }}
                    ];
                    return plugins;
                }}
            }});
            
            // Mock mimeTypes
            Object.defineProperty(navigator, 'mimeTypes', {{
                get: () => {{
                    const mimeTypes = [
                        {{type: "application/pdf", suffixes: "pdf", description: "Portable Document Format"}},
                        {{type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"}},
                        {{type: "application/x-nacl", suffixes: "", description: "Native Client Executable"}},
                        {{type: "application/x-pnacl", suffixes: "", description: "Portable Native Client Executable"}}
                    ];
                    return mimeTypes;
                }}
            }});
            
            // Overwrite the `languages` property
            Object.defineProperty(navigator, 'languages', {{
                get: () => ['en-US', 'en']
            }});
            
            // Mock platform
            Object.defineProperty(navigator, 'platform', {{
                get: () => 'Win32'
            }});
            
            // Mock hardwareConcurrency (CPU cores) - randomized
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {self._hardware_concurrency}
            }});
            
            // Mock deviceMemory - randomized
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => {self._device_memory}
            }});
            
            // Overwrite chrome property with realistic data
            window.chrome = {{
                app: {{}},
                runtime: {{}},
                loadTimes: function() {{}},
                csi: function() {{}},
            }};
            
            // Mock Notification permission
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({{ state: Notification.permission }}) :
                    originalQuery(parameters)
            );
            
            // Hide Playwright-specific properties
            delete window.__playwright;
            delete window.__pw_manual;
            delete window.__PW_inspect;
            
            // Mock battery API
            if (!navigator.getBattery) {{
                navigator.getBattery = () => Promise.resolve({{
                    charging: true,
                    chargingTime: 0,
                    dischargingTime: Infinity,
                    level: 1,
                    addEventListener: () => {{}},
                    removeEventListener: () => {{}},
                    dispatchEvent: () => true
                }});
            }}
            
            // Mock connection API
            Object.defineProperty(navigator, 'connection', {{
                get: () => ({{
                    effectiveType: '4g',
                    rtt: 50,
                    downlink: 10,
                    saveData: false,
                    addEventListener: () => {{}},
                    removeEventListener: () => {{}},
                    dispatchEvent: () => true
                }})
            }});
            
            // Override toString methods to hide proxy behavior
            const originalToString = Function.prototype.toString;
            Function.prototype.toString = function() {{
                if (this === navigator.permissions.query) {{
                    return 'function query() {{ [native code] }}';
                }}
                return originalToString.call(this);
            }};
            
            // Mock WebGL vendor and renderer
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) {{
                    return 'Intel Inc.';
                }}
                if (parameter === 37446) {{
                    return 'Intel Iris OpenGL Engine';
                }}
                return getParameter.call(this, parameter);
            }};
            
            // Mock canvas fingerprinting
            const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function() {{
                const context = this.getContext('2d');
                if (context) {{
                    const imageData = context.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {{
                        imageData.data[i] = imageData.data[i] ^ 1;
                    }}
                    context.putImageData(imageData, 0, 0);
                }}
                return originalToDataURL.apply(this, arguments);
            }};
            
            // Mock AudioContext fingerprinting
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            if (AudioContext) {{
                const originalCreateOscillator = AudioContext.prototype.createOscillator;
                AudioContext.prototype.createOscillator = function() {{
                    const oscillator = originalCreateOscillator.call(this);
                    const originalStart = oscillator.start;
                    oscillator.start = function() {{
                        return originalStart.apply(this, arguments);
                    }};
                    return oscillator;
                }};
            }}
            
            // Mock screen properties with slight randomization
            Object.defineProperties(screen, {{
                availWidth: {{ get: () => window.innerWidth }},
                availHeight: {{ get: () => window.innerHeight }},
                colorDepth: {{ get: () => 24 }},
                pixelDepth: {{ get: () => 24 }}
            }});
            
            // Mock Date.prototype.getTimezoneOffset
            const originalGetTimezoneOffset = Date.prototype.getTimezoneOffset;
            Date.prototype.getTimezoneOffset = function() {{
                return {tz_offset};
            }};
            
            // Add realistic mouse movement tracking
            let mouseMovements = 0;
            document.addEventListener('mousemove', () => {{
                mouseMovements++;
            }}, true);
            
            // Mock Intl.DateTimeFormat for timezone consistency
            const OriginalDateTimeFormat = Intl.DateTimeFormat;
            Intl.DateTimeFormat = function(...args) {{
                if (!args[1] || !args[1].timeZone) {{
                    args[1] = args[1] || {{}};
                    args[1].timeZone = '{us_loc["timezone"]}';
                }}
                return new OriginalDateTimeFormat(...args);
            }};
            
            // Mock userAgentData (Client Hints API)
            Object.defineProperty(navigator, 'userAgentData', {{
                get: () => ({{
                    brands: [
                        {{ brand: 'Google Chrome', version: '{self._major_version}' }},
                        {{ brand: 'Chromium', version: '{self._major_version}' }},
                        {{ brand: 'Not_A Brand', version: '24' }}
                    ],
                    mobile: false,
                    platform: 'Windows',
                    getHighEntropyValues: async (hints) => ({{
                        brands: [
                            {{ brand: 'Google Chrome', version: '{self._major_version}' }},
                            {{ brand: 'Chromium', version: '{self._major_version}' }},
                            {{ brand: 'Not_A Brand', version: '24' }}
                        ],
                        mobile: false,
                        platform: 'Windows',
                        platformVersion: '{ua_data["sec_ch_ua_platform_version"]}',
                        architecture: 'x86',
                        bitness: '64',
                        model: '',
                        uaFullVersion: '{self._chrome_version}',
                        fullVersionList: [
                            {{ brand: 'Google Chrome', version: '{self._chrome_version}' }},
                            {{ brand: 'Chromium', version: '{self._chrome_version}' }},
                            {{ brand: 'Not_A Brand', version: '24.0.0.0' }}
                        ]
                    }})
                }})
            }});
        """
        
        self._context.add_init_script(stealth_script)
        self._page = self._context.new_page()

    def _require_page(self) -> Any:
        if self._page is None:
            raise RuntimeError("Playwright page not initialized")
        return self._page

    def _require_context(self) -> Any:
        if self._context is None:
            raise RuntimeError("Playwright context not initialized")
        return self._context

    @property
    def page(self) -> Any:
        """Compatible platform plug-in for direct access executor.page usage."""
        return self._require_page()

    @property
    def context(self) -> Any:
        """Compatible platform plug-in for direct access executor.context usage."""
        return self._require_context()

    def get(self, url, *, headers=None, params=None) -> Response:
        import urllib.parse

        page = self._require_page()
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        if headers:
            page.set_extra_http_headers(headers)
        resp = page.goto(url)
        if resp is None:
            raise RuntimeError(f"Playwright Navigation failed: {url}")
        return Response(
            status_code=resp.status,
            text=page.content(),
            headers=dict(resp.headers),
            cookies=self.get_cookies(),
        )

    def post(self, url, *, headers=None, params=None, data=None, json=None) -> Response:
        import json as _json
        import urllib.parse

        page = self._require_page()
        if params:
            url = url + "?" + urllib.parse.urlencode(params)
        post_data = None
        content_type = "application/x-www-form-urlencoded"
        if json is not None:
            post_data = _json.dumps(json)
            content_type = "application/json"
        elif data:
            post_data = urllib.parse.urlencode(data)
        h = {"Content-Type": content_type}
        if headers:
            h.update(headers)
        resp = page.request.post(url, headers=h, data=post_data)
        return Response(
            status_code=resp.status,
            text=resp.text(),
            headers=dict(resp.headers),
            cookies=self.get_cookies(),
        )

    def get_cookies(self) -> dict:
        context = self._require_context()
        return {c["name"]: c["value"] for c in context.cookies()}

    def set_cookies(self, cookies: dict, domain: str = ".example.com") -> None:
        context = self._require_context()
        page = self._require_page()
        page_url = page.url
        if page_url and page_url.startswith("http"):
            context.add_cookies(
                [{"name": k, "value": v, "url": page_url} for k, v in cookies.items()]
            )
        else:
            context.add_cookies(
                [
                    {"name": k, "value": v, "domain": domain, "path": "/"}
                    for k, v in cookies.items()
                ]
            )

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
