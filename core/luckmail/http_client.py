"""
core HTTP client (based on curl_cffi)
Support synchronization/Asynchronous dual mode, intelligent identification and automatic switching of calling context

support TLS Fingerprint simulation to avoid being identified as a robot by the target website.
"""

import asyncio
import hashlib
import hmac
import json
import secrets
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from curl_cffi import requests as curl_requests

from .exceptions import APIError, AuthError, NetworkError
from ..proxy_utils import normalize_proxy_url, build_requests_proxy_config


def _is_async_context() -> bool:
    """Detect whether you are currently in an asynchronous context (the event loop is running)"""
    try:
        loop = asyncio.get_event_loop()
        return loop.is_running()
    except RuntimeError:
        return False


def _generate_hmac_signature(api_secret: str, api_key: str, timestamp: str, nonce: str) -> str:
    """generate HMAC-SHA256 sign

    Signature content:api_key + timestamp + nonce,use api_secret as key
    """
    message = f"{api_key}{timestamp}{nonce}"
    signature = hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature


class _SyncRunner:
    """Tool class for running asynchronous functions synchronously"""

    _lock = threading.Lock()
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _thread: Optional[threading.Thread] = None

    @classmethod
    def _ensure_loop(cls):
        """Make sure the background event loop is running"""
        with cls._lock:
            if cls._loop is None or not cls._loop.is_running():
                cls._loop = asyncio.new_event_loop()
                cls._thread = threading.Thread(
                    target=cls._loop.run_forever,
                    daemon=True,
                    name="LuckMailSdk-EventLoop"
                )
                cls._thread.start()

    @classmethod
    def run(cls, coro) -> Any:
        """Run coroutines synchronously in a background event loop"""
        cls._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, cls._loop)
        return future.result()


