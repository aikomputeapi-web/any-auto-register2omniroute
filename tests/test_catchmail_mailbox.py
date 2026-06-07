"""Test CatchMail.io mailbox integration"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import create_mailbox


def test_catchmail_creation():
    """Test that CatchMail mailbox can be created"""
    print("Testing CatchMail mailbox creation...")
    
    try:
        mailbox = create_mailbox("catchmail", extra={
            "catchmail_api_url": "https://catchmail.io"
        })
        print(f"SUCCESS: CatchMail mailbox created successfully: {type(mailbox).__name__}")
        return True
    except Exception as e:
        print(f"FAILURE: Failed to create CatchMail mailbox: {e}")
        return False


def test_catchmail_get_email():
    """Test getting an email from CatchMail"""
    print("\nTesting CatchMail email generation...")
    
    try:
        mailbox = create_mailbox("catchmail")
        account = mailbox.get_email()
        print(f"SUCCESS: Generated email: {account.email}")
        print(f"  Account ID: {account.account_id}")
        return True
    except Exception as e:
        print(f"FAILURE: Failed to generate email: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_catchmail_wait_for_code_mock():
    """Test wait_for_code with mocked API responses"""
    print("\nTesting CatchMail wait_for_code with mock...")
    from unittest.mock import patch, MagicMock

    try:
        mailbox = create_mailbox("catchmail")
        account = mailbox.get_email()

        # Mock list response and detail response
        mock_list_resp = MagicMock()
        mock_list_resp.status_code = 200
        mock_list_resp.json.return_value = [
            {"id": "msg_123", "subject": "OpenAI verification code"}
        ]

        mock_detail_resp = MagicMock()
        mock_detail_resp.status_code = 200
        mock_detail_resp.json.return_value = {
            "id": "msg_123",
            "subject": "OpenAI verification code",
            "text": "Your OpenAI verification code is 123456. Enter this code to verify your email."
        }

        # Side effect for requests.get to return appropriate mock depending on URL
        def get_side_effect(url, *args, **kwargs):
            if "/api/v1/mailbox" in url:
                return mock_list_resp
            elif "/api/v1/message/msg_123" in url:
                return mock_detail_resp
            # Fallback
            mock_err = MagicMock()
            mock_err.status_code = 404
            return mock_err

        with patch("requests.get", side_effect=get_side_effect):
            code = mailbox.wait_for_code(
                account, 
                keyword="OpenAI", 
                timeout=10, 
                code_pattern=r"\b\d{6}\b"
            )
            
            if code == "123456":
                print("SUCCESS: Successfully retrieved and parsed OTP using mocked CatchMail detail endpoint!")
                return True
            else:
                print(f"FAILURE: Expected code '123456', got '{code}'")
                return False
    except Exception as e:
        print(f"FAILURE: Exception during mock test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("CatchMail.io Integration Test")
    print("=" * 60)
    
    results = []
    results.append(test_catchmail_creation())
    
    # Only test email generation if creation succeeded
    if results[0]:
        results.append(test_catchmail_get_email())
        results.append(test_catchmail_wait_for_code_mock())
    
    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)
    
    sys.exit(0 if all(results) else 1)
