import unittest
from unittest import mock
from core.db import AccountModel
from services.omniroute_sync import build_omniroute_payload, upload_to_omniroute


class OmniRouteSyncTests(unittest.TestCase):
    def test_build_payload_chatgpt(self):
        account = AccountModel(
            platform="chatgpt",
            email="chat@example.com",
            password="pwd",
            token="old-token",
            status="registered",
        )
        account.set_extra({
            "access_token": "chat-access",
            "refresh_token": "chat-refresh",
            "id_token": "chat-id-token",
            "client_id": "custom-client-id"
        })
        
        payload = build_omniroute_payload(account)
        self.assertEqual(payload["provider"], "codex")
        self.assertEqual(payload["authType"], "oauth")
        self.assertEqual(payload["email"], "chat@example.com")
        self.assertEqual(payload["accessToken"], "chat-access")
        self.assertEqual(payload["refreshToken"], "chat-refresh")
        self.assertEqual(payload["idToken"], "chat-id-token")
        self.assertEqual(payload["providerSpecificData"]["clientId"], "custom-client-id")

    def test_build_payload_kiro(self):
        account = AccountModel(
            platform="kiro",
            email="kiro@example.com",
            password="pwd",
            token="kiro-token",
            status="registered",
        )
        account.set_extra({
            "access_token": "kiro-access",
            "refresh_token": "kiro-refresh",
            "clientId": "kiro-client",
            "clientSecret": "kiro-secret",
            "region": "eu-west-1",
            "provider": "BuilderId"
        })
        
        payload = build_omniroute_payload(account)
        self.assertEqual(payload["provider"], "kiro")
        self.assertEqual(payload["authType"], "oauth")
        self.assertEqual(payload["accessToken"], "kiro-access")
        self.assertEqual(payload["refreshToken"], "kiro-refresh")
        self.assertEqual(payload["providerSpecificData"]["clientId"], "kiro-client")
        self.assertEqual(payload["providerSpecificData"]["clientSecret"], "kiro-secret")
        self.assertEqual(payload["providerSpecificData"]["region"], "eu-west-1")

    def test_build_payload_grok(self):
        account = AccountModel(
            platform="grok",
            email="grok@example.com",
            password="pwd",
            status="registered",
        )
        account.set_extra({
            "sso": "grok-sso-token",
            "sso_rw": "grok-sso-rw"
        })
        
        payload = build_omniroute_payload(account)
        self.assertEqual(payload["provider"], "grok")
        self.assertEqual(payload["authType"], "oauth")
        self.assertEqual(payload["accessToken"], "grok-sso-token")
        self.assertEqual(payload["refreshToken"], "grok-sso-rw")

    def test_build_payload_tavily(self):
        account = AccountModel(
            platform="tavily",
            email="tavily@example.com",
            password="pwd",
            status="registered",
        )
        account.set_extra({
            "api_key": "tvly-key"
        })
        
        payload = build_omniroute_payload(account)
        self.assertEqual(payload["provider"], "tavily")
        self.assertEqual(payload["authType"], "apikey")
        self.assertEqual(payload["apiKey"], "tvly-key")

    def test_build_payload_cloudflare(self):
        account = AccountModel(
            platform="cloudflare",
            email="cf@example.com",
            password="pwd",
            status="registered",
        )
        account.set_extra({
            "api_token": "cf-token"
        })
        
        payload = build_omniroute_payload(account)
        self.assertEqual(payload["provider"], "cloudflare")
        self.assertEqual(payload["authType"], "apikey")
        self.assertEqual(payload["apiKey"], "cf-token")

    @mock.patch("services.omniroute_sync.cffi_requests")
    def test_upload_to_omniroute_success(self, mock_requests):
        account = AccountModel(
            platform="tavily",
            email="tavily@example.com",
            password="pwd",
            status="registered",
        )
        account.set_extra({"api_key": "tvly-key"})

        # Mock login response
        mock_login_resp = mock.Mock()
        mock_login_resp.status_code = 200
        mock_login_resp.cookies = {"auth_token": "cookie-123"}
        
        # Mock providers response
        mock_provider_resp = mock.Mock()
        mock_provider_resp.status_code = 201
        
        mock_requests.post.side_effect = [mock_login_resp, mock_provider_resp]
        
        ok, msg = upload_to_omniroute(
            account,
            api_url="https://admin.aikompute.com",
            admin_password="admin-pwd"
        )
        
        self.assertTrue(ok)
        self.assertEqual(msg, "Upload to OmniRoute successful")
        self.assertEqual(mock_requests.post.call_count, 2)
        
        # Verify login call
        login_args = mock_requests.post.call_args_list[0]
        self.assertEqual(login_args[0][0], "https://admin.aikompute.com/api/auth/login")
        self.assertEqual(login_args[1]["json"], {"password": "admin-pwd"})
        
        # Verify provider create call
        provider_args = mock_requests.post.call_args_list[1]
        self.assertEqual(provider_args[0][0], "https://admin.aikompute.com/api/providers")
        self.assertEqual(provider_args[1]["cookies"], {"auth_token": "cookie-123"})
        self.assertEqual(provider_args[1]["json"]["provider"], "tavily")
        self.assertEqual(provider_args[1]["json"]["apiKey"], "tvly-key")

    @mock.patch("services.omniroute_sync.cffi_requests")
    def test_find_existing_connection(self, mock_requests):
        from services.omniroute_sync import _find_existing_connection
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "connections": [
                {"id": "conn-1", "provider": "kiro", "email": "kiro1@example.com"},
                {"id": "conn-2", "provider": "kiro", "email": "kiro2@example.com"},
                {"id": "conn-3", "provider": "chatgpt", "email": "chat@example.com"}
            ]
        }
        mock_requests.get.return_value = mock_resp
        
        # Test without email
        conn_id = _find_existing_connection("http://localhost", {}, "kiro")
        self.assertEqual(conn_id, "conn-1")
        
        # Test with matching email
        conn_id = _find_existing_connection("http://localhost", {}, "kiro", "kiro2@example.com")
        self.assertEqual(conn_id, "conn-2")
        
        # Test with non-matching email
        conn_id = _find_existing_connection("http://localhost", {}, "kiro", "kiro3@example.com")
        self.assertIsNone(conn_id)

    @mock.patch("services.omniroute_sync.cffi_requests")
    @mock.patch("playwright.sync_api.sync_playwright")
    def test_kiro_device_code_flow(self, mock_playwright, mock_requests):
        from services.omniroute_sync import _kiro_device_code_flow
        
        # Setup account
        account = AccountModel(
            platform="kiro",
            email="kiro@example.com",
            password="pwd",
            status="registered",
        )
        account.set_extra({
            "portalCookies": [{"name": "foo", "value": "bar"}]
        })
        
        # Mock device code response
        dc_resp = mock.Mock()
        dc_resp.status_code = 200
        dc_resp.json.return_value = {
            "device_code": "dev-123",
            "verification_uri": "http://verify",
            "_clientId": "cli-123",
            "_clientSecret": "sec-123",
            "_region": "us-east-1"
        }
        
        # Mock poll response (success)
        poll_resp = mock.Mock()
        poll_resp.status_code = 200
        poll_resp.json.return_value = {
            "success": True,
            "connectionId": "conn-created"
        }
        
        mock_requests.get.return_value = dc_resp
        mock_requests.post.return_value = poll_resp
        
        # Mock Playwright to avoid launching a browser in unittest
        mock_pw_context = mock.Mock()
        mock_playwright.return_value.__enter__.return_value.chromium.launch.return_value.new_context.return_value = mock_pw_context
        
        ok, msg = _kiro_device_code_flow("http://localhost", {}, account)
        
        self.assertTrue(ok)
        self.assertIn("conn-created", msg)
        
        # Check that post was called with extraData
        mock_requests.post.assert_called_once()
        post_kwargs = mock_requests.post.call_args[1]
        self.assertEqual(post_kwargs["json"]["extraData"]["_clientId"], "cli-123")
        self.assertEqual(post_kwargs["json"]["extraData"]["_clientSecret"], "sec-123")
        self.assertEqual(post_kwargs["json"]["extraData"]["_region"], "us-east-1")


if __name__ == "__main__":
    unittest.main()
