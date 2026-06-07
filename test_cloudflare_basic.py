"""Test Cloudflare registration"""
import sys
sys.path.insert(0, "c:\\Users\\Administrator\\coding\\any-auto-register")

from core.registry import load_all, get
from core.base_platform import RegisterConfig

# Load all platforms
load_all()

# Get Cloudflare platform
CloudflarePlatform = get("cloudflare")
print(f"✓ Cloudflare platform loaded: {CloudflarePlatform.display_name}")
print(f"✓ Supported executors: {CloudflarePlatform.supported_executors}")

# Create instance
config = RegisterConfig(executor_type="headed")
platform = CloudflarePlatform(config=config)
print(f"✓ Platform instance created with executor: {platform.config.executor_type}")

print("\n✓ All basic checks passed!")
print("\nNext: Test with actual email and mailbox")
