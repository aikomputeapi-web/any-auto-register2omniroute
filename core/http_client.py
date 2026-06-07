"""Universal HTTP client - based on curl_cffi, supports proxy, retry, session management"""

"""
HTTP client encapsulation
based on curl_cffi of HTTP Request encapsulation, support proxy and error handling
"""

import time
import json
from typing import Optional, Dict, Any, Union, Tuple
from dataclasses import dataclass
import logging

from curl_cffi import requests as cffi_requests
from curl_cffi.requests import Session, Response
from .proxy_utils import build_requests_proxy_config


logger = logging.getLogger(__name__)


@dataclass
class RequestConfig:
    """HTTP Request configuration"""

    timeout: int = 30
    max_retries: int = 3
    retry_delay: float = 1.0
    impersonate: str = "chrome"
    verify_ssl: bool = True
    follow_redirects: bool = True


class HTTPClientError(Exception):
    """HTTP Client exception"""

    pass


class HTTPClient:
    """
    HTTP client encapsulation
    Supports proxies, retries, error handling and session management
    """

    def __init__(
        self,
        proxy_url: Optional[str] = None,
        config: Optional[RequestConfig] = None,
        session: Optional[Session] = None,
    ):
        """
        initialization HTTP client

        Args:
            proxy_url: acting URL,like "http://127.0.0.1:7890"
            config: Request configuration
            session: Reusable session object
        """
        self.proxy_url = proxy_url
        self.config = config or RequestConfig()
        self._session = session

    @property
    def proxies(self) -> Optional[Dict[str, str]]:
        """Get proxy configuration"""
        return build_requests_proxy_config(self.proxy_url)

    @property
    def session(self) -> Session:
        """Get the session object (singleton)"""
        if self._session is None:
            self._session = Session(
                proxies=self.proxies,
                impersonate=self.config.impersonate,
                verify=self.config.verify_ssl,
                timeout=self.config.timeout,
            )
        return self._session

    def request(self, method: str, url: str, **kwargs) -> Response:
        """
        send HTTP ask

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, etc.)
            url: ask URL
            **kwargs: Other request parameters

        Returns:
            Response object

        Raises:
            HTTPClientError: Request failed
        """
        # Set default parameters
        kwargs.setdefault("timeout", self.config.timeout)
        kwargs.setdefault("allow_redirects", self.config.follow_redirects)

        # Add proxy configuration
        if self.proxies and "proxies" not in kwargs:
            kwargs["proxies"] = self.proxies

        last_exception = None
        for attempt in range(self.config.max_retries):
            try:
                response = self.session.request(method, url, **kwargs)

                # Check response status code
                if response.status_code >= 400:
                    logger.warning(
                        f"HTTP {response.status_code} for {method} {url}"
                        f" (attempt {attempt + 1}/{self.config.max_retries})"
                    )

                    # If it's a server error, try again
                    if (
                        response.status_code >= 500
                        and attempt < self.config.max_retries - 1
                    ):
                        time.sleep(self.config.retry_delay * (attempt + 1))
                        continue

                return response

            except (cffi_requests.RequestsError, ConnectionError, TimeoutError) as e:
                last_exception = e
                logger.warning(
                    f"Request failed: {method} {url} (attempt {attempt + 1}/{self.config.max_retries}): {e}"
                )

                if attempt < self.config.max_retries - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                else:
                    break

        raise HTTPClientError(
            f"The request failed, the maximum number of retries has been reached: {method} {url} - {last_exception}"
        )

    def get(self, url: str, **kwargs) -> Response:
        """send GET ask"""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, data: Any = None, json: Any = None, **kwargs) -> Response:
        """send POST ask"""
        return self.request("POST", url, data=data, json=json, **kwargs)

    def put(self, url: str, data: Any = None, json: Any = None, **kwargs) -> Response:
        """send PUT ask"""
        return self.request("PUT", url, data=data, json=json, **kwargs)

    def delete(self, url: str, **kwargs) -> Response:
        """send DELETE ask"""
        return self.request("DELETE", url, **kwargs)

    def head(self, url: str, **kwargs) -> Response:
        """send HEAD ask"""
        return self.request("HEAD", url, **kwargs)

    def options(self, url: str, **kwargs) -> Response:
        """send OPTIONS ask"""
        return self.request("OPTIONS", url, **kwargs)

    def patch(self, url: str, data: Any = None, json: Any = None, **kwargs) -> Response:
        """send PATCH ask"""
        return self.request("PATCH", url, data=data, json=json, **kwargs)

    def download_file(self, url: str, filepath: str, chunk_size: int = 8192) -> None:
        """
        Download file

        Args:
            url: document URL
            filepath: save path
            chunk_size: block size

        Raises:
            HTTPClientError: Download failed
        """
        try:
            response = self.get(url, stream=True)
            response.raise_for_status()

            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)

        except Exception as e:
            raise HTTPClientError(f"Download file failed: {url} - {e}")

    def check_proxy(self, test_url: str = "https://httpbin.org/ip") -> bool:
        """
        Check if proxy is available

        Args:
            test_url: test URL

        Returns:
            bool: Is the agent available?
        """
        if not self.proxy_url:
            return False

        try:
            response = self.get(test_url, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def close(self):
        """Close session"""
        if self._session:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
