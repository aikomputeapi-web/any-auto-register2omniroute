"""Scheduled tasks - Account validity check,trial Expiration reminder"""
from datetime import datetime, timezone
from sqlmodel import Session, select
from .db import engine, AccountModel
from .registry import get, load_all
from .base_platform import Account, AccountStatus, RegisterConfig
import threading
import time


def _to_bool(value, default: bool = False) -> bool:
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _to_int(value, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(float(str(value or "").strip())))
    except Exception:
        return default


class Scheduler:
    def __init__(self):
        self._running = False
        self._thread: threading.Thread = None
        self._loop_interval_seconds = 60
        self._trial_check_interval_seconds = 3600
        self._last_trial_check_at = 0.0
        self._last_cpa_maintenance_at = 0.0
        self._last_kiro_refresh_at = 0.0
        self._last_chatgpt_refresh_at = 0.0
        self._last_proxy_scrape_at = 0.0
        self._last_proxy_check_at = 0.0
        self._proxy_maint_running = False
        self._proxy_maint_lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        
        now = time.time()
        # Set the last execution time to the current time to avoid triggering scheduled tasks as soon as the application starts (such as CPA automatic registration)
        self._last_trial_check_at = now
        self._last_cpa_maintenance_at = now
        self._last_kiro_refresh_at = now
        self._last_chatgpt_refresh_at = now
        self._last_proxy_scrape_at = now
        self._last_proxy_check_at = now

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("[Scheduler] Started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            now = time.time()
            if now - self._last_trial_check_at >= self._trial_check_interval_seconds:
                try:
                    self.check_trial_expiry()
                    self._last_trial_check_at = now
                except Exception as e:
                    print(f"[Scheduler] Trial Check for errors: {e}")

            # Auto-refresh Kiro tokens every 12 hours to keep them alive
            if now - self._last_kiro_refresh_at >= 43200:
                try:
                    print("[Scheduler] Auto-refreshing Kiro tokens...")
                    self.check_accounts_valid("kiro")
                    self._last_kiro_refresh_at = now
                except Exception as e:
                    print(f"[Scheduler] Kiro auto-refresh error: {e}")

            # Auto-refresh ChatGPT tokens every 12 hours to keep them alive
            if now - self._last_chatgpt_refresh_at >= 43200:
                try:
                    print("[Scheduler] Auto-refreshing ChatGPT tokens...")
                    self.check_accounts_valid("chatgpt")
                    self._last_chatgpt_refresh_at = now
                except Exception as e:
                    print(f"[Scheduler] ChatGPT auto-refresh error: {e}")

            cpa_interval = self._get_cpa_maintenance_interval_seconds()
            if cpa_interval and now - self._last_cpa_maintenance_at >= cpa_interval:
                try:
                    self.check_cpa_credentials()
                    self._last_cpa_maintenance_at = now
                except Exception as e:
                    print(f"[Scheduler] CPA Maintenance error: {e}")

            # Periodically scrape fresh proxies to refill the pool
            scrape_interval = self._get_proxy_scrape_interval_seconds()
            if scrape_interval and now - self._last_proxy_scrape_at >= scrape_interval:
                if self._try_start_proxy_maint():
                    self._last_proxy_scrape_at = now
                    self._spawn_proxy_maint("scrape", self.maintain_proxy_scrape)

            # Periodically re-check existing proxies to refresh is_active flags
            check_interval = self._get_proxy_check_interval_seconds()
            if check_interval and now - self._last_proxy_check_at >= check_interval:
                if self._try_start_proxy_maint():
                    self._last_proxy_check_at = now
                    self._spawn_proxy_maint("check", self.maintain_proxy_check)

            time.sleep(self._loop_interval_seconds)

    def _try_start_proxy_maint(self) -> bool:
        with self._proxy_maint_lock:
            if self._proxy_maint_running:
                return False
            self._proxy_maint_running = True
            return True

    def _spawn_proxy_maint(self, label: str, fn):
        def _runner():
            try:
                fn()
            except Exception as e:
                print(f"[Scheduler] Proxy {label} error: {e}")
            finally:
                with self._proxy_maint_lock:
                    self._proxy_maint_running = False

        t = threading.Thread(target=_runner, daemon=True)
        t.start()

    def _get_proxy_scrape_interval_seconds(self) -> int:
        from core.config_store import config_store

        if not _to_bool(config_store.get("proxy_auto_maintain_enabled", "1"), default=True):
            return 0
        minutes = _to_int(config_store.get("proxy_scrape_interval_minutes", "30"), default=30, minimum=1)
        return minutes * 60

    def _get_proxy_check_interval_seconds(self) -> int:
        from core.config_store import config_store

        if not _to_bool(config_store.get("proxy_auto_maintain_enabled", "1"), default=True):
            return 0
        minutes = _to_int(config_store.get("proxy_check_interval_minutes", "10"), default=10, minimum=1)
        return minutes * 60

    def maintain_proxy_scrape(self):
        print("[Scheduler] Proxy auto-scrape starting...")
        from core.proxy_pool import proxy_pool

        result = proxy_pool.scrape_proxies()
        print(
            f"[Scheduler] Proxy auto-scrape done: "
            f"added={result.get('added', 0)} updated={result.get('updated', 0)} "
            f"deleted={result.get('deleted', 0)} checked={result.get('checked', 0)}"
        )

    def maintain_proxy_check(self):
        print("[Scheduler] Proxy auto-check starting...")
        from core.proxy_pool import proxy_pool

        result = proxy_pool.check_all()
        print(
            f"[Scheduler] Proxy auto-check done: ok={result.get('ok', 0)} fail={result.get('fail', 0)}"
        )

    def _get_cpa_maintenance_interval_seconds(self) -> int:
        from services.cpa_manager import get_cpa_maintenance_interval_seconds

        return get_cpa_maintenance_interval_seconds()

    def check_trial_expiry(self):
        """examine trial Expired account, update status"""
        now = int(datetime.now(timezone.utc).timestamp())
        with Session(engine) as s:
            accounts = s.exec(
                select(AccountModel).where(AccountModel.status == "trial")
            ).all()
            updated = 0
            for acc in accounts:
                if acc.trial_end_time and acc.trial_end_time < now:
                    acc.status = AccountStatus.EXPIRED.value
                    acc.updated_at = datetime.now(timezone.utc)
                    s.add(acc)
                    updated += 1
            s.commit()
            if updated:
                print(f"[Scheduler] {updated} indivual trial Account has expired")

    def check_accounts_valid(self, platform: str = None, limit: int = 50):
        """Check account validity in batches"""
        load_all()
        with Session(engine) as s:
            q = select(AccountModel).where(
                AccountModel.status.in_(["registered", "trial", "subscribed"])
            )
            if platform:
                q = q.where(AccountModel.platform == platform)
            accounts = s.exec(q.limit(limit)).all()

        results = {"valid": 0, "invalid": 0, "error": 0}
        for acc in accounts:
            try:
                PlatformCls = get(acc.platform)
                plugin = PlatformCls(config=RegisterConfig())
                import json
                account_obj = Account(
                    platform=acc.platform,
                    email=acc.email,
                    password=acc.password,
                    user_id=acc.user_id,
                    region=acc.region,
                    token=acc.token,
                    extra=json.loads(acc.extra_json or "{}"),
                )
                valid = plugin.check_valid(account_obj)
                with Session(engine) as s:
                    a = s.get(AccountModel, acc.id)
                    if a:
                        if acc.platform != "chatgpt":
                            a.status = acc.status if valid else AccountStatus.INVALID.value
                        a.token = account_obj.token
                        a.extra_json = json.dumps(account_obj.extra, ensure_ascii=False)
                        a.updated_at = datetime.now(timezone.utc)
                        s.add(a)
                        s.commit()
                if valid:
                    results["valid"] += 1
                else:
                    results["invalid"] += 1
            except Exception:
                results["error"] += 1
        return results

    def check_cpa_credentials(self):
        """clean up CPA in error credentials, and automatically re-register when it falls below the threshold."""
        from services.cpa_manager import maintain_cpa_credentials

        return maintain_cpa_credentials()


scheduler = Scheduler()
