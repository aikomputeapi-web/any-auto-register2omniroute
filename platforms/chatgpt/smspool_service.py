"""SMSPool phone service for ChatGPT phone OTP verification.

Uses the SMSPool.net API to purchase temporary phone numbers and
retrieve SMS verification codes for the OpenAI/ChatGPT add-phone step.

API reference: https://documenter.getpostman.com/view/30155063/2s9YXmZ1JY

Configuration keys (read from the shared config dict):
    smspool_api_key          – Required. Your SMSPool API key.
    smspool_country          – Country ID, default "1" (United States).
    smspool_service          – Service ID, default "671" (OpenAI / ChatGPT).
    smspool_pricing_option   – "0" cheapest, "1" highest success rate. Default "1".
    smspool_max_price        – Optional max price cap per order.
    smspool_max_attempts     – How many numbers to try before giving up. Default 3.
    smspool_poll_interval    – Seconds between status checks. Default 5.
    smspool_poll_timeout     – Total seconds to wait for code. Default 120.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx


SMSPOOL_API_BASE = "https://api.smspool.net"

# OpenAI / ChatGPT service ID on SMSPool
DEFAULT_SERVICE_ID = "671"
# United States country ID
DEFAULT_COUNTRY_ID = "1"
# Prefer highest success rate
DEFAULT_PRICING_OPTION = "1"

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_POLL_INTERVAL = 5
DEFAULT_POLL_TIMEOUT = 120

# SMS check status codes
STATUS_PENDING = 1
STATUS_COMPLETED = 3
STATUS_EXPIRED = 6


@dataclass
class SMSPoolOrder:
    """Represents an active SMSPool order."""

    order_id: str
    phone_number: str
    country: str = ""
    service: str = ""
    price: float = 0.0


class SMSPoolError(RuntimeError):
    """Base exception for SMSPool operations."""
    pass


class SMSPoolOrderError(SMSPoolError):
    """Failed to place an order."""
    pass


class SMSPoolTimeoutError(SMSPoolError):
    """Timed out waiting for SMS."""
    pass


def _to_positive_int(value, default: int, *, minimum: int = 1) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    return parsed if parsed >= minimum else default


def _extract_otp_from_sms(sms_text: str, *, min_digits: int = 4, max_digits: int = 8) -> Optional[str]:
    """Extract a numeric OTP code from an SMS message body."""
    if not sms_text:
        return None
    # First try to find a standalone digit sequence of the expected length
    pattern = re.compile(r"(?<!\d)(\d{" + str(min_digits) + "," + str(max_digits) + r"})(?!\d)")
    match = pattern.search(sms_text)
    if match:
        return match.group(1)
    return None


class SMSPoolPhoneService:
    """Phone number provider using the SMSPool.net API."""

    def __init__(
        self,
        config: Optional[dict] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.config = dict(config or {})
        self.log_fn = log_fn or (lambda _msg: None)

        self.api_key = str(self.config.get("smspool_api_key", "") or "").strip()
        self.country_id = str(
            self.config.get("smspool_country", "") or DEFAULT_COUNTRY_ID
        ).strip()
        self.service_id = str(
            self.config.get("smspool_service", "") or DEFAULT_SERVICE_ID
        ).strip()
        self.pricing_option = str(
            self.config.get("smspool_pricing_option", "") or DEFAULT_PRICING_OPTION
        ).strip()
        self.max_price = str(self.config.get("smspool_max_price", "") or "").strip()

        self.max_attempts = _to_positive_int(
            self.config.get("smspool_max_attempts"), DEFAULT_MAX_ATTEMPTS
        )
        self.poll_interval = _to_positive_int(
            self.config.get("smspool_poll_interval"), DEFAULT_POLL_INTERVAL, minimum=2
        )
        self.poll_timeout = _to_positive_int(
            self.config.get("smspool_poll_timeout"), DEFAULT_POLL_TIMEOUT, minimum=30
        )

        self._client: Optional[httpx.Client] = None
        self._active_order: Optional[SMSPoolOrder] = None

    @property
    def enabled(self) -> bool:
        """Service is enabled when an API key is configured."""
        return bool(self.api_key)

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=30.0,
                follow_redirects=True,
                trust_env=False,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _log(self, message: str) -> None:
        self.log_fn(f"[SMSPool] {message}")

    # ── API Methods ──────────────────────────────────────────────────

    def purchase_number(self) -> SMSPoolOrder:
        """Order a phone number for OpenAI/ChatGPT verification.

        Returns:
            SMSPoolOrder with order_id and phone_number.

        Raises:
            SMSPoolOrderError: If the API rejects the order.
        """
        client = self._get_client()
        url = f"{SMSPOOL_API_BASE}/purchase/sms"

        form_data = {
            "key": self.api_key,
            "country": self.country_id,
            "service": self.service_id,
            "pricing_option": self.pricing_option,
        }
        if self.max_price:
            form_data["max_price"] = self.max_price

        self._log(
            f"Ordering number: country={self.country_id} "
            f"service={self.service_id} pricing_option={self.pricing_option}"
        )

        try:
            resp = client.post(url, data=form_data)
        except Exception as e:
            raise SMSPoolOrderError(f"HTTP error ordering number: {e}") from e

        if resp.status_code != 200:
            raise SMSPoolOrderError(
                f"Order failed HTTP {resp.status_code}: {resp.text[:300]}"
            )

        try:
            data = resp.json()
        except Exception:
            raise SMSPoolOrderError(f"Non-JSON response: {resp.text[:300]}")

        if not data.get("success"):
            error_msg = data.get("message", data.get("error", resp.text[:300]))
            raise SMSPoolOrderError(f"Order rejected: {error_msg}")

        order = SMSPoolOrder(
            order_id=str(data.get("order_id", "")),
            phone_number=str(data.get("number", "")),
            country=str(data.get("country", "")),
            service=str(data.get("service", "")),
            price=float(data.get("price", 0) or 0),
        )

        if not order.order_id or not order.phone_number:
            raise SMSPoolOrderError(f"Incomplete order response: {data}")

        self._active_order = order
        self._log(
            f"Order placed: order_id={order.order_id} "
            f"phone={order.phone_number} price=${order.price:.2f}"
        )
        return order

    def check_sms(self, order_id: str) -> dict:
        """Check the SMS status for a given order.

        Returns:
            Raw API response dict with keys: status, sms, full_sms, etc.
        """
        client = self._get_client()
        url = f"{SMSPOOL_API_BASE}/sms/check"

        try:
            resp = client.post(url, data={"key": self.api_key, "orderid": order_id})
        except Exception as e:
            return {"status": -1, "error": str(e)}

        if resp.status_code != 200:
            return {"status": -1, "error": f"HTTP {resp.status_code}"}

        try:
            return resp.json()
        except Exception:
            return {"status": -1, "error": "non-JSON response"}

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending SMS order and get a refund.

        Returns:
            True if cancellation was successful.
        """
        client = self._get_client()
        url = f"{SMSPOOL_API_BASE}/sms/cancel"

        try:
            resp = client.post(url, data={"key": self.api_key, "orderid": order_id})
            if resp.status_code == 200:
                data = resp.json()
                success = bool(data.get("success"))
                self._log(
                    f"Cancel order {order_id}: "
                    f"{'success' if success else data.get('message', 'failed')}"
                )
                return success
        except Exception as e:
            self._log(f"Cancel order {order_id} error: {e}")
        return False

    def wait_for_code(
        self,
        order_id: str,
        *,
        timeout: Optional[int] = None,
        poll_interval: Optional[int] = None,
    ) -> Optional[str]:
        """Poll the SMSPool API until an OTP code is received or timeout.

        Args:
            order_id: The SMSPool order ID.
            timeout: Total wait time in seconds (uses self.poll_timeout by default).
            poll_interval: Seconds between polls (uses self.poll_interval by default).

        Returns:
            The extracted OTP code string, or None if timed out.
        """
        wait_timeout = timeout or self.poll_timeout
        interval = poll_interval or self.poll_interval
        deadline = time.time() + wait_timeout

        self._log(f"Waiting for SMS code (order={order_id}, timeout={wait_timeout}s)...")

        while time.time() < deadline:
            result = self.check_sms(order_id)
            status = int(result.get("status", -1))

            if status == STATUS_COMPLETED:
                sms_code = str(result.get("sms", "")).strip()
                full_sms = str(result.get("full_sms", "")).strip()
                self._log(f"SMS received: code={sms_code}")

                # The 'sms' field usually contains just the code
                if sms_code and sms_code.isdigit():
                    return sms_code

                # Fallback: extract from full_sms
                extracted = _extract_otp_from_sms(full_sms)
                if extracted:
                    return extracted

                # Last resort: return whatever sms field had
                if sms_code:
                    return sms_code

                self._log(f"Could not extract OTP from SMS: {full_sms[:200]}")
                return None

            if status == STATUS_EXPIRED:
                self._log(f"Order {order_id} expired/cancelled by provider")
                return None

            if status == -1:
                error = result.get("error", "unknown")
                self._log(f"Check error: {error}")
                # Don't give up on transient errors, keep polling

            # STATUS_PENDING or other - keep waiting
            remaining = int(deadline - time.time())
            if remaining > 0:
                time.sleep(min(interval, remaining))

        self._log(f"Timed out waiting for SMS code (order={order_id})")
        return None

    # ── High-level: acquire + wait ───────────────────────────────────

    def acquire_and_wait_for_code(self) -> tuple[Optional[str], Optional[str]]:
        """Purchase a number and wait for the verification code.

        Tries up to self.max_attempts different numbers.

        Returns:
            (phone_number, otp_code) on success, (None, None) on failure.
        """
        for attempt in range(self.max_attempts):
            order: Optional[SMSPoolOrder] = None
            try:
                order = self.purchase_number()
            except SMSPoolOrderError as e:
                self._log(f"Attempt {attempt + 1}/{self.max_attempts}: {e}")
                if attempt + 1 < self.max_attempts:
                    time.sleep(3)
                continue

            # Return the phone number for the caller to submit to OpenAI,
            # then wait for the code
            return order.phone_number, order.order_id

        self._log("All SMSPool attempts exhausted")
        return None, None

    def format_phone_for_openai(self, phone_number: str) -> str:
        """Format the phone number for OpenAI's add-phone endpoint.

        SMSPool returns numbers without '+' prefix typically.
        OpenAI expects international format like '+1234567890'.
        """
        phone = str(phone_number or "").strip()
        if not phone:
            return phone
        # Remove any non-digit characters except leading +
        if phone.startswith("+"):
            return phone
        # Add + prefix for international format
        return f"+{phone}"
