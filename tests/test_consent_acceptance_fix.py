"""
Test for consent acceptance fix - verifies the new GET strategy works
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platforms.chatgpt.oauth_client import OAuthClient
from unittest.mock import Mock, MagicMock, patch
import json


def test_consent_get_strategy_with_redirect():
    """Test that the new GET strategy successfully extracts code from redirect"""
    
    # Create OAuth client
    config = {
        "oauth_issuer": "https://auth.openai.com",
        "oauth_client_id": "test_client",
        "oauth_redirect_uri": "http://localhost:1455/auth/callback"
    }
    client = OAuthClient(config, verbose=True, browser_mode="protocol")
    
    # Mock session.get to simulate successful redirect with code
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "http://localhost:1455/auth/callback?code=test_auth_code_12345&state=test_state"
    mock_response.text = ""
    
    with patch.object(client.session, 'get', return_value=mock_response):
        # Call the consent fallback method
        code, state = client._consent_accept_fallback(
            consent_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            workspace_id="test-workspace-id",
            device_id="test-device-id",
            user_agent="Mozilla/5.0",
            impersonate="chrome110",
            session_data=None
        )
    
    # Verify we got the code
    assert code == "test_auth_code_12345", f"Expected code 'test_auth_code_12345', got '{code}'"
    print("✓ Test passed: GET strategy successfully extracted code from redirect URL")


def test_consent_get_strategy_with_json_response():
    """Test that the GET strategy handles JSON response with continue_url"""
    
    config = {
        "oauth_issuer": "https://auth.openai.com",
        "oauth_client_id": "test_client",
        "oauth_redirect_uri": "http://localhost:1455/auth/callback"
    }
    client = OAuthClient(config, verbose=True, browser_mode="protocol")
    
    # Mock session.get to return JSON with continue_url
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
    mock_response.json.return_value = {
        "continue_url": "http://localhost:1455/auth/callback?code=json_code_67890"
    }
    
    # Mock _oauth_follow_for_code to return the code
    with patch.object(client.session, 'get', return_value=mock_response):
        with patch.object(client, '_oauth_follow_for_code', return_value=("json_code_67890", "http://localhost:1455/auth/callback")):
            code, state = client._consent_accept_fallback(
                consent_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
                workspace_id="test-workspace-id",
                device_id="test-device-id",
                user_agent="Mozilla/5.0",
                impersonate="chrome110",
                session_data=None
            )
    
    assert code == "json_code_67890", f"Expected code 'json_code_67890', got '{code}'"
    print("✓ Test passed: GET strategy successfully handled JSON response with continue_url")


def test_consent_get_strategy_with_meta_refresh():
    """Test that the GET strategy extracts code from HTML meta refresh"""
    
    config = {
        "oauth_issuer": "https://auth.openai.com",
        "oauth_client_id": "test_client",
        "oauth_redirect_uri": "http://localhost:1455/auth/callback"
    }
    client = OAuthClient(config, verbose=True, browser_mode="protocol")
    
    # Mock session.get to return HTML with meta refresh
    html_content = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta http-equiv="refresh" content="0; url=http://localhost:1455/auth/callback?code=meta_refresh_code_abc123">
    </head>
    <body>Redirecting...</body>
    </html>
    '''
    
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
    mock_response.text = html_content
    mock_response.json.side_effect = ValueError("Not JSON")
    
    with patch.object(client.session, 'get', return_value=mock_response):
        code, state = client._consent_accept_fallback(
            consent_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            workspace_id="test-workspace-id",
            device_id="test-device-id",
            user_agent="Mozilla/5.0",
            impersonate="chrome110",
            session_data=None
        )
    
    assert code == "meta_refresh_code_abc123", f"Expected code 'meta_refresh_code_abc123', got '{code}'"
    print("✓ Test passed: GET strategy successfully extracted code from HTML meta refresh")


def test_consent_get_strategy_with_js_redirect():
    """Test that the GET strategy extracts code from JavaScript window.location redirect"""
    
    config = {
        "oauth_issuer": "https://auth.openai.com",
        "oauth_client_id": "test_client",
        "oauth_redirect_uri": "http://localhost:1455/auth/callback"
    }
    client = OAuthClient(config, verbose=True, browser_mode="protocol")
    
    # Mock session.get to return HTML with JS redirect
    html_content = '''
    <!DOCTYPE html>
    <html>
    <head>
        <script>
            window.location.href = "http://localhost:1455/auth/callback?code=js_redirect_code_xyz789";
        </script>
    </head>
    <body>Redirecting...</body>
    </html>
    '''
    
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.url = "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"
    mock_response.text = html_content
    mock_response.json.side_effect = ValueError("Not JSON")
    
    with patch.object(client.session, 'get', return_value=mock_response):
        code, state = client._consent_accept_fallback(
            consent_url="https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
            workspace_id="test-workspace-id",
            device_id="test-device-id",
            user_agent="Mozilla/5.0",
            impersonate="chrome110",
            session_data=None
        )
    
    assert code == "js_redirect_code_xyz789", f"Expected code 'js_redirect_code_xyz789', got '{code}'"
    print("✓ Test passed: GET strategy successfully extracted code from JavaScript redirect")


if __name__ == "__main__":
    print("Testing consent acceptance fix...\n")
    
    try:
        test_consent_get_strategy_with_redirect()
        test_consent_get_strategy_with_json_response()
        test_consent_get_strategy_with_meta_refresh()
        test_consent_get_strategy_with_js_redirect()
        
        print("\n" + "="*60)
        print("✓ All tests passed!")
        print("="*60)
        print("\nThe new GET strategy for consent acceptance is working correctly.")
        print("It can handle:")
        print("  1. Direct redirects with code in URL")
        print("  2. JSON responses with continue_url")
        print("  3. HTML meta refresh redirects")
        print("  4. JavaScript window.location redirects")
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
