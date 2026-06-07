import unittest
from unittest import mock
from core.base_mailbox import MailboxAccount
from core.base_platform import RegisterConfig, AccountStatus
from platforms.cerebras.plugin import CerebrasPlatform


class _BlankMailbox:
    def get_email(self):
        return MailboxAccount(email="test@example.com", account_id="test-mailbox")

    def get_current_ids(self, account):
        return set()

    def wait_for_code(self, *args, **kwargs):
        return "123456"


class CerebrasPlatformTests(unittest.TestCase):
    @mock.patch("platforms.cerebras.core.CerebrasRegister")
    def test_cerebras_registration_success(self, mock_register_cls):
        # Setup mock register instance
        mock_reg_instance = mock.Mock()
        mock_reg_instance.register.return_value = (
            True,
            {
                "email": "test@example.com",
                "password": "mypassword",
                "api_key": "csk-mocked-api-key-12345",
            },
        )
        mock_register_cls.return_value = mock_reg_instance

        # Initialize platform
        platform = CerebrasPlatform(
            config=RegisterConfig(executor_type="headed", proxy="http://127.0.0.1:8888"),
            mailbox=_BlankMailbox(),
        )

        # Execute registration
        account = platform.register(email="test@example.com")

        # Verify mock initialization
        mock_register_cls.assert_called_once()
        _, kwargs = mock_register_cls.call_args
        self.assertEqual(kwargs.get("proxy"), "http://127.0.0.1:8888")
        self.assertEqual(kwargs.get("headless"), False)

        # Verify register call
        mock_reg_instance.register.assert_called_once()
        _, reg_kwargs = mock_reg_instance.register.call_args
        self.assertEqual(reg_kwargs.get("email"), "test@example.com")
        self.assertTrue(callable(reg_kwargs.get("otp_callback")))

        # Check returned account properties
        self.assertEqual(account.platform, "cerebras")
        self.assertEqual(account.email, "test@example.com")
        self.assertEqual(account.password, "mypassword")
        self.assertEqual(account.token, "csk-mocked-api-key-12345")
        self.assertEqual(account.status, AccountStatus.REGISTERED)
        self.assertEqual(account.extra.get("api_key"), "csk-mocked-api-key-12345")

    @mock.patch("platforms.cerebras.core.CerebrasRegister")
    def test_cerebras_registration_failure(self, mock_register_cls):
        # Setup mock register instance to fail
        mock_reg_instance = mock.Mock()
        mock_reg_instance.register.return_value = (False, {"error": "Captcha failed"})
        mock_register_cls.return_value = mock_reg_instance

        platform = CerebrasPlatform(
            config=RegisterConfig(executor_type="headless"),
            mailbox=None,
        )

        with self.assertRaises(RuntimeError) as ctx:
            platform.register(email="test@example.com")

        self.assertIn("Cerebras registration failed: Captcha failed", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
