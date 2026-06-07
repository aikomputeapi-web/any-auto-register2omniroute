"""Kiro Platform plugin - based on AWS Builder ID register"""

from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class KiroPlatform(BasePlatform):
    name = "kiro"
    display_name = "Kiro (AWS Builder ID)"
    version = "1.0.0"

    def __init__(
        self,
        config: Optional[RegisterConfig] = None,
        mailbox: Optional[BaseMailbox] = None,
    ):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        from platforms.kiro.core import KiroRegister

        proxy = self.config.proxy
        laoudo_account_id = self.config.extra.get("laoudo_account_id", "")
        requested_headless = (self.config.executor_type or "protocol") != "headed"

        reg = KiroRegister(proxy=proxy, tag="KIRO", headless=requested_headless)
        log_fn = getattr(self, "_log_fn", print)
        reg.log_fn = log_fn

        otp_timeout = int(self.config.extra.get("otp_timeout", 120))

        if self.mailbox:
            mailbox = self.mailbox
            mail_acct = mailbox.get_email()
            if not mail_acct:
                raise RuntimeError("No available email account found")
            email = email or mail_acct.email
            log_fn(f"Mail: {mail_acct.email}")
            _before = mailbox.get_current_ids(mail_acct)

            def otp_cb():
                log_fn("Wait for verification code...")
                code = mailbox.wait_for_code(
                    mail_acct,
                    keyword="builder id",
                    timeout=otp_timeout,
                    before_ids=_before,
                    code_pattern=r"(?is)(?:verification\s+code|Verification code)[^0-9]{0,20}(\d{6})",
                )
                if code:
                    log_fn(f"Verification code: {code}")
                return code
        else:
            otp_cb = None

        ok, info = reg.register(
            email=email,
            pwd=password,
            name=self.config.extra.get("name", "Kiro User"),
            mail_token=laoudo_account_id or None,
            otp_timeout=otp_timeout,
            otp_callback=otp_cb,
        )

        if not ok:
            raise RuntimeError(f"Kiro Registration failed: {info.get('error')}")

        return Account(
            platform="kiro",
            email=info["email"],
            password=info["password"],
            status=AccountStatus.REGISTERED,
            extra={
                "name": info.get("name", ""),
                "accessToken": info.get("accessToken", ""),
                "sessionToken": info.get("sessionToken", ""),
                "clientId": info.get("clientId", ""),
                "clientSecret": info.get("clientSecret", ""),
                "clientIdHash": info.get("clientIdHash", ""),
                "refreshToken": info.get("refreshToken", ""),
                "webAccessToken": info.get("webAccessToken", ""),
                "region": info.get("region", "us-east-1"),
                "provider": "BuilderId",
                "authMethod": "IdC",
                "portalCookies": info.get("portalCookies", []),
            },
        )

    def check_valid(self, account: Account) -> bool:
        """pass refreshToken Check if the account is valid"""
        extra = account.extra or {}
        refresh_token = extra.get("refreshToken", "")
        if not refresh_token:
            return False
        try:
            from platforms.kiro.switch import refresh_kiro_token

            ok, result = refresh_kiro_token(
                refresh_token,
                extra.get("clientId", ""),
                extra.get("clientSecret", ""),
            )
            if ok:
                new_access = result["accessToken"]
                new_refresh = result.get("refreshToken", refresh_token)
                account.token = new_access
                extra["accessToken"] = new_access
                extra["refreshToken"] = new_refresh
                account.extra = extra
            return ok
        except Exception:
            return False

    def get_platform_actions(self) -> list:
        return [
            {"id": "switch_account", "label": "Switch to desktop app", "params": []},
            {"id": "refresh_token", "label": "refresh Token", "params": []},
            {"id": "upload_kiro_manager", "label": "import Kiro Manager", "params": []},
            {"id": "upload_to_omniroute", "label": "Upload to OmniRoute", "params": []},
            {"id": "fetch_latest_otp", "label": "Fetch latest OTP from mailbox", "params": []},
        ]

    def execute_action(self, action_id: str, account: Account, params: dict) -> dict:
        extra = account.extra or {}

        if action_id == "switch_account":
            from platforms.kiro.switch import (
                refresh_kiro_token,
                switch_kiro_account,
                restart_kiro_ide,
            )
            from platforms.kiro.core import KiroRegister
            from core.base_mailbox import create_mailbox, MailboxAccount

            access_token = extra.get("accessToken", "") or account.token
            refresh_token = extra.get("refreshToken", "")
            client_id = extra.get("clientId", "")
            client_secret = extra.get("clientSecret", "")

            # Kiro The desktop version requires a complete Builder ID SSO cache.
            # only accessToken/sessionToken The web account cannot be switched to the desktop application stably.
            if not access_token:
                return {
                    "ok": False,
                    "error": "The current account is missing accessToken, unable to switch to desktop app",
                }
            if not refresh_token or not client_id or not client_secret:
                if account.email and account.password:
                    reg = KiroRegister(proxy=self.config.proxy, tag="KIRO-SWITCH")
                    reg.log_fn = getattr(self, "_log_fn", print)
                    otp_callback = None
                    mailbox_extra = dict(self.config.extra or {})
                    for key in (
                        "mail_provider",
                        "luckmail_base_url",
                        "luckmail_project_code",
                        "luckmail_email_type",
                        "luckmail_domain",
                    ):
                        if extra.get(key) not in (None, ""):
                            mailbox_extra[key] = extra.get(key)

                    mail_provider = mailbox_extra.get("mail_provider", "")
                    if mail_provider:
                        try:
                            mailbox = create_mailbox(
                                provider=mail_provider,
                                extra=mailbox_extra,
                                proxy=self.config.proxy or "",
                            )
                            mail_account = MailboxAccount(
                                email=account.email,
                                account_id=extra.get("mailbox_token", ""),
                            )
                            before_ids = mailbox.get_current_ids(mail_account)

                            def _otp_cb():
                                reg.log("Desktop authorization waiting for email verification code ...")
                                try:
                                    code = mailbox.wait_for_code(
                                        mail_account,
                                        keyword="",
                                        timeout=45,
                                        before_ids=before_ids,
                                        code_pattern=r"(?is)(?:verification\s+code|Verification code)[^0-9]{0,20}(\d{6})",
                                    )
                                except Exception:
                                    reg.log(
                                        "Before waiting for the new verification code, fall back to reading the most recent authentication email. ..."
                                    )
                                    code = mailbox.wait_for_code(
                                        mail_account,
                                        keyword="",
                                        timeout=15,
                                        before_ids=set(),
                                        code_pattern=r"(?is)(?:verification\s+code|Verification code)[^0-9]{0,20}(\d{6})",
                                    )
                                if code:
                                    reg.log(f"Desktop authorization verification code: {code}")
                                return code

                            otp_callback = _otp_cb
                        except Exception:
                            otp_callback = None

                    ok, desktop_info = reg.fetch_desktop_tokens(
                        account.email,
                        account.password,
                        otp_callback=otp_callback,
                    )
                    if not ok:
                        return {
                            "ok": False,
                            "error": (
                                "The current account is missing refreshToken / clientId / clientSecret,"
                                f"And automatically catch the desktop version Token fail: {desktop_info.get('error', 'unknown error')}"
                            ),
                        }
                    access_token = desktop_info.get("accessToken", "") or access_token
                    refresh_token = desktop_info.get("refreshToken", "")
                    client_id = desktop_info.get("clientId", "")
                    client_secret = desktop_info.get("clientSecret", "")
                else:
                    return {
                        "ok": False,
                        "error": (
                            "The current account only has web page login status and lacks refreshToken / clientId / clientSecret,"
                            "and there is no email available/The password is used to automatically catch the desktop version Token."
                        ),
                    }

            if refresh_token and client_id and client_secret:
                ok, result = refresh_kiro_token(refresh_token, client_id, client_secret)
                if ok:
                    access_token = result["accessToken"]
                    refresh_token = result.get("refreshToken", refresh_token)

            ok, msg = switch_kiro_account(
                access_token=access_token,
                refresh_token=refresh_token,
                client_id=client_id,
                client_secret=client_secret,
            )
            if not ok:
                return {"ok": False, "error": msg}

            restart_ok, restart_msg = restart_kiro_ide()
            return {
                "ok": True,
                "data": {
                    "accessToken": access_token,
                    "refreshToken": refresh_token,
                    "clientId": client_id,
                    "clientSecret": client_secret,
                    "message": f"{msg}.{restart_msg}" if restart_ok else msg,
                },
            }

        elif action_id == "refresh_token":
            from platforms.kiro.switch import refresh_kiro_token

            refresh_token = extra.get("refreshToken", "")
            client_id = extra.get("clientId", "")
            client_secret = extra.get("clientSecret", "")

            ok, result = refresh_kiro_token(refresh_token, client_id, client_secret)
            if ok:
                new_access = result["accessToken"]
                new_refresh = result.get("refreshToken", refresh_token)
                return {
                    "ok": True,
                    "data": {
                        "access_token": new_access,
                        "accessToken": new_access,
                        "refreshToken": new_refresh,
                    },
                }
            return {"ok": False, "error": result.get("error", "Refresh failed")}

        elif action_id == "upload_kiro_manager":
            from platforms.kiro.account_manager_upload import upload_to_kiro_manager

            ok, msg = upload_to_kiro_manager(account)
            return {"ok": ok, "data": {"message": msg}}

        elif action_id == "upload_to_omniroute":
            from services.omniroute_sync import upload_to_omniroute, build_omniroute_payload
            from core.config_store import config_store

            api_url = str(config_store.get("omniroute_api_url", "") or "").strip()
            admin_password = str(config_store.get("omniroute_admin_password", "") or "").strip()
            if not api_url:
                return {"ok": False, "error": "OmniRoute API URL is not configured (omniroute_api_url)"}

            # Build and expose the payload for debugging
            try:
                payload = build_omniroute_payload(account)
            except Exception as e:
                payload = {}
                return {"ok": False, "error": f"Failed to build OmniRoute payload: {e}"}

            ok, msg = upload_to_omniroute(account, api_url=api_url, admin_password=admin_password)
            return {
                "ok": ok,
                "data": {
                    "message": msg,
                    "payload_preview": {
                        "provider": payload.get("provider", ""),
                        "authType": payload.get("authType", ""),
                        "email": payload.get("email", ""),
                        "has_accessToken": bool(payload.get("accessToken")),
                        "has_refreshToken": bool(payload.get("refreshToken")),
                        "providerSpecificData": payload.get("providerSpecificData", {}),
                    },
                },
                "error": "" if ok else msg,
            }

        elif action_id == "fetch_latest_otp":
            from core.config_store import config_store
            from core.base_mailbox import create_mailbox, MailboxAccount

            if not account.email:
                return {"ok": False, "error": "Account has no email address"}

            all_config = config_store.get_all()
            extra_cfg = dict(all_config)
            # Allow params to override provider settings
            extra_cfg.update({k: v for k, v in params.items() if v is not None and v != ""})

            mail_provider = str(extra_cfg.get("mail_provider", "") or "").strip()
            if not mail_provider:
                return {"ok": False, "error": "mail_provider is not configured — cannot fetch OTP from mailbox"}

            try:
                mailbox = create_mailbox(
                    provider=mail_provider,
                    extra=extra_cfg,
                    proxy=self.config.proxy or "",
                )
                mail_acct = MailboxAccount(
                    email=account.email,
                    account_id=account.email,
                )
                # Fetch the latest code without filtering out any IDs (before_ids=empty set)
                code = mailbox.wait_for_code(
                    mail_acct,
                    keyword="",
                    timeout=int(extra_cfg.get("otp_fetch_timeout", 30)),
                    before_ids=set(),
                    code_pattern=r"(?is)(?:verification\s+code|Verification code)[^0-9]{0,20}(\d{6})",
                )
                if code:
                    return {
                        "ok": True,
                        "data": {
                            "message": f"Latest OTP for {account.email}: {code}",
                            "otp": code,
                            "email": account.email,
                        },
                    }
                return {"ok": False, "error": "No OTP code found in the mailbox"}
            except TimeoutError:
                return {"ok": False, "error": f"Timeout: no OTP email found for {account.email} within the wait period"}
            except Exception as e:
                return {"ok": False, "error": f"Failed to fetch OTP from mailbox: {e}"}

        raise NotImplementedError(f"Unknown operation: {action_id}")
