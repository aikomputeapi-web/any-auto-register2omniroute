"""proxy pool - Read agents from the database, support polling and selection by region"""

from typing import Optional
from sqlmodel import Session, select
from .db import ProxyModel, engine
from .proxy_utils import build_requests_proxy_config, check_proxy
import asyncio
import time, threading, random
from datetime import datetime, timezone


def _run_coroutine_sync(coro):
    """Run a coroutine to completion, safe to call from a sync context.

    FastAPI handlers run inside an already-running asyncio event loop, so
    ``loop.run_until_complete()`` raises ``RuntimeError`` there. This helper
    detects that situation and falls back to running the coroutine in a
    dedicated background thread (via ``asyncio.run``), which is the correct
    way to bridge sync->async code without disturbing the running loop.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're inside a running loop (e.g. a FastAPI async handler).
        # Run the coroutine in a separate thread with its own loop.
        result_holder: dict = {}

        def _runner():
            result_holder["result"] = asyncio.run(coro)

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        worker.join()
        if "result" in result_holder:
            return result_holder["result"]
        raise RuntimeError("Coroutine execution failed in background thread")

    # No running loop — safe to use run_until_complete on a fresh loop.
    return asyncio.run(coro)


class ProxyPool:
    def __init__(self):
        self._index = 0
        self._lock = threading.Lock()
        self._validated_cache: dict[str, float] = {}

    def get_next(self, region: str = "") -> Optional[str]:
        """Weighted polling takes an available agent and rotates among agents with high success rate"""
        with Session(engine) as s:
            q = select(ProxyModel).where(ProxyModel.is_active == True)
            if region:
                q = q.where(ProxyModel.region == region)
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

    def get_validated(self, region: str = "", max_attempts: int = 5) -> Optional[str]:
        """Get a proxy and verify it's working before returning."""
        seen = set()
        for _ in range(max_attempts):
            url = self.get_next(region=region)
            if not url:
                return None
            if url in seen:
                continue
            seen.add(url)
            if url in self._validated_cache:
                age = time.time() - self._validated_cache[url]
                if age < 120:
                    return url
            if check_proxy(url, timeout=4):
                self._validated_cache[url] = time.time()
                return url
            self.report_fail(url)
        return None

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
                    if p.fail_count >= 2 and p.success_count == 0:
                        p.is_active = False
                    elif p.fail_count >= 3:
                        p.is_active = False
                    s.add(p)
                    s.commit()

    def check_all(self) -> dict:
        """Check all agent availability concurrently using async_proxy_checker"""
        from .async_proxy_checker import verify_proxies_async

        with self._lock:
            with Session(engine) as s:
                proxies = s.exec(select(ProxyModel)).all()
                urls = [p.url for p in proxies if p.url]

        results = {"ok": 0, "fail": 0, "deactivated": 0}
        if not urls:
            return results

        check_results = _run_coroutine_sync(verify_proxies_async(urls))

        with self._lock:
            with Session(engine) as s:
                for url, is_ok, region in check_results:
                    db_p = s.exec(select(ProxyModel).where(ProxyModel.url == url)).first()
                    if db_p:
                        if is_ok and region == "US":
                            db_p.is_active = True
                            db_p.region = region
                            db_p.success_count += 1
                            results["ok"] += 1
                            db_p.last_checked = datetime.now(timezone.utc)
                            s.add(db_p)
                        else:
                            # Don't permanently delete on a transient
                            # failure — a single network blip would wipe
                            # the proxy. Deactivate it instead so it can be
                            # re-checked/re-enabled later. Only proxies with
                            # repeated failures (no successes) get purged by
                            # delete_dead_proxies().
                            db_p.is_active = False
                            db_p.fail_count += 1
                            db_p.last_checked = datetime.now(timezone.utc)
                            results["fail"] += 1
                            results["deactivated"] += 1
                            s.add(db_p)
                s.commit()

        return results

    def delete_dead_proxies(self, max_consecutive_failures: int = 2) -> int:
        """Delete proxies that have failed multiple times with no successes.

        Phase 1 removes proxies whose accumulated stats already mark them as
        dead (fail_count >= threshold AND success_count == 0). Phase 2
        re-checks the *remaining* proxies and deactivates (not deletes) any
        that fail a live check, so a transient network blip doesn't wipe a
        previously-good proxy. Only proxies that accumulate enough failures
        with zero successes are eligible for actual deletion on the next run.
        """
        deleted = 0
        deactivated = 0
        with self._lock:
            with Session(engine) as s:
                dead = s.exec(
                    select(ProxyModel).where(
                        (ProxyModel.fail_count >= max_consecutive_failures)
                        & (ProxyModel.success_count == 0)
                    )
                ).all()
                for p in dead:
                    s.delete(p)
                    deleted += 1
                s.commit()

        # Re-check remaining proxies and deactivate failures rather than
        # deleting them outright — a single failed connectivity check should
        # not permanently remove a proxy that may just be temporarily down.
        from .proxy_utils import check_proxy
        with self._lock:
            with Session(engine) as s:
                proxies = s.exec(
                    select(ProxyModel).where(ProxyModel.is_active == True)
                ).all()
                for p in proxies:
                    if not check_proxy(p.url, timeout=4):
                        p.fail_count += 1
                        p.is_active = False
                        p.last_checked = datetime.now(timezone.utc)
                        deactivated += 1
                        s.add(p)
                s.commit()

        if deactivated:
            print(f"[Proxy] Deactivated {deactivated} proxy/proxies on re-check")
        return deleted

    def scrape_proxies(self) -> dict:
        """Scrape raw proxies, verify them concurrently, and ONLY add working USA ones to the database"""
        from .async_proxy_checker import scrape_all_raw_proxies, verify_proxies_async

        scraped_proxies = _run_coroutine_sync(scrape_all_raw_proxies())

        added = 0
        updated = 0
        deleted = 0
        if scraped_proxies:
            urls = list(scraped_proxies.keys())
            check_results = _run_coroutine_sync(
                verify_proxies_async(urls, max_concurrent=500)
            )

            with self._lock:
                with Session(engine) as s:
                    for url, is_ok, region in check_results:
                        existing = s.exec(select(ProxyModel).where(ProxyModel.url == url)).first()
                        if is_ok and region == "US":
                            if existing:
                                existing.is_active = True
                                existing.region = region
                                existing.success_count += 1
                                existing.last_checked = datetime.now(timezone.utc)
                                s.add(existing)
                                updated += 1
                            else:
                                s.add(ProxyModel(
                                    url=url,
                                    region=region,
                                    is_active=True,
                                    success_count=1,
                                    last_checked=datetime.now(timezone.utc)
                                ))
                                added += 1
                        else:
                            # Newly scraped proxies that don't pass are
                            # simply not added. For existing ones, deactivate
                            # rather than delete so a transient failure
                            # doesn't wipe a previously-good proxy.
                            if existing:
                                existing.is_active = False
                                existing.fail_count += 1
                                existing.last_checked = datetime.now(timezone.utc)
                                s.add(existing)
                                deleted += 1
                    s.commit()

        return {"added": added, "updated": updated, "deleted": deleted, "checked": len(scraped_proxies)}





proxy_pool = ProxyPool()

