"""Authentication API.

Identity is managed by Authelia (the SSO gateway in front of this app),
which authenticates users and injects the trusted ``Remote-User`` header
via Caddy's ``forward_auth``. This router now only exposes a status
endpoint so the front-end can detect that auth is proxy-managed.

The previous in-app password / JWT / TOTP implementation has been retired.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def auth_status():
    return {
        "has_password": False,
        "has_totp": False,
        "proxy_auth": True,
    }