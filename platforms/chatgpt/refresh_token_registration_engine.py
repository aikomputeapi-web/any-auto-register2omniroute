"""
ChatGPT Refresh Token Register engine.

The main link adopts two-stage advancement:
1. `ChatGPTClient.register_complete_flow()` Responsible for advancing the registration state machine to about_you
2. `OAuthClient.login_and_get_tokens()` Continue to complete the pre-session session about_you / workspace / token
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from core.task_runtime import TaskInterruption

from .chatgpt_client import ChatGPTClient
from .oauth import OAuthManager
from .oauth_client import OAuthClient
from .utils import (
    generate_random_birthday,
    generate_random_name,
    generate_random_password,
)

logger = logging.getLogger(__name__)


@dataclass
class RegistrationResult:
    """Registration results."""

    success: bool
    email: str = ""
    password: str = ""
    account_id: str = ""
    workspace_id: str = ""
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    session_token: str = ""
    error_message: str = ""
    logs: list | None = None
    metadata: dict | None = None
    source: str = "register"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "email": self.email,
            "password": self.password,
            "account_id": self.account_id,
            "workspace_id": self.workspace_id,
            "access_token": self.access_token[:20] + "..." if self.access_token else "",
            "refresh_token": self.refresh_token[:20] + "..." if self.refresh_token else "",
            "id_token": self.id_token[:20] + "..." if self.id_token else "",
            "session_token": self.session_token[:20] + "..." if self.session_token else "",
            "error_message": self.error_message,
            "logs": self.logs or [],
            "metadata": self.metadata or {},
            "source": self.source,
        }


@dataclass
class SignupFormResult:
    """Preserves the old structure and is compatible with external references."""

    success: bool
    page_type: str = ""
    is_existing_account: bool = False
    response_data: Dict[str, Any] | None = None
    error_message: str = ""


class EmailServiceAdapter:
    """will existing email_service adapted to ChatGPTClient / OAuthClient State machine."""

    def __init__(self, email_service, email: str, log_fn: Callable[[str], None]):
        self.email_service = email_service
        self.email = email
        self.log_fn = log_fn
        self._used_codes: set[str] = set()
        self._last_code: str = ""
        self._last_code_at: float = 0.0
        self._last_success_code: str = ""
        self._last_success_code_at: float = 0.0

    @property
    def last_code(self) -> str:
        return self._last_success_code or self._last_code

    def _remember_code(self, code: str, *, successful: bool = False) -> None:
        code = str(code or "").strip()
        if not code:
            return
        now = time.time()
        self._last_code = code
        self._last_code_at = now
        self._used_codes.add(code)
        if successful:
            self._last_success_code = code
            self._last_success_code_at = now

    def remember_successful_code(self, code: str) -> None:
        self._remember_code(code, successful=True)

    def get_recent_code(
        self,
        max_age_seconds: int = 180,
        *,
        prefer_successful: bool = True,
    ) -> str:
        now = time.time()
        if (
            prefer_successful
            and self._last_success_code
            and now - self._last_success_code_at <= max_age_seconds
        ):
            return self._last_success_code
        if self._last_code and now - self._last_code_at <= max_age_seconds:
            return self._last_code
        return ""

    def wait_for_verification_code(
        self,
        email: str,
        timeout: int = 90,
        otp_sent_at: float | None = None,
        exclude_codes=None,
    ):
        excluded = set(exclude_codes) if exclude_codes is not None else set(self._used_codes)
        self.log_fn(f"Waiting for email {email} verification code ({timeout}s)...")
        code = self.email_service.get_verification_code(
            email=email,
            timeout=timeout,
            otp_sent_at=otp_sent_at,
            exclude_codes=excluded,
        )
        if code:
            code = str(code).strip()
            self._remember_code(code, successful=False)
            self.log_fn(f"Successfully obtained verification code: {code}")
        return code


class RefreshTokenRegistrationEngine:
    """Refresh token Register engine."""

    def __init__(
        self,
        email_service,
        proxy_url: Optional[str] = None,
        callback_logger: Optional[Callable[[str], None]] = None,
        task_uuid: Optional[str] = None,
        browser_mode: str = "protocol",
        max_retries: int = 3,
        extra_config: Optional[dict] = None,
    ):
        self.email_service = email_service
        self.proxy_url = proxy_url
        self.callback_logger = callback_logger or (lambda msg: logger.info(msg))
        self.task_uuid = task_uuid
        self.browser_mode = str(browser_mode or "protocol").strip().lower() or "protocol"
        self.max_retries = max(1, int(max_retries or 1))
        self.extra_config = dict(extra_config or {})

        self.email: Optional[str] = None
        self.password: Optional[str] = None
        self.email_info: Optional[Dict[str, Any]] = None
        self.logs: list[str] = []

    def _log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        self.logs.append(log_message)

        if self.callback_logger:
            self.callback_logger(log_message)

        if level == "error":
            logger.error(log_message)
        elif level == "warning":
            logger.warning(log_message)
        else:
            logger.info(log_message)

    def _create_email(self) -> bool:
        try:
            self._log(f"Creating {self.email_service.service_type.value} Mail...")
            self.email_info = self.email_service.create_email()

            email_value = str(
                self.email
                or (self.email_info or {}).get("email")
                or ""
            ).strip()
            if not email_value:
                self._log(
                    f"Failed to create mailbox: {self.email_service.service_type.value} Returns an empty email address",
                    "error",
                )
                return False

            if self.email_info is None:
                self.email_info = {}
            self.email_info["email"] = email_value
            self.email = email_value
            self._log(f"Email created successfully: {self.email}")
            return True
        except Exception as e:
            self._log(f"Failed to create mailbox: {e}", "error")
            return False

    def _read_int_config(
        self,
        primary_key: str,
        *,
        fallback_keys: tuple[str, ...] = (),
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        keys = (primary_key, *tuple(fallback_keys or ()))
        for key in keys:
            if key not in self.extra_config:
                continue
            value = self.extra_config.get(key)
            try:
                parsed = int(value)
            except Exception:
                continue
            return max(minimum, min(parsed, maximum))
        return max(minimum, min(int(default), maximum))

    @staticmethod
    def _should_switch_to_login_after_register_failure(message: str) -> bool:
        text = str(message or "").lower()
        markers = (
            "user_already_exists",
            "account already exists",
            "please login instead",
            "add_phone",
            "add-phone",
            "authentication method you used during sign up",
            "authentication method",
        )
        return any(marker in text for marker in markers)

    def _build_chatgpt_client(self) -> ChatGPTClient:
        client = ChatGPTClient(
            proxy=self.proxy_url,
            verbose=False,
            browser_mode=self.browser_mode,
        )
        client._log = lambda msg: self._log(f"[Registration link] {msg}")
        return client

    def _build_oauth_client(self) -> OAuthClient:
        client = OAuthClient(
            self.extra_config,
            proxy=self.proxy_url,
            verbose=False,
            browser_mode=self.browser_mode,
        )
        client._log = lambda msg: self._log(f"[Login link] {msg}")
        return client

    def _reuse_register_browser_context(
        self,
        register_client: ChatGPTClient,
        oauth_client: OAuthClient,
    ) -> None:
        oauth_client.adopt_browser_context(
            register_client.session,
            device_id=getattr(register_client, "device_id", "") or "",
            user_agent=getattr(register_client, "ua", None),
            sec_ch_ua=getattr(register_client, "sec_ch_ua", None),
            accept_language=(
                getattr(register_client.session, "headers", {}).get("Accept-Language", "")
                if getattr(register_client, "session", None) is not None
                else ""
            ),
        )
        oauth_client.impersonate = str(
            getattr(register_client, "impersonate", "") or ""
        ).strip()
        self._log("Already connected to prequel session/cookie/fingerprint, continue processing OAuth Next steps")

    def _extract_account_info(self, tokens: dict[str, Any]) -> dict[str, Any]:
        id_token = str((tokens or {}).get("id_token") or "").strip()
        if not id_token:
            return {}
        manager = OAuthManager(proxy_url=self.proxy_url)
        return manager.extract_account_info(id_token)

    @staticmethod
    def _extract_workspace_id(oauth_client: OAuthClient) -> str:
        workspace_id = str(getattr(oauth_client, "last_workspace_id", "") or "").strip()
        if workspace_id:
            return workspace_id

        try:
            session_data = oauth_client._decode_oauth_session_cookie() or {}
        except Exception:
            session_data = {}

        workspaces = session_data.get("workspaces") or []
        if not workspaces:
            return ""
        return str((workspaces[0] or {}).get("id") or "").strip()

    @staticmethod
    def _extract_session_token(oauth_client: OAuthClient) -> str:
        getter = getattr(oauth_client, "_get_cookie_value", None)
        if not callable(getter):
            return ""
        return str(
            getter("__Secure-next-auth.session-token", "chatgpt.com")
            or getter("__Secure-authjs.session-token", "chatgpt.com")
            or ""
        ).strip()

    def _parallel_add_phone_retry(
        self,
        *,
        result,
        register_client,
        email_adapter,
        first_name: str,
        last_name: str,
        birthdate: str,
        register_otp_wait_seconds: int,
        parallel: int = 3,
    ):
        """add_phone After blocking, start multiple new channels in parallel OAuth session, the first one to succeed wins."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        winning_tokens = None
        winning_client = None

        def _one_attempt(idx):
            client = self._build_oauth_client()
            client.config.setdefault(
                "chatgpt_oauth_otp_wait_seconds", register_otp_wait_seconds
            )
            self._log(f"add_phone Parallel retry #{idx + 1}/{parallel} start up...")
            t = client.login_and_get_tokens(
                result.email,
                self.password,
                device_id="",
                user_agent=getattr(register_client, "ua", None),
                sec_ch_ua=getattr(register_client, "sec_ch_ua", None),
                impersonate=getattr(register_client, "impersonate", None),
                skymail_client=email_adapter,
                prefer_passwordless_login=True,
                allow_phone_verification=True,
                force_new_browser=True,
                force_chatgpt_entry=False,
                screen_hint="login",
                force_password_login=False,
                complete_about_you_if_needed=True,
                first_name=first_name,
                last_name=last_name,
                birthdate=birthdate,
                login_source=f"add_phone_parallel_{idx}",
            )
            return t, client

        with ThreadPoolExecutor(max_workers=parallel) as executor:
            futures = {executor.submit(_one_attempt, i): i for i in range(parallel)}
            for future in as_completed(futures):
                try:
                    t, client = future.result()
                    if t and not winning_tokens:
                        winning_tokens = t
                        winning_client = client
                        self._log(
                            f"add_phone Parallel retry #{futures[future] + 1} Success, cancel the rest..."
                        )
                        # Cancel something that hasn’t started yet futures
                        for f in futures:
                            if f is not future:
                                f.cancel()
                        break
                except Exception as exc:
                    self._log(f"add_phone Parallel retry exception: {exc}", "warning")

        return winning_tokens, winning_client

    def _populate_result_from_tokens(
        self,
        result: RegistrationResult,
        tokens: dict[str, Any],
        oauth_client: OAuthClient,
        registration_message: str,
        source: str,
        register_client: Any,
    ) -> None:
        account_info = self._extract_account_info(tokens)
        workspace_id = self._extract_workspace_id(oauth_client)
        session_token = self._extract_session_token(oauth_client)

        result.success = True
        result.email = self.email or ""
        result.password = self.password or ""
        result.access_token = str(tokens.get("access_token") or "").strip()
        result.refresh_token = str(tokens.get("refresh_token") or "").strip()
        result.id_token = str(tokens.get("id_token") or "").strip()
        result.account_id = str(
            tokens.get("account_id")
            or account_info.get("account_id")
            or ""
        ).strip()
        result.workspace_id = workspace_id
        result.session_token = session_token
        result.source = source
        result.metadata = {
            "email_service": self.email_service.service_type.value,
            "proxy_used": self.proxy_url,
            "registered_at": datetime.now().isoformat(),
            "registration_message": registration_message,
            "registration_flow": "chatgpt_client.register_complete_flow",
            "token_flow": "oauth_client.login_and_get_tokens",
            "token_login_mode": "passwordless",
            "browser_mode": self.browser_mode,
            "device_id": getattr(register_client, "device_id", ""),
            "impersonate": getattr(register_client, "impersonate", ""),
            "user_agent": getattr(register_client, "ua", ""),
            "workspace_id": workspace_id,
            "account_claims_email": account_info.get("email", ""),
        }

    def run(self) -> RegistrationResult:
        result = RegistrationResult(success=False, logs=self.logs)
        last_error = ""
        fixed_email = str(self.email or "").strip()
        register_otp_wait_seconds = self._read_int_config(
            "chatgpt_register_otp_wait_seconds",
            fallback_keys=("chatgpt_otp_wait_seconds",),
            default=600,
            minimum=30,
            maximum=3600,
        )
        register_otp_resend_wait_seconds = self._read_int_config(
            "chatgpt_register_otp_resend_wait_seconds",
            fallback_keys=("chatgpt_register_otp_wait_seconds", "chatgpt_otp_wait_seconds"),
            default=300,
            minimum=30,
            maximum=3600,
        )

        for attempt in range(self.max_retries):
            if attempt > 0:
                self._log(f"Registration attempt {attempt + 1}/{self.max_retries}...")
                if not fixed_email:
                    self.email = None
                    self.password = None
                    self.email_info = None

            try:
                registration_message = ""
                source = "register"

                self._log("=" * 60)
                self._log(f"ChatGPT RT New main link starts (Attempt {attempt + 1}/{self.max_retries})")
                self._log(f"request mode: {self.browser_mode}")
                self._log("implementation strategy: Register state machine + OAuth Continue process")
                self._log("=" * 60)

                if not fixed_email:
                    self.email = None

                self._log("1. Create mailbox...")
                if not self._create_email():
                    last_error = "Failed to create mailbox"
                    if attempt == self.max_retries - 1:
                        result.error_message = last_error
                        return result
                    continue

                result.email = self.email or ""
                self.password = self.password or generate_random_password(16)
                result.password = self.password

                first_name, last_name = generate_random_name()
                birthdate = generate_random_birthday()
                self._log(f"Mail: {result.email}")
                self._log(f"password: {self.password}")
                self._log(f"Registration information: {first_name} {last_name}, Birthday: {birthdate}")
                self._log("process strategy: The registration stage advances to about_you and then switch to OAuth The process continues with subsequent steps")
                self._log(
                    "Verification code waiting strategy: "
                    f"register_wait={register_otp_wait_seconds}s, "
                    f"register_resend_wait={register_otp_resend_wait_seconds}s, "
                    "oauth_wait=read OAuthClient configuration (default600s)"
                )

                email_adapter = EmailServiceAdapter(
                    self.email_service,
                    result.email,
                    self._log,
                )

                _REG_RETRY_MARKERS = ("Failed to access home page", "Pre-authorization blocked")
                registered = False
                registration_message = ""
                for _reg_attempt in range(3):
                    if _reg_attempt > 0:
                        self._log(
                            f"Register state machine retry {_reg_attempt}/2(reason: {registration_message})..."
                        )
                    register_client = self._build_chatgpt_client()
                    self._log("2. Execute the registration state machine (interrupt Mode: Not submitted during registration phase about_you)...")
                    registered, registration_message = register_client.register_complete_flow(
                        result.email,
                        self.password,
                        first_name,
                        last_name,
                        birthdate,
                        email_adapter,
                        stop_before_about_you_submission=True,
                        otp_wait_timeout=register_otp_wait_seconds,
                        otp_resend_wait_timeout=register_otp_resend_wait_seconds,
                    )
                    if registered:
                        break
                    if not any(m in registration_message for m in _REG_RETRY_MARKERS):
                        break

                if not registered:
                    if not self._should_switch_to_login_after_register_failure(
                        registration_message
                    ):
                        last_error = f"Failed to register state machine: {registration_message}"
                        if attempt == self.max_retries - 1:
                            result.error_message = last_error
                            return result
                        continue

                    self._log(
                        "The registration phase hits a final state that can continue to be processed, and is changed to OAuth Login process",
                        "warning",
                    )
                    self._log(f"Switch reason: {registration_message}")
                    source = "login"
                else:
                    if registration_message == "pending_about_you_submission":
                        self._log("The registration state machine has been advanced to about_you, in line with expectations. Next step to enter OAuth Conversation complement")
                    else:
                        self._log(
                            "The registration state machine returns successfully but does not stop at about_you."
                            "will continue to enter OAuth Session, advanced by the actual return of the state machine."
                        )

                oauth_client = self._build_oauth_client()
                oauth_client.config.setdefault(
                    "chatgpt_oauth_otp_wait_seconds",
                    register_otp_wait_seconds,
                )
                oauth_client.config.setdefault(
                    "chatgpt_oauth_otp_resend_wait_seconds",
                    register_otp_resend_wait_seconds,
                )

                use_continued_session = registered and (
                    registration_message == "pending_about_you_submission"
                )

                if use_continued_session:
                    self._reuse_register_browser_context(register_client, oauth_client)
                    self._log("3. Preface to take over session, keep walking OAuth passwordless process")
                    self._log("4. Following the preamble stage cookie / device_id / browser fingerprint")
                    self._log("5. Submit after successful login about_you, and continue workspace/token process")
                    # CRITICAL: Clear registration-phase used codes so OAuth login
                    # does not try the (now-expired) registration OTP.
                    if hasattr(email_adapter, "_used_codes"):
                        email_adapter._used_codes.clear()
                    tokens = oauth_client.login_and_get_tokens(
                        result.email,
                        self.password,
                        device_id=getattr(register_client, "device_id", "") or "",
                        user_agent=getattr(register_client, "ua", None),
                        sec_ch_ua=getattr(register_client, "sec_ch_ua", None),
                        impersonate=getattr(register_client, "impersonate", None),
                        skymail_client=email_adapter,
                        prefer_passwordless_login=True,
                        allow_phone_verification=True,
                        force_new_browser=False,
                        force_chatgpt_entry=False,
                        screen_hint="login",
                        force_password_login=False,
                        complete_about_you_if_needed=True,
                        first_name=first_name,
                        last_name=last_name,
                        birthdate=birthdate,
                        login_source="post_register_workspace_continue",
                    )
                else:
                    self._log("3. Newly opened OAuth session,according to screen_hint=login + passwordless OTP Log in...")
                    self._log("4. If hit about_you, then in OAuth Submit name within session+birthday, keep going workspace/token")
                    tokens = oauth_client.login_and_get_tokens(
                        result.email,
                        self.password,
                        device_id="",
                        user_agent=getattr(register_client, "ua", None),
                        sec_ch_ua=getattr(register_client, "sec_ch_ua", None),
                        impersonate=getattr(register_client, "impersonate", None),
                        skymail_client=email_adapter,
                        prefer_passwordless_login=True,
                        allow_phone_verification=True,
                        force_new_browser=True,
                        force_chatgpt_entry=False,
                        screen_hint="login",
                        force_password_login=False,
                        complete_about_you_if_needed=True,
                        first_name=first_name,
                        last_name=last_name,
                        birthdate=birthdate,
                        login_source=(
                            "existing_account_continue" if source == "login" else "post_register_workspace_continue"
                        ),
                    )

                if not tokens:
                    last_error = oauth_client.last_error or "OAuth Login state machine failed"
                    
                    # Handle authentication method mismatch - retry with fresh session
                    if "authentication method" in last_error.lower() and use_continued_session:
                        self._log(
                            "OAuth about_you submission failed due to authentication method mismatch",
                            "warning",
                        )
                        self._log(
                            "Retrying with fresh OAuth session (passwordless flow)...",
                            "warning",
                        )
                        # Create a new OAuth client with fresh session
                        oauth_client = self._build_oauth_client()
                        oauth_client.config.setdefault(
                            "chatgpt_oauth_otp_wait_seconds",
                            register_otp_wait_seconds,
                        )
                        oauth_client.config.setdefault(
                            "chatgpt_oauth_otp_resend_wait_seconds",
                            register_otp_resend_wait_seconds,
                        )
                        tokens = oauth_client.login_and_get_tokens(
                            result.email,
                            self.password,
                            device_id="",
                            user_agent=getattr(register_client, "ua", None),
                            sec_ch_ua=getattr(register_client, "sec_ch_ua", None),
                            impersonate=getattr(register_client, "impersonate", None),
                            skymail_client=email_adapter,
                            prefer_passwordless_login=True,
                            allow_phone_verification=True,
                            force_new_browser=True,
                            force_chatgpt_entry=False,
                            screen_hint="login",
                            force_password_login=False,
                            complete_about_you_if_needed=True,
                            first_name=first_name,
                            last_name=last_name,
                            birthdate=birthdate,
                            login_source="post_register_auth_mismatch_retry",
                        )
                        if tokens:
                            self._log("Authentication method mismatch resolved via fresh OAuth session")
                        else:
                            last_error = oauth_client.last_error or last_error
                    
                    # Handle add_phone blocking
                    if not tokens and "add_phone" in last_error:
                        self._log(
                            "OAuth add_phone Block, start parallel OAuth retry(3 Road concurrency)...",
                            "warning",
                        )
                        tokens, oauth_client = self._parallel_add_phone_retry(
                            result=result,
                            register_client=register_client,
                            email_adapter=email_adapter,
                            first_name=first_name,
                            last_name=last_name,
                            birthdate=birthdate,
                            register_otp_wait_seconds=register_otp_wait_seconds,
                        )
                        if not tokens:
                            last_error = (oauth_client.last_error if oauth_client else None) or last_error
                    
                    if not tokens:
                        if attempt == self.max_retries - 1:
                            result.error_message = last_error
                            return result
                        continue

                self._populate_result_from_tokens(
                    result=result,
                    tokens=tokens,
                    oauth_client=oauth_client,
                    registration_message=registration_message,
                    source=source,
                    register_client=register_client,
                )

                self._log("5. Main link completed")
                self._log(f"Account ID: {result.account_id}")
                self._log(f"Workspace ID: {result.workspace_id}")
                self._log("=" * 60)
                return result

            except TaskInterruption:
                raise
            except Exception as e:
                self._log(f"RT Registration main link exception: {e}", "error")
                last_error = str(e)
                if attempt == self.max_retries - 1:
                    result.error_message = last_error
                    return result
                continue

        return result

    def save_to_database(self, result: RegistrationResult) -> bool:
        """Keep the old interface and return the placeholder."""
        return bool(result and result.success)
