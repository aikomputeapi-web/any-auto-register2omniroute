"""Scheduled tasks - Account validity check,trial Expiration reminder"""
from datetime import datetime, timezone
from sqlmodel import Session, select
from .db import engine, AccountModel
from .registry import get, load_all
from .base_platform import Account, AccountStatus, RegisterConfig
import threading
import time


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

            time.sleep(self._loop_interval_seconds)

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
