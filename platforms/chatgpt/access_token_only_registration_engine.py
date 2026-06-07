"""
Registration process engine V2
based on curl_cffi Registration state machine, directly reuse the same session extraction after successful registration ChatGPT Session.
"""

import time
import logging
from datetime import datetime
from typing import Optional, Callable

from core.task_runtime import TaskInterruption
from platforms.chatgpt.refresh_token_registration_engine import RegistrationResult

from .chatgpt_client import ChatGPTClient
from .utils import generate_random_name, generate_random_birthday

logger = logging.getLogger(__name__)

class EmailServiceAdapter:
    """\u5c06 V1 \u7684 email_service \u9002\u914d\u6210 V2 \u6240\u9700\u7684\u63a5\u7801\u63a5\u53e3\u3002"""
    def __init__(self, email_service, email, log_fn):
        self.es = email_service
        self.email = email
        self.log_fn = log_fn
        self._used_codes = set()

    def wait_for_verification_code(self, email, timeout=60, otp_sent_at=None, exclude_codes=None):
        msg = f"\u6b63\u5728\u7b49\u5f85\u90ae\u7bb1 {email} \u7684\u9a8c\u8bc1\u7801 ({timeout}s)..."
        self.log_fn(msg)
        code = self.es.get_verification_code(
            timeout=timeout,
            otp_sent_at=otp_sent_at,
            exclude_codes=exclude_codes if exclude_codes is not None else self._used_codes,
        )
        if code:
            self._used_codes.add(code)
            self.log_fn(f"\u6210\u529f\u83b7\u53d6\u9a8c\u8bc1\u7801: {code}")
        return code

class AccessTokenOnlyRegistrationEngine:
    def __init__(
        self,
        email_service,
        proxy_url: Optional[str] = None,
        browser_mode: str = "protocol",
        callback_logger: Optional[Callable[[str], None]] = None,
        task_uuid: Optional[str] = None,
        max_retries: int = 3,
        extra_config: Optional[dict] = None,
    ):
        self.email_service = email_service
        self.proxy_url = proxy_url
        self.browser_mode = browser_mode or "protocol"
        self.callback_logger = callback_logger
        self.task_uuid = task_uuid
        self.max_retries = max(1, int(max_retries or 1))
        self.extra_config = dict(extra_config or {})
        
        self.email = None
        self.password = None
        self.logs = []
        
    def _log(self, message: str, level: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        self.logs.append(log_message)
        if self.callback_logger:
            self.callback_logger(log_message)
        if level == "error":
            logger.error(log_message)
        else:
            logger.info(log_message)

    def _should_retry(self, message: str) -> bool:
        text = str(message or "").lower()
        retriable_markers = [
            "tls",
            "ssl",
            "curl: (35)",
            "Pre-authorization blocked",
            "authorize",
            "registration_disallowed",
            "http 400",
            "Failed to create account",
            "Not obtained authorization code",
            "consent",
            "workspace",
            "organization",
            "otp",
            "Verification code",
            "session",
            "accessToken",
            "next-auth",
        ]
        return any(marker.lower() in text for marker in retriable_markers)

    def run(self) -> RegistrationResult:
        result = RegistrationResult(success=False, logs=self.logs)
        try:
            last_error = ""
            for attempt in range(self.max_retries):
                try:
                    if attempt == 0:
                        self._log("=" * 60)
                        self._log("Start the registration process V2 (Session Reuse direct access AccessToken)")
                        self._log(f"request mode: {self.browser_mode}")
                        self._log("=" * 60)
                    else:
                        self._log(f"Retry the entire process {attempt + 1}/{self.max_retries} ...")
                        time.sleep(1)

                    # 1. Create mailbox
                    email_data = self.email_service.create_email()
                    email_addr = self.email or (email_data.get('email') if email_data else None)
                    if not email_addr:
                        result.error_message = "Failed to create mailbox"
                        return result

                    result.email = email_addr

                    pwd = self.password or "AAb1234567890!"
                    result.password = pwd

                    # Random name, birthday
                    first_name, last_name = generate_random_name()
                    birthdate = generate_random_birthday()

                    self._log(f"Mail: {email_addr}, password: {pwd}")
                    self._log(f"Registration information: {first_name} {last_name}, Birthday: {birthdate}")

                    # Use wrappers to provide coding services for underlying clients
                    skymail_adapter = EmailServiceAdapter(self.email_service, email_addr, self._log)

                    # 2. initialization V2 client
                    chatgpt_client = ChatGPTClient(
                        proxy=self.proxy_url,
                        verbose=False,
                        browser_mode=self.browser_mode,
                    )
                    chatgpt_client._log = self._log

                    self._log("step 1/2: Execute registration state machine...")

                    success, msg = chatgpt_client.register_complete_flow(
                        email_addr, pwd, first_name, last_name, birthdate, skymail_adapter
                    )

                    if not success:
                        last_error = f"Registration flow failed: {msg}"
                        if attempt < self.max_retries - 1 and self._should_retry(msg):
                            self._log(f"The registration process failed, prepare to retry the entire process.: {msg}")
                            continue
                        result.error_message = last_error
                        return result

                    self._log("step 2/2: Reuse the registration session and obtain it directly ChatGPT Session / AccessToken...")
                    session_ok, session_result = chatgpt_client.reuse_session_and_get_tokens()

                    if session_ok:
                        self._log("Token Extraction completed!")
                        result.success = True
                        result.access_token = session_result.get("access_token", "")
                        result.session_token = session_result.get("session_token", "")
                        result.account_id = (
                            session_result.get("account_id")
                            or session_result.get("user_id")
                            or ("v2_acct_" + chatgpt_client.device_id[:8])
                        )
                        result.workspace_id = session_result.get("workspace_id", "")
                        result.metadata = {
                            "auth_provider": session_result.get("auth_provider", ""),
                            "expires": session_result.get("expires", ""),
                            "user_id": session_result.get("user_id", ""),
                            "user": session_result.get("user") or {},
                            "account": session_result.get("account") or {},
                        }

                        if result.workspace_id:
                            self._log(f"Session Workspace ID: {result.workspace_id}")

                        self._log("=" * 60)
                        self._log("Registration process ended successfully!")
                        self._log("=" * 60)
                        return result

                    last_error = f"Registration is successful, but the reuse session is obtained AccessToken fail: {session_result}"
                    if attempt < self.max_retries - 1:
                        self._log(f"{last_error}, prepare to retry the entire process")
                        continue
                    result.error_message = last_error
                    return result
                except TaskInterruption:
                    raise
                except Exception as attempt_error:
                    last_error = str(attempt_error)
                    if attempt < self.max_retries - 1 and self._should_retry(last_error):
                        self._log(f"An exception occurred this round. Prepare to retry the whole process.: {last_error}")
                        continue
                    raise

            result.error_message = last_error or "Registration failed"
            return result
                
        except TaskInterruption:
            raise
        except Exception as e:
            self._log(f"none RT Execution exception during the entire registration process: {e}", "error")
            import traceback
            traceback.print_exc()
            result.error_message = str(e)
            return result


# Compatible with old naming, gradually migrate to more meaningful class names.
RegistrationEngineV2 = AccessTokenOnlyRegistrationEngine
