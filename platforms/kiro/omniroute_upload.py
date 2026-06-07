"""
OmniRoute Upload – push Kiro (AWS Builder ID) accounts as provider connections.

OmniRoute supports Kiro as a first-class provider.  Provider connections are
created via ``POST /api/providers``. Due to a strict middleware policy that rejects
Bearer tokens for management routes, we authenticate by performing a
dashboard login (POST /api/auth/login) with the admin password to get
an ``auth_token`` cookie, which we then use for the management request.

For Kiro accounts the provider ID is ``kiro``, and authType is ``oauth``
because we supply OAuth tokens (accessToken, refreshToken) directly.
"""

from __future__ import annotations

import logging
from typing import Any, Tuple

from curl_cffi import requests as cffi_requests

logger = logging.getLogger(__name__)


def _get_config_value(key: str) -> str:
    try:
        from core.config_store import config_store

        return str(config_store.get(key, "") or "").strip()
    except Exception:
        return ""


def _build_omniroute_kiro_payload(account) -> dict[str, Any]:
    """Build the OmniRoute ``createProviderConnection`` payload for a Kiro account."""
    extra = getattr(account, "extra", {}) or {}
    access_token = (
        extra.get("accessToken")
        or extra.get("access_token")
        or getattr(account, "token", "")
    )
    refresh_token = extra.get("refreshToken") or extra.get("refresh_token") or ""
    email = getattr(account, "email", "") or extra.get("email", "")

    return {
        "provider": "kiro",
        "authType": "oauth",
        "name": email or "Kiro Account",
        "email": email,
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "isActive": True,
        "testStatus": "unknown",
        "providerSpecificData": {
            "clientId": extra.get("clientId") or extra.get("client_id") or "",
            "clientSecret": extra.get("clientSecret") or extra.get("client_secret") or "",
            "region": extra.get("region") or "us-east-1",
            "provider": extra.get("provider") or "BuilderId",
        },
    }


def _get_omniroute_auth_cookie(api_url: str, password: str) -> str | None:
    """Perform a dashboard login to get the auth_token cookie."""
    if not password:
        return None
    login_url = f"{api_url.rstrip('/')}/api/auth/login"
    try:
        r = cffi_requests.post(
            login_url,
            json={"password": password},
            verify=False,
            timeout=15,
            impersonate="chrome110",
        )
        if r.status_code == 200:
            return r.cookies.get("auth_token")
    except Exception as e:
        logger.error("Failed to authenticate with OmniRoute: %s", e)
    return None


def upload_kiro_to_omniroute(
    account,
    api_url: str | None = None,
    admin_password: str | None = None,
) -> Tuple[bool, str]:
    """Upload a single Kiro account to an OmniRoute instance as a provider connection."""
    api_url = str(api_url or _get_config_value("omniroute_api_url")).strip()
    admin_password = str(
        admin_password or _get_config_value("omniroute_admin_password")
    ).strip()

    if not api_url:
        return False, "OmniRoute API URL not configured"

    payload = _build_omniroute_kiro_payload(account)
    url = f"{api_url.rstrip('/')}/api/providers"
    
    auth_token = _get_omniroute_auth_cookie(api_url, admin_password)
    cookies = {"auth_token": auth_token} if auth_token else {}

    try:
        logger.info("OmniRoute Kiro upload -> %s (email=%s)", url, payload.get("email", "?"))
        response = cffi_requests.post(
            url,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            cookies=cookies,
            json=payload,
            proxies=None,
            verify=False,
            timeout=30,
            impersonate="chrome110",
        )

        if response.status_code in (200, 201):
            return True, "Upload to OmniRoute successful"

        error_msg = f"Upload failed: HTTP {response.status_code}"
        try:
            detail = response.json()
            if isinstance(detail, dict):
                error_msg = str(
                    detail.get("error")
                    or detail.get("message")
                    or detail.get("msg")
                    or error_msg
                )
        except Exception:
            error_msg = f"{error_msg} - {response.text[:200]}"
        logger.warning("OmniRoute Kiro upload failed: %s", error_msg)
        return False, error_msg
    except Exception as exc:
        logger.error("OmniRoute Kiro upload exception: %s", exc)
        return False, f"Upload exception: {exc}"
