"""
Proxy Pool Client — Reusable snippet for scraping, checking, and rotating free proxies.

Sources: monosans/proxy-list on GitHub (HTTP, SOCKS4, SOCKS5).

Usage:
    from proxy_pool_client import ProxyPool

    pool = ProxyPool()                         # persists to proxies.json by default
    pool = ProxyPool("my_proxies.json")        # or specify your own file

    # 1. Scrape fresh proxies from monosans
    added = pool.scrape()
    print(f"Added {added} new proxies")

    # 2. Check which ones are alive (concurrent, with geo-lookup)
    stats = pool.check_all(max_workers=50, timeout=8)
    print(f"Alive: {stats['ok']}, Dead: {stats['fail']}")

    # 3. Get the next working proxy (weighted round-robin)
    proxy_url = pool.get_next()                # e.g. "socks5h://1.2.3.4:1080"
    proxy_url = pool.get_next(region="US")     # filter by country

    # 4. Report success/failure so the pool learns
    pool.report_success(proxy_url)
    pool.report_fail(proxy_url)

    # 5. Build config dicts for requests / Playwright
    from proxy_pool_client import (
        build_requests_proxy,
        build_playwright_proxy,
        normalize_proxy_url,
        resolve_us_profile,
    )

    requests_proxies = build_requests_proxy(proxy_url)
    pw_proxy = build_playwright_proxy(proxy_url)
    us_profile = resolve_us_profile(proxy_url)

Requirements:
    pip install requests
    pip install PySocks          # only needed if you use SOCKS proxies with requests
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Optional
from urllib.parse import unquote, urlsplit, urlunsplit

import requests


# ===================================================================== #
#  Proxy URL utilities (standalone, no pool needed)                      #
# ===================================================================== #

def normalize_proxy_url(proxy_url: Optional[str]) -> Optional[str]:
    """Normalize ``socks5://`` → ``socks5h://`` to avoid local DNS leakage."""
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


def build_requests_proxy(proxy_url: Optional[str]) -> Optional[dict[str, str]]:
    """Return a ``proxies`` dict for ``requests.get(..., proxies=...)``."""
    if not proxy_url:
        return None
    url = normalize_proxy_url(proxy_url) or proxy_url
    return {"http": url, "https": url}


def build_playwright_proxy(proxy_url: Optional[str]) -> Optional[dict[str, str]]:
    """Return a ``proxy`` dict for ``playwright.chromium.launch(proxy=...)``."""
    if not proxy_url:
        return None
    value = str(proxy_url).strip()
    if not value:
        return None

    parts = urlsplit(value)
    if not parts.scheme or not parts.hostname or parts.port is None:
        server = value
        if server.startswith("socks5h://"):
            server = "socks5://" + server[len("socks5h://"):]
        return {"server": server, "bypass": "localhost,127.0.0.1"}

    scheme = (parts.scheme or "").lower()
    # Playwright can't handle authenticated SOCKS5
    if scheme in {"socks5", "socks5h"} and (parts.username or parts.password):
        return None
    if scheme == "socks5h":
        scheme = "socks5"

    config: dict[str, str] = {
        "server": f"{scheme}://{parts.hostname}:{parts.port}",
        "bypass": "localhost,127.0.0.1",
    }
    if parts.username:
        config["username"] = unquote(parts.username)
    if parts.password:
        config["password"] = unquote(parts.password)
    return config


def is_authenticated_socks5(proxy_url: Optional[str]) -> bool:
    """Check whether *proxy_url* is an authenticated SOCKS5 proxy."""
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
                return scheme in {"socks5", "socks5h"} and bool(username or password)
        except Exception:
            return False

    parts = urlsplit(value)
    scheme = (parts.scheme or "").lower()
    return scheme in {"socks5", "socks5h"} and bool(
        unquote(parts.username or "") or unquote(parts.password or "")
    )


# ===================================================================== #
#  US geo-profile resolution                                             #
# ===================================================================== #

US_TIMEZONE_COORDS = {
    "America/New_York":    {"latitude": 40.7128,  "longitude": -74.0060},
    "America/Chicago":     {"latitude": 41.8781,  "longitude": -87.6298},
    "America/Denver":      {"latitude": 39.7392,  "longitude": -104.9903},
    "America/Los_Angeles": {"latitude": 37.7749,  "longitude": -122.4194},
    "America/Phoenix":     {"latitude": 33.4484,  "longitude": -112.0740},
}


