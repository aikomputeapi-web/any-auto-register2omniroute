#!/usr/bin/env python3
"""Scaffold a new any-auto-register platform plugin.

Usage (from repo root):
    python scripts/new_platform.py my_platform
    python scripts/new_platform.py my_platform --display-name "My Platform"
    python scripts/new_platform.py my_platform --executors headless,headed
    python scripts/new_platform.py my_platform --no-core   # plugin.py only

After scaffolding:
    1. Implement registration logic in platforms/<name>/core.py (or plugin.py)
    2. Restart: python main.py
    3. Verify: GET http://localhost:8000/api/platforms?type=all
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VALID_NAME = re.compile(r"^[a-z][a-z0-9_]*$")

PLUGIN_TEMPLATE = '''"""{display_name} platform plugin"""
from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class {class_name}(BasePlatform):
    name = "{name}"
    display_name = "{display_name}"
    version = "1.0.0"
    supported_executors = {supported_executors!r}

    def __init__(
        self,
        config: Optional[RegisterConfig] = None,
        mailbox: Optional[BaseMailbox] = None,
    ):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: str = None) -> Account:
        from platforms.{name}.core import {register_class}

        password = password or self.generate_password()
        email, otp_cb = self.prepare_mailbox_otp(
            email,
            code_pattern=r"(\\d{{6}})",  # adjust if the platform uses a different code format
            require_mailbox=True,
        )

        reg = {register_class}(
            proxy=self.config.proxy,
            headless=self.wants_headless,
        )
        reg.log = self.log

        ok, info = reg.register(
            email=email,
            password=password,
            otp_callback=otp_cb,
        )
        if not ok:
            raise RuntimeError(
                f"{display_name} registration failed: {{info.get('error')}}"
            )

        return self.make_account(
            email=info.get("email") or email,
            password=info.get("password") or password,
            token=info.get("token") or info.get("api_key") or "",
            status=AccountStatus.REGISTERED,
            extra={{
                "api_key": info.get("api_key", ""),
                # Put platform-specific fields here
            }},
        )

    def check_valid(self, account: Account) -> bool:
        return bool(account.token or (account.extra or {{}}).get("api_key"))
'''

PLUGIN_ONLY_TEMPLATE = '''"""{display_name} platform plugin"""
from typing import Optional

from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register


@register
class {class_name}(BasePlatform):
    name = "{name}"
    display_name = "{display_name}"
    version = "1.0.0"
    supported_executors = {supported_executors!r}

    def __init__(
        self,
        config: Optional[RegisterConfig] = None,
        mailbox: Optional[BaseMailbox] = None,
    ):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: str = None) -> Account:
        password = password or self.generate_password()
        email, otp_cb = self.prepare_mailbox_otp(email, require_mailbox=False)

        # TODO: implement registration (HTTP / Playwright / external script)
        # Example with built-in executors:
        # captcha = self._make_captcha()
        # with self._make_executor() as ex:
        #     ...

        self.log(f"Starting registration for {{email}}")
        raise NotImplementedError("{name} register() not implemented yet")

        # return self.make_account(
        #     email=email,
        #     password=password,
        #     token="",
        #     status=AccountStatus.REGISTERED,
        #     extra={{}},
        # )

    def check_valid(self, account: Account) -> bool:
        return bool(account.token or (account.extra or {{}}).get("api_key"))
'''

CORE_TEMPLATE = '''"""Core registration logic for {display_name}"""
from typing import Callable, Optional, Tuple


class {register_class}:
    def __init__(self, proxy: Optional[str] = None, headless: bool = True):
        self.proxy = proxy
        self.headless = headless
        self.log: Callable[[str], None] = print

    def register(
        self,
        email: str,
        password: Optional[str] = None,
        otp_callback: Optional[Callable[[], Optional[str]]] = None,
    ) -> Tuple[bool, dict]:
        """
        Run the registration flow.

        Returns:
            (True, {{"email", "password", "token"?, "api_key"?}})
            (False, {{"error": "..."}})
        """
        self.log(f"Starting registration for {{email}}")

        # TODO: implement steps
        # 1. Open signup / call API
        # 2. Fill credentials
        # 3. Solve captcha if needed
        # 4. If OTP required: code = otp_callback() if otp_callback else None
        # 5. Extract tokens / API keys
        # 6. Return result

        return False, {{"error": "Not implemented"}}
'''


def to_class_name(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_")) + "Platform"


def to_register_class(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_")) + "Register"


def to_display_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.split("_"))


def parse_executors(raw: str) -> list[str]:
    allowed = {"protocol", "headless", "headed"}
    parts = [p.strip().lower() for p in (raw or "").split(",") if p.strip()]
    if not parts:
        parts = ["headless", "headed"]
    bad = [p for p in parts if p not in allowed]
    if bad:
        raise SystemExit(f"Unknown executor(s): {bad}. Allowed: {sorted(allowed)}")
    return parts


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold a new platform plugin")
    parser.add_argument("name", help="Directory / plugin id (lowercase, e.g. my_platform)")
    parser.add_argument("--display-name", default="", help='UI label (default: title-cased name)')
    parser.add_argument(
        "--executors",
        default="headless,headed",
        help="Comma-separated: protocol,headless,headed (default: headless,headed)",
    )
    parser.add_argument(
        "--no-core",
        action="store_true",
        help="Only create plugin.py (skip core.py)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files",
    )
    args = parser.parse_args()

    name = args.name.strip().lower()
    if not VALID_NAME.match(name):
        print(
            f"Invalid name '{args.name}'. Use lowercase letters, digits, underscores; "
            "must start with a letter.",
            file=sys.stderr,
        )
        return 1

    repo_root = Path(__file__).resolve().parents[1]
    target = repo_root / "platforms" / name
    if target.exists() and not args.force:
        if any(target.iterdir()):
            print(f"Directory already exists and is not empty: {target}", file=sys.stderr)
            print("Pass --force to overwrite scaffold files.", file=sys.stderr)
            return 1

    executors = parse_executors(args.executors)
    display_name = args.display_name.strip() or to_display_name(name)
    class_name = to_class_name(name)
    register_class = to_register_class(name)

    target.mkdir(parents=True, exist_ok=True)
    (target / "__init__.py").write_text("", encoding="utf-8")

    if args.no_core:
        plugin_src = PLUGIN_ONLY_TEMPLATE.format(
            name=name,
            display_name=display_name,
            class_name=class_name,
            supported_executors=executors,
        )
    else:
        plugin_src = PLUGIN_TEMPLATE.format(
            name=name,
            display_name=display_name,
            class_name=class_name,
            register_class=register_class,
            supported_executors=executors,
        )
        core_path = target / "core.py"
        if core_path.exists() and not args.force:
            print(f"Refusing to overwrite {core_path} (use --force)", file=sys.stderr)
            return 1
        core_path.write_text(
            CORE_TEMPLATE.format(
                display_name=display_name,
                register_class=register_class,
            ),
            encoding="utf-8",
        )

    plugin_path = target / "plugin.py"
    if plugin_path.exists() and not args.force:
        print(f"Refusing to overwrite {plugin_path} (use --force)", file=sys.stderr)
        return 1
    plugin_path.write_text(plugin_src, encoding="utf-8")

    print(f"Created platforms/{name}/")
    print(f"  - __init__.py")
    print(f"  - plugin.py  ({class_name})")
    if not args.no_core:
        print(f"  - core.py    ({register_class})")
    print()
    print("Next steps:")
    print(f"  1. Implement registration logic in platforms/{name}/")
    print("  2. Restart backend: python main.py")
    print("  3. Check discovery: GET /api/platforms?type=all")
    print(f"  4. Submit task: POST /api/tasks/register  {{\"platform\": \"{name}\", ...}}")
    print("  See docs/PLUGIN_DEVELOPMENT_GUIDE.md for details.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
