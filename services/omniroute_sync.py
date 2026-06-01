"""
OmniRoute Upload – push registered platform accounts as provider connections.
This module supports both OAuth (e.g. ChatGPT, Grok, Cursor, Kiro, OpenBlockLabs) 
and API key (e.g. Cloudflare, Mistral, Nvidia NIM, OpenRouter, Tavily) connections.
"""

from __future__ import annotations

import logging
from typing import Any, Tuple

from curl_cffi import requests as cffi_requests

logger = logging.getLogger(__name__)


def _get_extra(account: Any) -> dict:
    if hasattr(account, "get_extra"):
        try:
            extra = account.get_extra()
            if isinstance(extra, dict):
                return extra
        except Exception:
            pass
    extra = getattr(account, "extra", {})
    return extra if isinstance(extra, dict) else {}


def build_omniroute_payload(account: Any) -> dict[str, Any]:
    """
    Build the OmniRoute ``createProviderConnection`` payload for an account.
    Instructions for adding new accounts/platforms:
    1. If the new platform uses OAuth (requires accessToken, refreshToken, idToken):
       Add its platform name to the `oauth_platforms` set below.
    2. Define any custom client IDs or providerSpecificData inside the `providerSpecificData` mapping.
    3. If the platform uses standard API keys, it will default to 'apikey' and map `token` or `api_key` to `apiKey`.
    """
    platform = str(getattr(account, "platform", "") or "").lower()
    email = getattr(account, "email", "")
    token = getattr(account, "token", "")
    extra = _get_extra(account)

    # Map our platform strings to OmniRoute provider identifiers
    provider_map = {
        "chatgpt": "codex",
        "kiro": "kiro",
    }
    provider = provider_map.get(platform, platform)

    # Define which platforms are authenticated via OAuth
    oauth_platforms = {"chatgpt", "kiro", "grok", "cursor", "openblocklabs"}
    if platform in oauth_platforms:
        auth_type = "oauth"
    else:
        auth_type = "apikey"

    payload = {
        "provider": provider,
        "authType": auth_type,
        "name": email or f"{platform.capitalize()} Account",
        "email": email,
        "isActive": True,
        "testStatus": "unknown",
        "providerSpecificData": {},
    }

    if auth_type == "oauth":
        access_token = (
            extra.get("accessToken")
            or extra.get("access_token")
            or extra.get("sso")
            or extra.get("sso_token")
            or token
        )
        refresh_token = (
            extra.get("refreshToken")
            or extra.get("refresh_token")
            or extra.get("sso_rw")
            or ""
        )
        id_token = extra.get("idToken") or extra.get("id_token") or ""

        payload["accessToken"] = str(access_token or "").strip()
        payload["refreshToken"] = str(refresh_token or "").strip()
        if id_token:
            payload["idToken"] = str(id_token or "").strip()

        # Platform specific metadata
        if platform == "chatgpt":
            client_id = extra.get("client_id") or extra.get("clientId") or "app_EMoamEEZ73f0CkXaXp7hrann"
            payload["providerSpecificData"]["clientId"] = str(client_id).strip()
        elif platform == "kiro":
            payload["providerSpecificData"] = {
                "clientId": extra.get("clientId") or extra.get("client_id") or "",
                "clientSecret": extra.get("clientSecret") or extra.get("client_secret") or "",
                "region": extra.get("region") or "us-east-1",
                "provider": extra.get("provider") or "BuilderId",
            }
    else:
        api_key_val = (
            extra.get("api_key")
            or extra.get("api_token")
            or extra.get("apiKey")
            or token
        )
        payload["apiKey"] = str(api_key_val or "").strip()

    return payload


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


def _find_existing_connection(api_url: str, cookies: dict, provider: str, email: str | None = None) -> str | None:
    """Find the ID of an existing provider connection by provider name and optionally email."""
    try:
        r = cffi_requests.get(
            f"{api_url.rstrip('/')}/api/providers",
            headers={"Accept": "application/json"},
            cookies=cookies,
            verify=False,
            timeout=15,
            impersonate="chrome110",
        )
        if r.status_code != 200:
            return None
        data = r.json()
        connections = data.get("connections", data) if isinstance(data, dict) else data
        if not isinstance(connections, list):
            return None
        for conn in connections:
            if isinstance(conn, dict) and conn.get("provider") == provider:
                if not email or conn.get("email") == email:
                    return conn.get("id")
    except Exception as e:
        logger.warning("Could not list OmniRoute connections: %s", e)
    return None


