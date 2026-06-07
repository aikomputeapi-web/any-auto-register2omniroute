import sys
import os
import time
from typing import Optional
from core.base_platform import BasePlatform, Account, AccountStatus, RegisterConfig
from core.base_mailbox import BaseMailbox
from core.registry import register

@register
class StripePlatform(BasePlatform):
    name = "stripe"
    display_name = "Stripe"
    version = "1.0.0"
    supported_executors = ["headed"]

    def __init__(self, config: Optional[RegisterConfig] = None, mailbox: Optional[BaseMailbox] = None):
        super().__init__(config or RegisterConfig())
        self.mailbox = mailbox

    def register(self, email: str, password: Optional[str] = None) -> Account:
        extra = self.config.extra or {}
        profile = str(extra.get("profile", "pro_account_register/stripe_business_profile.txt"))
        bridge = str(extra.get("bridge", "http://localhost:3005"))
        
        old_argv = sys.argv
        sys.argv = [
            "register_stripe.py",
            "--profile", profile,
            "--bridge", bridge
        ]
        
        log = getattr(self, "_log_fn", print)
        log(f"Starting Stripe registration using profile {profile} and bridge {bridge}...")
        try:
            from pro_account_register import register_stripe
            import importlib
            importlib.reload(register_stripe)
            
            # Set the logger on the module to capture print calls
            register_stripe._log_fn = log
            
            register_stripe.main()
        except Exception as e:
            log(f"Error executing Stripe script: {e}")
            raise e
        finally:
            sys.argv = old_argv
            
        return Account(
            platform="stripe",
            email=email or "",
            password=password or "",
            status=AccountStatus.REGISTERED,
            extra={}
        )

    def check_valid(self, account: Account) -> bool:
        return True