def resolve_us_profile(proxy_url: Optional[str]) -> dict[str, Any]:
    """Resolve a plausible US locale/timezone/lat/lon profile.

    If the proxy is actually in the US, the returned timezone and coordinates
    match the proxy's real location. Otherwise, a random US timezone is picked.
    """
    locale = "en-US"
    tz = None
    lat = None
    lon = None

    if proxy_url:
        try:
            import urllib.request

            handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
            opener = urllib.request.build_opener(handler)
            opener.addheaders = [
                ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            ]
            with opener.open("http://ip-api.com/json/", timeout=4) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "success" and data.get("countryCode", "").upper() == "US":
                    tz = data.get("timezone")
                    lat = data.get("lat")
                    lon = data.get("lon")
        except Exception:
            pass

    if not tz:
        tz = random.choice(list(US_TIMEZONE_COORDS.keys()))
    if lat is None or lon is None:
        coords = US_TIMEZONE_COORDS.get(tz, US_TIMEZONE_COORDS["America/New_York"])
        lat = coords["latitude"]
        lon = coords["longitude"]

    return {"locale": locale, "timezone": tz, "latitude": lat, "longitude": lon}


# ===================================================================== #
#  ProxyPool — scrape, check, rotate                                     #
# ===================================================================== #

# Each proxy record stored in the JSON file
_EMPTY_RECORD: dict[str, Any] = {
    "url": "",
    "region": "",
    "success_count": 0,
    "fail_count": 0,
    "is_active": True,
    "last_checked": None,
}

# monosans/proxy-list raw URLs
MONOSANS_SOURCES: dict[str, str] = {
    "http":   "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "socks4": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt",
    "socks5": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
}


