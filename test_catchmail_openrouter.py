"""Test script to check CatchMail emails for OpenRouter"""

import time
import requests

def test_catchmail_messages(email: str):
    """Check what messages are in the CatchMail inbox"""
    api_url = "https://api.catchmail.io"
    
    print(f"\nChecking messages for: {email}")
    print("=" * 60)
    
    try:
        response = requests.get(
            f"{api_url}/api/v1/mailbox",
            params={"address": email},
            headers={"accept": "application/json"},
            timeout=10,
        )
        
        print(f"Status Code: {response.status_code}")
        
        if response.status_code >= 400:
            print(f"Error: {response.text}")
            return
            
        data = response.json()
        
        # Handle different response formats
        if isinstance(data, list):
            messages = data
        else:
            messages = data.get("messages") or data.get("emails") or []
        
        print(f"Found {len(messages)} message(s)\n")
        
        for i, msg in enumerate(messages, 1):
            print(f"Message {i}:")
            print(f"  ID: {msg.get('id') or msg.get('messageId')}")
            print(f"  From: {msg.get('from')}")
            print(f"  Subject: {msg.get('subject')}")
            print(f"  Date: {msg.get('date') or msg.get('createdAt')}")
            
            # Show body/content
            body = msg.get('text') or msg.get('body') or msg.get('html') or msg.get('content') or ''
            if body:
                # Show first 500 chars
                print(f"  Body preview: {body[:500]}...")
            print()
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Test with the email from your log
    email = "johngarcia@catchmail.io"
    
    print("Waiting 10 seconds for emails to arrive...")
    time.sleep(10)
    
    test_catchmail_messages(email)
    
    print("\nWaiting another 30 seconds...")
    time.sleep(30)
    
    test_catchmail_messages(email)
