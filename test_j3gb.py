"""
Test script for J3GB platform registration.

Usage:
    python test_j3gb.py --gmail <gmail_address> --app-password <app_password>

Or set the credentials in config_store / .env:
    J3GB_GMAIL_BASE_EMAIL=your@gmail.com
    J3GB_GMAIL_APP_PASSWORD=your_app_password
"""

import sys
import os
import argparse


def main():
    parser = argparse.ArgumentParser(description="Test J3GB registration")
    parser.add_argument("--gmail", required=False, default="", help="Base Gmail address")
    parser.add_argument("--app-password", required=False, default="", help="Gmail App Password")
    parser.add_argument("--headed", action="store_true", help="Run in headed mode")
    parser.add_argument("--proxy", default="", help="Proxy URL")
    args = parser.parse_args()

    gmail = args.gmail or os.getenv("J3GB_GMAIL_BASE_EMAIL", "")
    app_password = args.app_password or os.getenv("J3GB_GMAIL_APP_PASSWORD", "")

    if not gmail or not app_password:
        print("Error: Gmail address and App Password are required.")
        print("Usage: python test_j3gb.py --gmail your@gmail.com --app-password xxxx xxxx xxxx xxxx")
        print("Or set env vars: J3GB_GMAIL_BASE_EMAIL, J3GB_GMAIL_APP_PASSWORD")
        sys.exit(1)

    from core.base_platform import RegisterConfig
    from platforms.j3gb.plugin import J3gbPlatform

    config = RegisterConfig(
        executor_type="headed" if args.headed else "headless",
        captcha_solver="capsolver",
        proxy=args.proxy or None,
        extra={
            "j3gb_gmail_base_email": gmail,
            "j3gb_gmail_app_password": app_password,
        },
    )

    platform = J3gbPlatform(config=config, mailbox=None)
    platform._log_fn = lambda msg: print(msg)

    print(f"\n{'='*60}")
    print(f"Starting J3GB registration with Gmail: {gmail}")
    print(f"{'='*60}\n")

    try:
        account = platform.register(email=None, password=None)
        print(f"\n{'='*60}")
        print(f"Registration SUCCESS!")
        print(f"  Email:    {account.email}")
        print(f"  Password: {account.password}")
        print(f"  API Key:  {account.token}")
        print(f"  Username: {account.extra.get('username', '')}")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\nRegistration FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