class ProxyPool:
    """Self-contained proxy pool backed by a local JSON file.

    Scrapes free proxies from monosans/proxy-list, validates them
    concurrently via ip-api.com, and serves them in a weighted
    round-robin (preferring proxies with high success rates).
    """

    def __init__(
        self,
        store_path: str = "proxies.json",
        log_fn: Callable[[str], None] | None = None,
    ):
        self._path = store_path
        self._lock = threading.Lock()
        self._index = 0
        self._log_fn = log_fn or (lambda msg: print(f"[ProxyPool] {msg}"))
        self._proxies: list[dict[str, Any]] = self._load()

    # ------------------------------------------------------------------ #
    #  Persistence                                                        #
    # ------------------------------------------------------------------ #

    def _load(self) -> list[dict[str, Any]]:
        if not os.path.exists(self._path):
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save(self) -> None:
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._proxies, f, indent=2, ensure_ascii=False, default=str)
        os.replace(tmp, self._path)

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    @property
    def size(self) -> int:
        """Total number of proxies in the pool (active + inactive)."""
        with self._lock:
            return len(self._proxies)

    @property
    def active_count(self) -> int:
        """Number of proxies currently marked active."""
        with self._lock:
            return sum(1 for p in self._proxies if p.get("is_active", True))

    def list_all(self) -> list[dict[str, Any]]:
        """Return a copy of all proxy records."""
        with self._lock:
            return list(self._proxies)

    def get_next(self, region: str = "") -> Optional[str]:
        """Get the next proxy URL via weighted round-robin.

        Prefers proxies with higher success rates. Optionally filter by
        *region* (country code, e.g. ``"US"``).
        """
        with self._lock:
            candidates = [
                p for p in self._proxies
                if p.get("is_active", True)
                and (not region or p.get("region", "").upper() == region.upper())
            ]
            if not candidates:
                return None

            # Sort by success rate descending
            candidates.sort(
                key=lambda p: p["success_count"] / max(p["success_count"] + p["fail_count"], 1),
                reverse=True,
            )
            idx = self._index % len(candidates)
            self._index += 1
            url = candidates[idx]["url"]

        return normalize_proxy_url(url)

    def add(self, url: str, region: str = "") -> bool:
        """Add a single proxy. Returns False if it already exists."""
        url = url.strip()
        with self._lock:
            if any(p["url"] == url for p in self._proxies):
                return False
            record = dict(_EMPTY_RECORD)
            record["url"] = url
            record["region"] = region
            self._proxies.append(record)
            self._save()
        return True

    def add_bulk(self, urls: list[str], region: str = "") -> int:
        """Add many proxies at once. Returns count of newly added."""
        added = 0
        with self._lock:
            existing = {p["url"] for p in self._proxies}
            for raw in urls:
                url = raw.strip()
                if not url or url in existing:
                    continue
                record = dict(_EMPTY_RECORD)
                record["url"] = url
                record["region"] = region
                self._proxies.append(record)
                existing.add(url)
                added += 1
            if added:
                self._save()
        return added

    def remove(self, url: str) -> bool:
        """Remove a proxy by URL."""
        with self._lock:
            before = len(self._proxies)
            self._proxies = [p for p in self._proxies if p["url"] != url]
            if len(self._proxies) < before:
                self._save()
                return True
        return False

    def clear(self) -> int:
        """Remove all proxies. Returns how many were removed."""
        with self._lock:
            count = len(self._proxies)
            self._proxies.clear()
            self._save()
        return count

    def remove_inactive(self) -> int:
        """Remove all inactive or never-successful proxies."""
        with self._lock:
            before = len(self._proxies)
            self._proxies = [
                p for p in self._proxies
                if p.get("is_active", True) and not (
                    p.get("fail_count", 0) > 0 and p.get("success_count", 0) == 0
                )
            ]
            removed = before - len(self._proxies)
            if removed:
                self._save()
        return removed

    def report_success(self, url: str) -> None:
        """Record a successful use of *url*."""
        url_normalized = normalize_proxy_url(url) or url
        with self._lock:
            for p in self._proxies:
                if p["url"] == url or normalize_proxy_url(p["url"]) == url_normalized:
                    p["success_count"] += 1
                    p["last_checked"] = datetime.now(timezone.utc).isoformat()
                    break
            self._save()

    def report_fail(self, url: str) -> None:
        """Record a failed use of *url*. Auto-disables after 5 consecutive failures."""
        url_normalized = normalize_proxy_url(url) or url
        with self._lock:
            for p in self._proxies:
                if p["url"] == url or normalize_proxy_url(p["url"]) == url_normalized:
                    p["fail_count"] += 1
                    p["last_checked"] = datetime.now(timezone.utc).isoformat()
                    if p["fail_count"] >= 5 and p["success_count"] == 0:
                        p["is_active"] = False
                    break
            self._save()

    # ------------------------------------------------------------------ #
    #  Scrape from monosans                                               #
    # ------------------------------------------------------------------ #

    def scrape(self, sources: dict[str, str] | None = None) -> int:
        """Scrape proxy lists and add new ones. Returns count of newly added.

        *sources* maps protocol → raw-text URL. Defaults to monosans/proxy-list.
        """
        sources = sources or MONOSANS_SOURCES
        new_urls: list[str] = []

        with self._lock:
            existing = {p["url"] for p in self._proxies}

        for proto, list_url in sources.items():
            try:
                self._log(f"Scraping {proto} proxies from {list_url}")
                r = requests.get(list_url, timeout=15)
                if r.status_code != 200:
                    self._log(f"  HTTP {r.status_code}, skipping")
                    continue
                lines = r.text.strip().splitlines()
                count = 0
                for line in lines:
                    ip_port = line.strip()
                    if not ip_port:
                        continue
                    proxy_url = f"{proto}://{ip_port}"
                    if proxy_url not in existing:
                        new_urls.append(proxy_url)
                        existing.add(proxy_url)
                        count += 1
                self._log(f"  Found {count} new {proto} proxies")
            except Exception as e:
                self._log(f"  Error scraping {proto}: {e}")

        if new_urls:
            with self._lock:
                for url in new_urls:
                    record = dict(_EMPTY_RECORD)
                    record["url"] = url
                    self._proxies.append(record)
                self._save()

        self._log(f"Scrape complete: {len(new_urls)} new proxies added (total: {self.size})")
        return len(new_urls)

    # ------------------------------------------------------------------ #
    #  Concurrent checking                                                #
    # ------------------------------------------------------------------ #

    def check_all(
        self,
        max_workers: int = 30,
        timeout: int = 8,
        test_url: str = "http://ip-api.com/json/",
    ) -> dict[str, int]:
        """Check all proxies concurrently. Updates region and active status.

        Returns ``{"ok": N, "fail": N}``.
        """
        with self._lock:
            snapshot = list(self._proxies)

        if not snapshot:
            self._log("No proxies to check")
            return {"ok": 0, "fail": 0}

        self._log(f"Checking {len(snapshot)} proxies (workers={max_workers}, timeout={timeout}s)")
        results = {"ok": 0, "fail": 0}

        def check_one(record: dict[str, Any]) -> bool:
            url = record["url"]
            try:
                r = requests.get(
                    test_url,
                    proxies=build_requests_proxy(url),
                    timeout=timeout,
                )
                if r.status_code == 200:
                    data = r.json()
                    country = data.get("countryCode", "").upper()
                    with self._lock:
                        for p in self._proxies:
                            if p["url"] == url:
                                p["region"] = country
                                p["is_active"] = True
                                p["success_count"] += 1
                                p["last_checked"] = datetime.now(timezone.utc).isoformat()
                                break
                    return True
            except Exception:
                pass

            with self._lock:
                for p in self._proxies:
                    if p["url"] == url:
                        p["fail_count"] += 1
                        p["last_checked"] = datetime.now(timezone.utc).isoformat()
                        if p["fail_count"] >= 5 and p["success_count"] == 0:
                            p["is_active"] = False
                        break
            return False

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(check_one, rec): rec for rec in snapshot}
            for future in as_completed(futures):
                try:
                    if future.result():
                        results["ok"] += 1
                    else:
                        results["fail"] += 1
                except Exception:
                    results["fail"] += 1

        with self._lock:
            self._save()

        self._log(f"Check complete: {results['ok']} alive, {results['fail']} dead")
        return results

    # ------------------------------------------------------------------ #
    #  Logging                                                            #
    # ------------------------------------------------------------------ #

    def _log(self, message: str) -> None:
        if self._log_fn:
            self._log_fn(message)


