import sys
import os

# Add root folder to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.proxy_utils import build_playwright_proxy_config, resolve_us_profile

def test_parsing():
    print("Testing build_playwright_proxy_config parsing...")
    proxy_str = "http://JZtu:lJXk@5.78.106.79:47168"
    config = build_playwright_proxy_config(proxy_str)
    print(f"Parsed config: {config}")
    assert config == {
        "server": "http://5.78.106.79:47168",
        "bypass": "localhost,127.0.0.1",
        "username": "JZtu",
        "password": "lJXk"
    }, f"Unexpected parsed config: {config}"
    print("Parsing test passed!")

def test_resolve_us_profile():
    print("\nTesting resolve_us_profile...")
    
    # 1. Test without proxy (fallback case)
    print("Testing resolve_us_profile without proxy (fallback)...")
    profile = resolve_us_profile(None)
    print(f"No-proxy profile: {profile}")
    assert profile["locale"] == "en-US"
    assert profile["timezone"] in [
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Phoenix",
    ]
    assert isinstance(profile["latitude"], float)
    assert isinstance(profile["longitude"], float)
    print("No-proxy test passed!")
    
    # 2. Test with proxy (active geo-lookup case)
    proxy_str = "http://JZtu:lJXk@5.78.106.79:47168"
    print(f"Testing resolve_us_profile with proxy: {proxy_str} ...")
    profile = resolve_us_profile(proxy_str)
    print(f"Proxy-resolved profile: {profile}")
    assert profile["locale"] == "en-US"
    assert isinstance(profile["timezone"], str)
    assert isinstance(profile["latitude"], float)
    assert isinstance(profile["longitude"], float)
    print("Proxy test passed!")

def test_imports():
    print("\nTesting imports of platform modules...")
    modules = [
        "platforms.kiro.core",
        "platforms.nvidia_nim.core",
        "platforms.mistral.core",
        "platforms.cloudflare.core",
        "platforms.grok.core",
        "platforms.openrouter.core",
        "platforms.chatgpt.sentinel_batch",
        "platforms.chatgpt.sentinel_browser",
        "core.executors.playwright",
    ]
    for mod in modules:
        try:
            __import__(mod)
            print(f"  [OK] {mod} imported successfully.")
        except Exception as e:
            print(f"  [FAIL] {mod} failed to import: {e}")
            raise e

if __name__ == "__main__":
    test_parsing()
    test_resolve_us_profile()
    test_imports()
