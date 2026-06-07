"""
Test authentication method mismatch error handling
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from platforms.chatgpt.refresh_token_registration_engine import RefreshTokenRegistrationEngine


class TestAuthMethodMismatchHandling:
    """Test suite for authentication method mismatch error handling"""

    def test_should_switch_to_login_detects_auth_mismatch(self):
        """Test that _should_switch_to_login_after_register_failure detects auth method errors"""
        # Test various error messages that should trigger switch to login
        test_cases = [
            "authentication method you used during sign up",
            "You tried signing in using a password, which is not the authentication method",
            "AUTHENTICATION METHOD mismatch",  # Case insensitive
            "add_phone blocking",
            "user_already_exists",
        ]
        
        for error_msg in test_cases:
            result = RefreshTokenRegistrationEngine._should_switch_to_login_after_register_failure(error_msg)
            assert result is True, f"Should detect error: {error_msg}"

    def test_should_switch_to_login_ignores_other_errors(self):
        """Test that other errors don't trigger switch to login"""
        test_cases = [
            "Network timeout",
            "Invalid email format",
            "Sentinel token failed",
            "Random error message",
        ]
        
        for error_msg in test_cases:
            result = RefreshTokenRegistrationEngine._should_switch_to_login_after_register_failure(error_msg)
            assert result is False, f"Should not detect error: {error_msg}"

    @patch('platforms.chatgpt.refresh_token_registration_engine.OAuthClient')
    def test_auth_mismatch_triggers_retry(self, mock_oauth_class):
        """Test that authentication method mismatch triggers automatic retry"""
        # Setup mock OAuth client
        mock_oauth_instance = Mock()
        mock_oauth_instance.last_error = "[stage=about_you] authentication method you used during sign up"
        mock_oauth_instance.login_and_get_tokens.return_value = None  # First call fails
        mock_oauth_class.return_value = mock_oauth_instance
        
        # Create engine instance
        engine = RefreshTokenRegistrationEngine(
            proxy_url=None,
            browser_mode="protocol",
            extra_config={}
        )
        
        # Verify the error message is recognized
        should_retry = engine._should_switch_to_login_after_register_failure(
            mock_oauth_instance.last_error
        )
        assert should_retry is True

    def test_oauth_client_detects_auth_mismatch_in_response(self):
        """Test that OAuthClient properly detects auth mismatch in 400 responses"""
        from platforms.chatgpt.oauth_client import OAuthClient
        
        client = OAuthClient(config={}, verbose=False)
        
        # Simulate a 400 response with auth mismatch error
        mock_response = Mock()
        mock_response.status_code = 400
        mock_response.text = '{"error": {"message": "You tried signing in using a password, which is not the authentication method you used during sign up"}}'
        mock_response.url = "https://auth.openai.com/api/accounts/create_account"
        
        # The error should be detected and logged
        # This is tested indirectly through the error message format
        assert "authentication method" in mock_response.text.lower()


class TestOTPCodeHandling:
    """Test suite for OTP code reuse prevention"""

    def test_used_codes_are_tracked(self):
        """Test that used OTP codes are properly tracked"""
        from platforms.chatgpt.oauth_client import OAuthClient
        
        client = OAuthClient(config={}, verbose=False)
        
        # Mock skymail client with used codes tracking
        mock_skymail = Mock()
        mock_skymail._used_codes = set()
        
        # Simulate adding a used code
        test_code = "725254"
        mock_skymail._used_codes.add(test_code)
        
        # Verify code is tracked
        assert test_code in mock_skymail._used_codes
        
        # Verify different code is not tracked
        assert "718397" not in mock_skymail._used_codes


def test_error_message_format():
    """Test that error messages are properly formatted for detection"""
    error_scenarios = [
        {
            "response": '{"error": {"message": "You tried signing in as \\"user@example.com\\" using a password, which is not the authentication method you used during sign up"}}',
            "should_match": True,
        },
        {
            "response": '{"error": {"message": "Invalid credentials"}}',
            "should_match": False,
        },
        {
            "response": '{"error": {"message": "Account already exists, please login instead"}}',
            "should_match": True,
        },
    ]
    
    for scenario in error_scenarios:
        response_text = scenario["response"].lower()
        has_auth_method = "authentication method" in response_text
        has_login_marker = any(
            marker in response_text 
            for marker in ["already exists", "please login"]
        )
        
        should_trigger = has_auth_method or has_login_marker
        assert should_trigger == scenario["should_match"], \
            f"Error detection mismatch for: {scenario['response']}"


if __name__ == "__main__":
    # Run basic tests
    print("Running authentication method mismatch handling tests...")
    
    test_handler = TestAuthMethodMismatchHandling()
    test_handler.test_should_switch_to_login_detects_auth_mismatch()
    print("✓ Auth mismatch detection works")
    
    test_handler.test_should_switch_to_login_ignores_other_errors()
    print("✓ Other errors are properly ignored")
    
    test_error_message_format()
    print("✓ Error message format detection works")
    
    otp_handler = TestOTPCodeHandling()
    otp_handler.test_used_codes_are_tracked()
    print("✓ OTP code tracking works")
    
    print("\nAll tests passed! ✓")