# ===================================================================== #
#  CLI: run directly to scrape + check                                   #
# ===================================================================== #
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Proxy Pool — scrape & check free proxies")
    parser.add_argument("--file", default="proxies.json", help="JSON file for proxy storage")
    parser.add_argument("--scrape", action="store_true", help="Scrape fresh proxies from monosans")
    parser.add_argument("--check", action="store_true", help="Check all proxies for liveness")
    parser.add_argument("--workers", type=int, default=50, help="Concurrent workers for checking")
    parser.add_argument("--timeout", type=int, default=8, help="Timeout per proxy check (seconds)")
    parser.add_argument("--clean", action="store_true", help="Remove inactive/dead proxies")
    parser.add_argument("--stats", action="store_true", help="Print pool statistics")
    parser.add_argument("--get", action="store_true", help="Get next proxy")
    parser.add_argument("--region", default="", help="Filter by region (e.g. US)")
    args = parser.parse_args()

    pool = ProxyPool(args.file)

    if args.scrape:
        added = pool.scrape()
        print(f"\n✓ Added {added} new proxies")

    if args.check:
        stats = pool.check_all(max_workers=args.workers, timeout=args.timeout)
        print(f"\n✓ Alive: {stats['ok']}, Dead: {stats['fail']}")

    if args.clean:
        removed = pool.remove_inactive()
        print(f"\n✓ Removed {removed} dead proxies")

    if args.get:
        proxy = pool.get_next(region=args.region)
        if proxy:
            print(f"\nNext proxy: {proxy}")
        else:
            print("\nNo active proxies available")

    if args.stats or not any([args.scrape, args.check, args.clean, args.get]):
        all_proxies = pool.list_all()
        active = [p for p in all_proxies if p.get("is_active", True)]
        regions = {}
        for p in active:
            r = p.get("region") or "unknown"
            regions[r] = regions.get(r, 0) + 1

        print(f"\n{'='*50}")
        print(f"  Proxy Pool: {args.file}")
        print(f"  Total:  {len(all_proxies)}")
        print(f"  Active: {len(active)}")
        print(f"  Dead:   {len(all_proxies) - len(active)}")
        if regions:
            print(f"  Regions:")
            for region, count in sorted(regions.items(), key=lambda x: -x[1]):
                print(f"    {region}: {count}")
        print(f"{'='*50}")