class LuckMailHttpClient:
    """
    LuckMail HTTP client (based on curl_cffi)

    use curl_cffi as bottom layer HTTP library, support TLS Fingerprint simulation.
    Automatic identification of calling context (synchronous/asynchronous), providing a unified request interface.

    Args:
        base_url: API Base URL,like https://your-domain.com
        api_key: API Key(required)
        api_secret: API Secret(optional, for HMAC Signature verification, higher security)
        timeout: Request timeout (seconds), default 30
        use_hmac: Whether to use HMAC Signature verification, default False(Required when using api_secret)
        impersonate: Browser fingerprint simulation, default "chrome"(optional "firefox","safari" wait)
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: Optional[str] = None,
        timeout: float = 30.0,
        use_hmac: bool = False,
        impersonate: str = "chrome",
        proxy_url: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.use_hmac = use_hmac and api_secret is not None
        self.impersonate = impersonate
        self.proxy_url = normalize_proxy_url(proxy_url)
        self._proxy_config = build_requests_proxy_config(self.proxy_url)

        # synchronous Session(lazy initialization)
        self._sync_session: Optional[curl_requests.Session] = None
        # asynchronous Session(lazy initialization)
        self._async_session: Optional[Any] = None

    def _get_sync_session(self) -> curl_requests.Session:
        """Get or create a sync Session"""
        if self._sync_session is None:
            session_kwargs = {
                "impersonate": self.impersonate,
                "timeout": self.timeout,
            }
            if self.proxy_url:
                try:
                    self._sync_session = curl_requests.Session(
                        proxy=self.proxy_url,
                        **session_kwargs,
                    )
                except TypeError:
                    self._sync_session = curl_requests.Session(**session_kwargs)
            else:
                self._sync_session = curl_requests.Session(**session_kwargs)
            if self._proxy_config and self._sync_session is not None:
                try:
                    self._sync_session.proxies = dict(self._proxy_config)
                except Exception:
                    pass
        return self._sync_session

    async def _get_async_session(self):
        """Get or create async Session"""
        if self._async_session is None:
            session_kwargs = {
                "impersonate": self.impersonate,
                "timeout": self.timeout,
            }
            if self.proxy_url:
                try:
                    self._async_session = curl_requests.AsyncSession(
                        proxy=self.proxy_url,
                        **session_kwargs,
                    )
                except TypeError:
                    self._async_session = curl_requests.AsyncSession(**session_kwargs)
            else:
                self._async_session = curl_requests.AsyncSession(**session_kwargs)
            if self._proxy_config and self._async_session is not None:
                try:
                    self._async_session.proxies = dict(self._proxy_config)
                except Exception:
                    pass
        return self._async_session

    def _build_headers(self) -> Dict[str, str]:
        """Build request header (including authentication information)"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if self.use_hmac and self.api_secret:
            # HMAC signature mode
            timestamp = str(int(time.time()))
            nonce = secrets.token_hex(16)
            signature = _generate_hmac_signature(
                self.api_secret, self.api_key, timestamp, nonce
            )
            headers["X-API-Key"] = self.api_key
            headers["X-Timestamp"] = timestamp
            headers["X-Nonce"] = nonce
            headers["X-Signature"] = signature
        elif self.api_key:
            # ordinary API Key Mode (recommended)
            headers["X-API-Key"] = self.api_key

        return headers

    def _build_url(self, path: str, params: Optional[Dict] = None) -> str:
        """Complete build URL"""
        url = f"{self.base_url}{path}"
        if params:
            # filter None value
            filtered = {k: v for k, v in params.items() if v is not None}
            if filtered:
                url = f"{url}?{urlencode(filtered)}"
        return url

    def _parse_response(self, status_code: int, content: bytes) -> Any:
        """Parse response data"""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # No JSON Responses (such as file streams) directly return the byte content
            return content

        if not isinstance(data, dict):
            return data

        code = data.get("code", -1)
        message = data.get("message", "Unknown error")

        if code != 0:
            if status_code == 401 or code == 401:
                raise AuthError(message)
            raise APIError(code, message, data.get("data"))

        return data.get("data")

    # ===================== asynchronous method =====================

    async def _async_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ) -> Any:
        """asynchronous HTTP ask"""
        session = await self._get_async_session()
        headers = self._build_headers()
        url = self._build_url(path, params)

        try:
            if method.upper() == "GET":
                response = await session.get(url, headers=headers)
            elif method.upper() == "POST":
                response = await session.post(
                    url, headers=headers, json=json_data or {}
                )
            elif method.upper() == "PUT":
                response = await session.put(
                    url, headers=headers, json=json_data or {}
                )
            elif method.upper() == "DELETE":
                response = await session.delete(url, headers=headers)
            else:
                raise ValueError(f"Not supported HTTP method: {method}")

            return self._parse_response(response.status_code, response.content)

        except (AuthError, APIError):
            raise
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg:
                from .exceptions import TimeoutError as LuckTimeoutError
                raise LuckTimeoutError(f"Request timeout: {path}") from e
            raise NetworkError(f"Request failed: {e}") from e

    async def _async_get_stream(self, path: str, params: Optional[Dict] = None) -> bytes:
        """Get streaming responses asynchronously (file downloads, etc.)"""
        session = await self._get_async_session()
        headers = self._build_headers()
        url = self._build_url(path, params)

        try:
            response = await session.get(url, headers=headers)
            return response.content
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg:
                from .exceptions import TimeoutError as LuckTimeoutError
                raise LuckTimeoutError(f"Request timeout: {path}") from e
            raise NetworkError(f"network error: {e}") from e

    async def aclose(self):
        """Close asynchronous client"""
        if self._async_session is not None:
            await self._async_session.close()
            self._async_session = None

    # ===================== sync method =====================

    def _sync_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ) -> Any:
        """synchronous HTTP request (using curl_cffi)"""
        session = self._get_sync_session()
        headers = self._build_headers()
        url = self._build_url(path, params)

        try:
            if method.upper() == "GET":
                response = session.get(url, headers=headers)
            elif method.upper() == "POST":
                response = session.post(
                    url, headers=headers, json=json_data or {}
                )
            elif method.upper() == "PUT":
                response = session.put(
                    url, headers=headers, json=json_data or {}
                )
            elif method.upper() == "DELETE":
                response = session.delete(url, headers=headers)
            else:
                raise ValueError(f"Not supported HTTP method: {method}")

            return self._parse_response(response.status_code, response.content)

        except (AuthError, APIError):
            raise
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg:
                from .exceptions import TimeoutError as LuckTimeoutError
                raise LuckTimeoutError(f"Request timeout: {path}") from e
            raise NetworkError(f"Request failed: {e}") from e

    def _sync_get_stream(self, path: str, params: Optional[Dict] = None) -> bytes:
        """Get streaming response synchronously"""
        session = self._get_sync_session()
        headers = self._build_headers()
        url = self._build_url(path, params)

        try:
            response = session.get(url, headers=headers)
            return response.content
        except Exception as e:
            err_msg = str(e).lower()
            if "timeout" in err_msg:
                from .exceptions import TimeoutError as LuckTimeoutError
                raise LuckTimeoutError(f"Request timeout: {path}") from e
            raise NetworkError(f"network error: {e}") from e

    # ===================== Unified interface (intelligent recognition synchronization/asynchronous)=====================

    def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
    ):
        """
        Unified request interface, intelligent identification of calling context:
        - exist async Called in a function: automatically returns to the coroutine, required await
        - Called in a normal function: return the result directly

        Usage example:
            # Synchronous call
            result = client.request("GET", "/api/v1/openapi/user/info")

            # asynchronous call
            result = await client.request("GET", "/api/v1/openapi/user/info")
        """
        if _is_async_context():
            return self._async_request(method, path, params=params, json_data=json_data)
        else:
            return self._sync_request(method, path, params=params, json_data=json_data)

    def get_stream(self, path: str, params: Optional[Dict] = None):
        """
        streaming GET Request (for file download), intelligent recognition synchronization/asynchronous context
        """
        if _is_async_context():
            return self._async_get_stream(path, params=params)
        else:
            return self._sync_get_stream(path, params=params)

    def close(self):
        """Turn off synchronization of client resources"""
        if self._sync_session is not None:
            self._sync_session.close()
            self._sync_session = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