def _put_update_connection(api_url: str, cookies: dict, connection_id: str, payload: dict) -> Tuple[bool, str]:
    """Update an existing OmniRoute connection via PUT."""
    url = f"{api_url.rstrip('/')}/api/providers/{connection_id}"
    try:
        response = cffi_requests.put(
            url,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            cookies=cookies,
            json=payload,
            verify=False,
            timeout=30,
            impersonate="chrome110",
        )
        if response.status_code in (200, 201):
            return True, f"Updated existing OmniRoute connection {connection_id} (PUT)"
        err = f"PUT update failed: HTTP {response.status_code} - {response.text[:200]}"
        logger.warning("OmniRoute PUT update failed: %s", err)
        return False, err
    except Exception as exc:
        logger.error("OmniRoute PUT update exception: %s", exc)
        return False, f"PUT update exception: {exc}"


def _kiro_device_code_flow(
    api_url: str,
    omniroute_cookies: dict,
    account: Any,
) -> Tuple[bool, str]:
    """Create a NEW kiro connection in OmniRoute via the device-code OAuth flow.

    Flow:
    1. Call GET /api/oauth/kiro/device-code  → get device_code + verification_uri
    2. Launch a Playwright browser with the account's saved AWS portal cookies
    3. Navigate to verification_uri and click the Allow button
    4. Poll POST /api/oauth/kiro/poll until OmniRoute reports success
    """
    import time

    extra = _get_extra(account)
    portal_cookies: list = extra.get("portalCookies", [])

    if not portal_cookies:
        return False, (
            "No AWS portal cookies saved for this account — "
            "re-register the account to capture portal session cookies, "
            "then retry the OmniRoute upload."
        )

    # Step 1: Get device code from OmniRoute
    try:
        dc_r = cffi_requests.get(
            f"{api_url.rstrip('/')}/api/oauth/kiro/device-code",
            cookies=omniroute_cookies,
            verify=False,
            timeout=15,
            impersonate="chrome110",
        )
        dc_r.raise_for_status()
        dc = dc_r.json()
    except Exception as e:
        return False, f"Failed to get device code: {e}"

    device_code = dc.get("device_code", "")
    verification_uri = dc.get("verification_uri_complete") or dc.get("verification_uri", "")
    user_code = dc.get("user_code", "")
    interval = max(int(dc.get("interval", 5)), 3)
    client_id = dc.get("_clientId")
    client_secret = dc.get("_clientSecret")
    region = dc.get("_region", "us-east-1")

    if not device_code or not verification_uri:
        return False, f"Invalid device code response: {dc}"

    logger.info(
        "Kiro device-code flow: user_code=%s, url=%s",
        user_code,
        verification_uri,
    )

    # Step 2: Use Playwright to approve the device code with the portal session
    try:
        from playwright.sync_api import sync_playwright
        import os

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            
            context_opts = {}
            user_agent = extra.get("userAgent") or extra.get("user_agent")
            if user_agent:
                context_opts["user_agent"] = user_agent
            ctx = browser.new_context(**context_opts)

            # Restore the portal cookies from registration
            loaded = 0
            for c in portal_cookies:
                try:
                    ctx.add_cookies([c])
                    loaded += 1
                except Exception:
                    pass
            logger.info("Loaded %d/%d portal cookies into browser context", loaded, len(portal_cookies))

            page = ctx.new_page()

            logger.info("Navigating to device verification URL: %s", verification_uri)
            page.goto(verification_uri, timeout=30_000)
            page.wait_for_load_state("networkidle", timeout=20_000)

            # Log what page we landed on
            current_url = page.url
            page_title = page.title()
            logger.info("Landed on: url=%s title=%s", current_url, page_title)

            # Take a screenshot for debugging
            try:
                ss_path = os.path.join(os.getcwd(), "kiro_device_auth_debug.png")
                page.screenshot(path=ss_path)
                logger.info("Screenshot saved: %s", ss_path)
            except Exception as ss_e:
                logger.warning("Screenshot failed: %s", ss_e)

            # Log all buttons visible on the page
            try:
                btns = page.get_by_role("button").all()
                btn_labels = [b.inner_text() for b in btns]
                logger.info("Buttons on page: %s", btn_labels)
            except Exception:
                pass

            # The page may have a "Next" button to confirm the user code, then an "Allow" button
            # We dynamically search and click any visible button from the list in a loop
            for attempt in range(5):
                clicked_any = False
                for btn_text in ["Confirm", "Next", "Allow", "Authorize", "Submit"]:
                    try:
                        btn = page.get_by_role("button", name=btn_text, exact=False)
                        if btn.is_visible(timeout=2_000):
                            btn.click()
                            page.wait_for_load_state("networkidle", timeout=8_000)
                            logger.info("Clicked '%s' button — now at: %s", btn_text, page.url)
                            clicked_any = True
                            break
                    except Exception:
                        pass
                if not clicked_any:
                    # Brief pause if no buttons are visible to let transitions finish
                    page.wait_for_timeout(1_000)

            browser.close()
    except Exception as e:
        logger.error("Playwright device authorization failed: %s", e)
        return False, f"Browser device authorization failed: {e}"

    # Step 3: Poll OmniRoute until success (up to 60 seconds)
    poll_url = f"{api_url.rstrip('/')}/api/oauth/kiro/poll"
    for attempt in range(20):
        try:
            time.sleep(interval)
            poll_r = cffi_requests.post(
                poll_url,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                cookies=omniroute_cookies,
                json={
                    "deviceCode": device_code,
                    "codeVerifier": "",
                    "extraData": {
                        "_clientId": client_id,
                        "_clientSecret": client_secret,
                        "_region": region,
                    }
                },
                verify=False,
                timeout=15,
                impersonate="chrome110",
            )
            result = poll_r.json()
            if result.get("success"):
                conn_id = result.get("connectionId") or result.get("id", "?")
                logger.info("OmniRoute kiro connection created via device-code: %s", conn_id)
                return True, f"New kiro connection added to OmniRoute (id={conn_id})"
            err = result.get("error", "")
            if err and err not in ("authorization_pending", "slow_down"):
                return False, f"Device code poll failed: {err} — {result.get('errorDescription', '')}"
            logger.debug("Poll attempt %d: pending (%s)", attempt + 1, err)
        except Exception as e:
            logger.warning("Poll attempt %d exception: %s", attempt + 1, e)

    return False, "Device code authorization timed out after 60s — the portal session may have expired"


