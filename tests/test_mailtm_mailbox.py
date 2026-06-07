"""Test Mail.tm mailbox integration"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.base_mailbox import create_mailbox


def test_mailtm_creation():
    """Test that Mail.tm mailbox can be created"""
    print("Testing Mail.tm mailbox creation...")
    
    try:
        mailbox = create_mailbox("mailtm", extra={
            "mailtm_api_url": "https://api.mail.tm"
        })
        print(f"SUCCESS: Mail.tm mailbox created successfully: {type(mailbox).__name__}")
        return True
    except Exception as e:
        print(f"FAILURE: Failed to create Mail.tm mailbox: {e}")
        return False


def test_mailtm_get_email():
    """Test getting an email from Mail.tm"""
    print("\nTesting Mail.tm email generation...")
    
    try:
        mailbox = create_mailbox("mailtm")
        account = mailbox.get_email()
        print(f"SUCCESS: Generated email: {account.email}")
        print(f"  Account ID: {account.account_id}")
        print(f"  Password: {account.extra.get('password')}")
        print(f"  Token: {account.extra.get('token')[:20]}...")
        
        # Test retrieving messages (should be empty but shouldn't error)
        msgs = mailbox._list_messages(account)
        print(f"SUCCESS: Successfully listed messages (found {len(msgs)})")
        
        return True
    except Exception as e:
        print(f"FAILURE: Failed to generate email or list messages: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Mail.tm Integration Test")
    print("=" * 60)
    
    results = []
    results.append(test_mailtm_creation())
    
    # Only test email generation if creation succeeded
    if results[0]:
        results.append(test_mailtm_get_email())
    
    print("\n" + "=" * 60)
    print(f"Test Results: {sum(results)}/{len(results)} passed")
    print("=" * 60)
    
    sys.exit(0 if all(results) else 1)
