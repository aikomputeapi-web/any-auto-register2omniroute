"""Email domain name global policy verification."""

from __future__ import annotations

import re
from typing import Any


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _required_level_count(value: Any) -> int:
    text = str(value or "").strip()
    if not text:
        return 2
    try:
        level_count = int(text)
    except (TypeError, ValueError) as exc:
        raise ValueError("Domain name level must be an integer") from exc
    if level_count < 2:
        raise ValueError("The domain name level cannot be less than 2")
    return level_count


def validate_email_domain_policy(email: str, config: dict[str, Any] | None = None) -> None:
    cfg = config or {}
    if not _to_bool(cfg.get("email_domain_rule_enabled")):
        return

    address = str(email or "").strip().lower()
    if "@" not in address:
        raise ValueError("The email format is invalid and the domain name is missing.")

    _, domain = address.rsplit("@", 1)
    domain = domain.strip().strip(".")
    if not domain:
        raise ValueError("The email format is invalid and the domain name is missing.")

    levels = [part for part in domain.split(".") if part]
    required_levels = _required_level_count(cfg.get("email_domain_level_count"))
    if len(levels) < required_levels:
        raise ValueError(
            f"The email domain name does not meet the requirements: current {len(levels)} level, at least required {required_levels} class"
        )

    letters = len(re.findall(r"[a-z]", domain))
    digits = len(re.findall(r"\d", domain))
    if letters < 2 or digits < 2:
        raise ValueError("The email domain name does not meet the requirements: the domain name contains at least 2 English letters and 2 numbers")