def _oidc_refresh_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    region: str = "us-east-1",
) -> dict | None:
    """Refresh an AWS Builder ID token via the AWS OIDC endpoint.

    Returns a dict with accessToken, refreshToken, expiresIn on success, else None.
    """
    url = f"https://oidc.{region}.amazonaws.com/token"
    try:
        r = cffi_requests.post(
            url,
            json={
                "clientId": client_id,
                "clientSecret": client_secret,
                "refreshToken": refresh_token,
                "grantType": "refresh_token",
            },
            timeout=30,
            impersonate="chrome110",
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.warning("OIDC token refresh failed: %s", e)
    return None


def _kiro_direct_import(
    api_url: str,
    omniroute_cookies: dict,
    account: Any,
) -> Tuple[bool, str]:
    """Import a Kiro (Builder ID) account via the direct-import endpoint.

    This endpoint accepts pre-validated tokens with OIDC client credentials,
    bypassing the social-auth validation that fails for Builder ID tokens.
    It calls ``createProviderConnection`` directly, creating a NEW connection
    for each unique email.

    Flow:
    1. OIDC-refresh the token to validate it and get a fresh accessToken.
    2. POST /api/oauth/kiro/direct-import with refreshToken + clientId/clientSecret.
       OmniRoute verifies via the OIDC path and creates the connection.
    """
    extra = _get_extra(account)
    refresh_token = (
        extra.get("refreshToken")
        or extra.get("refresh_token")
        or getattr(account, "token", "")
    )
    client_id = extra.get("clientId") or extra.get("client_id") or ""
    client_secret = extra.get("clientSecret") or extra.get("client_secret") or ""
    region = extra.get("region") or "us-east-1"

    if not refresh_token:
        return False, "No refresh token available for this account"
    if not client_id or not client_secret:
        return False, "No OIDC client credentials (clientId/clientSecret) for this account"

    # Step 1: Verify the token still works via OIDC refresh
    token_data = _oidc_refresh_token(refresh_token, client_id, client_secret, region)
    if not token_data:
        return False, "OIDC token refresh failed — token may be expired or revoked"

    fresh_access = token_data.get("accessToken", "")
    fresh_refresh = token_data.get("refreshToken", refresh_token)
    email = getattr(account, "email", "") or extra.get("email", "")

    # Step 2: Call the direct-import endpoint
    import_url = f"{api_url.rstrip('/')}/api/oauth/kiro/direct-import"
    payload = {
        "refreshToken": fresh_refresh,
        "accessToken": fresh_access,
        "email": email,
        "region": region,
        "clientId": client_id,
        "clientSecret": client_secret,
    }

    try:
        r = cffi_requests.post(
            import_url,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            cookies=omniroute_cookies,
            json=payload,
            verify=False,
            timeout=60,
            impersonate="chrome110",
        )

        if r.status_code in (200, 201):
            try:
                data = r.json()
                conn_id = data.get("connection", {}).get("id", "?")
                conn_email = data.get("connection", {}).get("email", email)
                return True, f"New kiro connection created via direct-import (id={conn_id}, email={conn_email})"
            except Exception:
                return True, "New kiro connection created via direct-import"

        # Parse error
        try:
            err_data = r.json()
            err_msg = str(err_data.get("error", "")) or r.text[:200]
        except Exception:
            err_msg = r.text[:200]
        return False, f"Direct-import failed: HTTP {r.status_code} - {err_msg}"

    except Exception as exc:
        return False, f"Direct-import exception: {exc}"


def upload_to_omniroute(
    account: Any,
    api_url: str | None = None,
    admin_password: str | None = None,
) -> Tuple[bool, str]:
    """Upload a registered account to an OmniRoute instance as a provider connection.

    Strategy (for Kiro / Builder ID accounts):
    1. Try POST /api/oauth/kiro/direct-import with OIDC-refreshed tokens.
       This creates a NEW connection per unique email.
    2. If direct-import is unavailable, fall back to POST /api/providers.
    3. If POST returns 400 "Invalid provider":
       a. Try the device-code OAuth flow.
       b. Fall back to PUT-updating the existing slot.

    For non-Kiro providers, uses POST /api/providers directly.
    """
    from core.config_store import config_store

    api_url = str(api_url or config_store.get("omniroute_api_url", "")).strip()
    admin_password = str(admin_password or config_store.get("omniroute_admin_password", "")).strip()

    if not api_url:
        return False, "OmniRoute API URL not configured"

    payload = build_omniroute_payload(account)
    provider = payload.get("provider", "")
    platform = str(getattr(account, "platform", "") or "").lower()

    auth_token = _get_omniroute_auth_cookie(api_url, admin_password)
    cookies = {"auth_token": auth_token} if auth_token else {}

    # ── Kiro: prefer direct-import (creates NEW connections via OIDC) ──
    if platform == "kiro":
        extra = _get_extra(account)
        has_client_creds = bool(
            (extra.get("clientId") or extra.get("client_id"))
            and (extra.get("clientSecret") or extra.get("client_secret"))
        )
        if has_client_creds:
            logger.info(
                "OmniRoute kiro upload -> direct-import (email=%s)",
                payload.get("email", "?"),
            )
            ok, msg = _kiro_direct_import(api_url, cookies, account)
            if ok:
                return True, msg
            # If direct-import endpoint doesn't exist (404), fall through
            if "404" not in msg and "not found" not in msg.lower():
                logger.warning("Direct-import failed: %s. Trying fallback strategies.", msg)

    # ── Generic: try POST /api/providers ──
    post_url = f"{api_url.rstrip('/')}/api/providers"
    try:
        logger.info(
            "OmniRoute %s upload -> %s (email=%s)",
            provider,
            post_url,
            payload.get("email", "?"),
        )
        response = cffi_requests.post(
            post_url,
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

        # Parse error body
        error_body = ""
        try:
            detail = response.json()
            if isinstance(detail, dict):
                error_body = str(
                    detail.get("error")
                    or detail.get("message")
                    or detail.get("msg")
                    or ""
                )
        except Exception:
            error_body = response.text[:300]

        if response.status_code == 400 and "invalid provider" in error_body.lower():
            logger.warning(
                "OmniRoute POST rejected provider '%s'. "
                "Attempting device-code OAuth flow to create a new connection.",
                provider,
            )
            ok, msg = _kiro_device_code_flow(api_url, cookies, account)
            if ok:
                return True, msg

            # Device-code flow failed — fall back to PUT-updating the existing slot
            logger.warning(
                "Device-code flow failed (%s). Falling back to PUT-update of existing connection.",
                msg,
            )
            existing_id = _find_existing_connection(api_url, cookies, provider, email=payload.get("email"))
            if existing_id:
                put_ok, put_msg = _put_update_connection(api_url, cookies, existing_id, payload)
                if put_ok:
                    return True, f"{put_msg} (Note: {msg})"
                return False, f"PUT update also failed: {put_msg}. Device-code error: {msg}"
            return False, (
                f"OmniRoute: provider '{provider}' rejected by API, device-code flow failed ({msg}), "
                f"and no existing connection found to update. "
                f"Re-register the account to capture portal cookies, then retry."
            )

        error_msg = f"Upload failed: HTTP {response.status_code} - {error_body or response.text[:200]}"
        logger.warning("OmniRoute upload failed: %s | full response: %s", error_msg, response.text[:500])
        return False, error_msg
    except Exception as exc:
        logger.error("OmniRoute upload exception: %s", exc)
        return False, f"Upload exception: {exc}"

