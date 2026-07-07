from __future__ import annotations

import json
from typing import Optional
from urllib.parse import unquote, urlsplit, urlunsplit


def _is_auth_socks_proxy(scheme: str, username: str, password: str) -> bool:
    normalized = (scheme or "").lower()
    return normalized in {"socks5", "socks5h"} and bool(username or password)


def is_authenticated_socks5_proxy(proxy_url: Optional[str]) -> bool:
    if not proxy_url:
        return False

    value = str(proxy_url).strip()
    if not value:
        return False

    if value.startswith("{"):
        try:
            data = json.loads(value)
            if isinstance(data, dict):
                server = str(data.get("server") or "").strip()
                if not server:
                    return False
                scheme = (urlsplit(server).scheme or "").lower()
                username = str(data.get("username") or "").strip()
                password = str(data.get("password") or "").strip()
                return _is_auth_socks_proxy(scheme, username, password)
        except Exception:
            return False

    parts = urlsplit(value)
    return _is_auth_socks_proxy(
        parts.scheme or "",
        unquote(parts.username or ""),
        unquote(parts.password or ""),
    )


def normalize_proxy_url(proxy_url: Optional[str]) -> Optional[str]:
    """Will socks5:// normalized to socks5h://, avoid local DNS leakage."""
    if proxy_url is None:
        return None

    value = str(proxy_url).strip()
    if not value:
        return None

    parts = urlsplit(value)
    if (parts.scheme or "").lower() == "socks5":
        parts = parts._replace(scheme="socks5h")
        return urlunsplit(parts)
    return value


def build_requests_proxy_config(proxy_url: Optional[str]) -> Optional[dict[str, str]]:
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def check_proxy(proxy_url: Optional[str], target: str = "https://chatgpt.com/", timeout: int = 8) -> bool:
    """Quickly verify proxy connectivity."""
    if not proxy_url:
        return False
    try:
        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        })
        opener = urllib.request.build_opener(proxy_handler)
        opener.addheaders = [("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
                             ("Accept", "text/html,application/xhtml+xml,*/*;q=0.8")]
        r = opener.open(target, timeout=timeout)
        code = r.status
        r.close()
        if code == 200:
            return True
        # Also treat redirects (3xx) as healthy — the proxy tunnel works
        return 200 <= code < 400
    except Exception:
        return False


def build_playwright_proxy_config(proxy_url: Optional[str]) -> Optional[dict[str, str]]:
    if not proxy_url:
        return None

    value = str(proxy_url).strip()
    if not value:
        return None
    parts = urlsplit(value)
    if not parts.scheme or not parts.hostname or parts.port is None:
        server = value
        if server.startswith("socks5h://"):
            server = "socks5://" + server[len("socks5h://") :]
        return {"server": server, "bypass": "localhost,127.0.0.1"}

    scheme = (parts.scheme or "").lower()
    if _is_auth_socks_proxy(scheme, parts.username or "", parts.password or ""):
        return None
    if scheme == "socks5h":
        scheme = "socks5"

    config = {
        "server": f"{scheme}://{parts.hostname}:{parts.port}",
        "bypass": "localhost,127.0.0.1"
    }
    if parts.username:
        config["username"] = unquote(parts.username)
    if parts.password:
        config["password"] = unquote(parts.password)
    return config


US_TIMEZONE_COORDS = {
    "America/New_York": {"latitude": 40.7128, "longitude": -74.0060},
    "America/Chicago": {"latitude": 41.8781, "longitude": -87.6298},
    "America/Denver": {"latitude": 39.7392, "longitude": -104.9903},
    "America/Los_Angeles": {"latitude": 37.7749, "longitude": -122.4194},
    "America/Phoenix": {"latitude": 33.4484, "longitude": -112.0740},
}


def resolve_us_profile(proxy_url: Optional[str]) -> dict[str, any]:
    """
    Resolves a US location profile (locale, timezone, lat, lon).
    If the proxy is located in the US, matches the proxy's timezone and coordinates.
    Otherwise, falls back to a random US timezone and its default coordinates.
    
    Returns a dict with 'locale' (always 'en-US'), 'timezone', 'latitude', and 'longitude'.
    """
    import random
    locale = "en-US"
    timezone = None
    latitude = None
    longitude = None
    
    if proxy_url:
        try:
            import urllib.request
            import json

            # Configure proxy handler. Using HTTPS here forces a CONNECT
            # tunnel, so a transparent proxy that answers 405 to CONNECT
            # (and would break every real HTTPS request) is detected here
            # instead of silently falling back to a random US timezone.
            proxy_handler = urllib.request.ProxyHandler({'http': proxy_url, 'https': proxy_url})
            opener = urllib.request.build_opener(proxy_handler)
            opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')]

            # ipwho.is is free over HTTPS and returns country_code / latitude /
            # longitude plus a timezone object whose "id" is the IANA name.
            # (ip-api.com's free endpoint is HTTP-only, so it can't validate
            # CONNECT-capable proxies.)
            with opener.open('https://ipwho.is/', timeout=8) as response:
                data = json.loads(response.read().decode('utf-8'))
                if data.get('success') is not False:
                    country_code = str(data.get('country_code', '') or '').upper()
                    tz = data.get('timezone')
                    # ipwho.is returns timezone as {"id": "America/New_York", ...}
                    tz_id = tz.get('id') if isinstance(tz, dict) else tz
                    # We only match the proxy timezone/location if it is in the US
                    if country_code == 'US' and tz_id:
                        timezone = tz_id
                        latitude = data.get('latitude')
                        longitude = data.get('longitude')
        except Exception:
            pass
            
    if not timezone:
        timezone = random.choice(list(US_TIMEZONE_COORDS.keys()))
        
    if latitude is None or longitude is None:
        coords = US_TIMEZONE_COORDS.get(timezone, US_TIMEZONE_COORDS["America/New_York"])
        latitude = coords["latitude"]
        longitude = coords["longitude"]
        
    return {
        "locale": locale,
        "timezone": timezone,
        "latitude": latitude,
        "longitude": longitude
    }

