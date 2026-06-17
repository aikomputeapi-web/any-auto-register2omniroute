"""proxy pool - Read agents from the database, support polling and selection by region"""

from typing import Optional
from sqlmodel import Session, select
from .db import ProxyModel, engine
from .proxy_utils import build_requests_proxy_config
import time, threading, random
from datetime import datetime, timezone


class ProxyPool:
    def __init__(self):
        self._index = 0
        self._lock = threading.Lock()

    def get_next(self, region: str = "") -> Optional[str]:
        """Weighted polling takes an available agent and rotates among agents with high success rate"""
        target_region = region if region else "US"
        with Session(engine) as s:
            q = select(ProxyModel).where(ProxyModel.is_active == True)
            if target_region:
                q = q.where(ProxyModel.region == target_region)
            proxies = s.exec(q).all()
            if not proxies:
                return None
            proxies.sort(
                key=lambda p: p.success_count / max(p.success_count + p.fail_count, 1),
                reverse=True,
            )
            with self._lock:
                idx = self._index % len(proxies)
                self._index += 1
            return proxies[idx].url

    def report_success(self, url: str) -> None:
        with self._lock:
            with Session(engine) as s:
                p = s.exec(select(ProxyModel).where(ProxyModel.url == url)).first()
                if p:
                    p.success_count += 1
                    p.last_checked = datetime.now(timezone.utc)
                    s.add(p)
                    s.commit()

    def report_fail(self, url: str) -> None:
        with self._lock:
            with Session(engine) as s:
                p = s.exec(select(ProxyModel).where(ProxyModel.url == url)).first()
                if p:
                    p.fail_count += 1
                    p.last_checked = datetime.now(timezone.utc)
                    # Continuous failure exceeds 5 automatically disabled
                    if p.fail_count > 0 and p.success_count == 0 and p.fail_count >= 5:
                        p.is_active = False
                    s.add(p)
                    s.commit()

    def check_all(self) -> dict:
        """Check all agent availability concurrently using ThreadPoolExecutor"""
        import requests
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with self._lock:
            with Session(engine) as s:
                proxies = s.exec(select(ProxyModel)).all()
        
        results = {"ok": 0, "fail": 0}
        if not proxies:
            return results

        def check_single(p: ProxyModel):
            try:
                # 1. Test basic connectivity & fetch IP info via ip-api
                r = requests.get(
                    "http://ip-api.com/json/",
                    proxies=build_requests_proxy_config(p.url),
                    timeout=8,
                )
                if r.status_code == 200:
                    data = r.json()
                    country_code = data.get("countryCode", "").upper()
                    # 2. Verify country is US
                    if country_code == "US":
                        # Set region to US and report success
                        with self._lock:
                            with Session(engine) as s:
                                db_p = s.exec(select(ProxyModel).where(ProxyModel.url == p.url)).first()
                                if db_p:
                                    db_p.region = "US"
                                    s.add(db_p)
                                    s.commit()
                        self.report_success(p.url)
                        return True
                    else:
                        # Non-US proxy: Disable it
                        with self._lock:
                            with Session(engine) as s:
                                db_p = s.exec(select(ProxyModel).where(ProxyModel.url == p.url)).first()
                                if db_p:
                                    db_p.is_active = False
                                    db_p.region = country_code
                                    s.add(db_p)
                                    s.commit()
            except Exception:
                pass
            self.report_fail(p.url)
            return False

        with ThreadPoolExecutor(max_workers=30) as executor:
            future_to_proxy = {executor.submit(check_single, p): p for p in proxies}
            for future in as_completed(future_to_proxy):
                is_ok = future.result()
                if is_ok:
                    results["ok"] += 1
                else:
                    results["fail"] += 1
        return results

    def scrape_proxies(self) -> dict:
        """Scrape proxies from monosans/proxy-list and add new ones to database"""
        import requests

        urls = {
            "http": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            "socks4": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt",
            "socks5": "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"
        }

        # Load all existing URLs
        with self._lock:
            with Session(engine) as s:
                existing_urls = set(s.exec(select(ProxyModel.url)).all())

        new_proxies = []
        for proto, list_url in urls.items():
            try:
                r = requests.get(list_url, timeout=15)
                if r.status_code == 200:
                    lines = r.text.strip().splitlines()
                    for line in lines:
                        ip_port = line.strip()
                        if not ip_port:
                            continue
                        proxy_url = f"{proto}://{ip_port}"
                        if proxy_url not in existing_urls:
                            new_proxies.append(proxy_url)
                            existing_urls.add(proxy_url)
            except Exception:
                pass

        if new_proxies:
            with self._lock:
                with Session(engine) as s:
                    # bulk commit in chunks of 500
                    for i in range(0, len(new_proxies), 500):
                        chunk = new_proxies[i : i + 500]
                        for url in chunk:
                            s.add(ProxyModel(url=url, region=""))
                        s.commit()

        return {"added": len(new_proxies)}


proxy_pool = ProxyPool()
