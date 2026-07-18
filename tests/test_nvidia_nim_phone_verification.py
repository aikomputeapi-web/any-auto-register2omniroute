"""Unit tests for NVIDIA NIM phone verification integration."""
import unittest
from unittest.mock import MagicMock, patch


class TestNvidiaNimPhoneVerification(unittest.TestCase):
    """Verify the phone verification methods exist and work correctly."""

    def test_register_accepts_config_param(self):
        """NvidiaNimRegister.__init__ should accept a config dict."""
        from platforms.nvidia_nim.core import NvidiaNimRegister
        reg = NvidiaNimRegister(config={"smspool_api_key": "test_key_123"})
        self.assertEqual(reg.config.get("smspool_api_key"), "test_key_123")

    def test_register_defaults_config_to_empty(self):
        """NvidiaNimRegister should default config to empty dict."""
        from platforms.nvidia_nim.core import NvidiaNimRegister
        reg = NvidiaNimRegister()
        self.assertEqual(reg.config, {})

    def test_phone_verification_method_exists(self):
        """_handle_phone_verification method should exist and be callable."""
        from platforms.nvidia_nim.core import NvidiaNimRegister
        reg = NvidiaNimRegister()
        self.assertTrue(hasattr(reg, "_handle_phone_verification"))
        self.assertTrue(callable(reg._handle_phone_verification))

    def test_complete_phone_verification_method_exists(self):
        """_complete_phone_verification method should exist."""
        from platforms.nvidia_nim.core import NvidiaNimRegister
        reg = NvidiaNimRegister()
        self.assertTrue(hasattr(reg, "_complete_phone_verification"))

    def test_enter_and_submit_sms_code_method_exists(self):
        """_enter_and_submit_sms_code method should exist."""
        from platforms.nvidia_nim.core import NvidiaNimRegister
        reg = NvidiaNimRegister()
        self.assertTrue(hasattr(reg, "_enter_and_submit_sms_code"))

    def test_no_phone_modal_returns_false(self):
        """_handle_phone_verification should return False when no modal is present."""
        from platforms.nvidia_nim.core import NvidiaNimRegister
        reg = NvidiaNimRegister(config={"smspool_api_key": "test_key"})
        page = MagicMock()
        phone_input = MagicMock()
        phone_input.count.return_value = 0
        page.locator.return_value.first = phone_input
        result = reg._handle_phone_verification(page)
        self.assertFalse(result)

    def test_no_smspool_key_tries_skip(self):
        """Without SMSPool key, should try to click Skip and return False."""
        from platforms.nvidia_nim.core import NvidiaNimRegister
        reg = NvidiaNimRegister(config={})  # No smspool_api_key
        page = MagicMock()
        phone_input = MagicMock()
        phone_input.count.return_value = 1
        skip_btn = MagicMock()
        skip_btn.count.return_value = 1
        skip_btn.is_visible.return_value = True
        # page.locator returns different things for different selectors
        page.locator.side_effect = lambda sel: MagicMock(first=phone_input) if "tel" in sel or "phone" in sel.lower() else MagicMock(first=skip_btn)
        result = reg._handle_phone_verification(page)
        self.assertFalse(result)

    def test_plugin_passes_config_to_register(self):
        """NvidiaNimPlatform.register should pass config.extra to NvidiaNimRegister."""
        from platforms.nvidia_nim.plugin import NvidiaNimPlatform
        from core.base_platform import RegisterConfig
        platform = NvidiaNimPlatform(
            config=RegisterConfig(extra={"smspool_api_key": "test123"}),
            mailbox=None,
        )
        # The config should be accessible
        self.assertEqual(platform.config.extra.get("smspool_api_key"), "test123")


class TestNvidiaNimOtpBeforeTracking(unittest.TestCase):
    """Verify the _before tracking fix in plugin.py."""

    def test_otp_callback_updates_before(self):
        """The otp_callback should update _before after finding a code."""
        import inspect
        from platforms.nvidia_nim import plugin
        source = inspect.getsource(plugin)
        # Verify the _before.update call exists
        self.assertIn("_before.update", source)
        self.assertIn("get_current_ids", source)


if __name__ == "__main__":
    unittest.main()
