# Authentication Method Mismatch Error Fix

## Problem Description

The registration system was failing with the following error:

```
[stage=about_you] about_you Submission failed: 400 - {
  "error": {
    "message": "You tried signing in as \"email@domain.com\" using a password, 
    which is not the authentication method you used during sign up..."
  }
}
```

## Root Cause

The issue occurs in the two-phase registration flow:

1. **Phase 1 (Registration)**: Uses passwordless OTP authentication to advance to `about_you` stage
2. **Phase 2 (OAuth Continuation)**: Attempts to submit `about_you` while reusing the registration session

OpenAI's backend detects that:
- The account was initially created using **passwordless OTP** authentication
- The OAuth continuation session has **password context** from the session reuse
- This mismatch triggers a 400 error rejecting the `about_you` submission

## Solution Implemented

### 1. Enhanced Error Detection (`oauth_client.py`)

Added specific handling for authentication method mismatch errors in the `_submit_about_you_create_account` method:

```python
# Handle authentication method mismatch error
if r.status_code == 400:
    response_text = r.text or ""
    if "authentication method you used during sign up" in response_text.lower():
        self._log(
            "about_you submission rejected: authentication method mismatch detected",
            "warning"
        )
        self._log(
            "This typically occurs when registration used passwordless OTP but OAuth session has password context",
            "warning"
        )
        # Set error and return None to trigger retry logic
        self._set_error(f"[stage=about_you] about_you Submission failed: {r.status_code} - {response_text[:180]}")
        return None
```

### 2. Updated Failure Detection (`refresh_token_registration_engine.py`)

Modified `_should_switch_to_login_after_register_failure` to recognize authentication method errors:

```python
@staticmethod
def _should_switch_to_login_after_register_failure(message: str) -> bool:
    text = str(message or "").lower()
    markers = (
        "user_already_exists",
        "account already exists",
        "please login instead",
        "add_phone",
        "add-phone",
        "authentication method you used during sign up",  # NEW
        "authentication method",  # NEW
    )
    return any(marker in text for marker in markers)
```

### 3. Automatic Retry with Fresh Session (`refresh_token_registration_engine.py`)

Added retry logic that creates a fresh OAuth session when authentication method mismatch is detected:

```python
if not tokens:
    last_error = oauth_client.last_error or "OAuth Login state machine failed"
    
    # Handle authentication method mismatch - retry with fresh session
    if "authentication method" in last_error.lower() and use_continued_session:
        self._log(
            "OAuth about_you submission failed due to authentication method mismatch",
            "warning",
        )
        self._log(
            "Retrying with fresh OAuth session (passwordless flow)...",
            "warning",
        )
        # Create a new OAuth client with fresh session
        oauth_client = self._build_oauth_client()
        # ... configure and retry with force_new_browser=True
        tokens = oauth_client.login_and_get_tokens(
            result.email,
            self.password,
            device_id="",  # Fresh device ID
            # ... other params
            force_new_browser=True,  # Force fresh session
            prefer_passwordless_login=True,  # Use passwordless
            complete_about_you_if_needed=True,
            login_source="post_register_auth_mismatch_retry",
        )
```

## How It Works Now

1. **Registration Phase**: Advances to `about_you` using passwordless OTP (unchanged)
2. **OAuth Continuation**: Attempts to submit `about_you` with reused session
3. **Error Detection**: If authentication method mismatch occurs, error is detected
4. **Automatic Retry**: System automatically retries with a **fresh OAuth session**
5. **Fresh Flow**: New session uses passwordless OTP from the start, avoiding mismatch
6. **Success**: Account creation completes successfully

## Benefits

- **Automatic Recovery**: No manual intervention needed when mismatch occurs
- **Graceful Degradation**: Falls back to fresh session automatically
- **Better Logging**: Clear warnings explain what happened and why
- **Maintains Success Rate**: Converts failures into successes through intelligent retry

## Testing Recommendations

1. Monitor logs for "authentication method mismatch" warnings
2. Verify that retries succeed with "post_register_auth_mismatch_retry" source
3. Check that OTP codes are not reused (existing logic handles this)
4. Confirm registration success rate improves

## Related Issues

- OTP code reuse is already handled by existing `_used_codes` tracking
- Phone verification blocking has separate retry logic (unchanged)
- The fix is specific to the `about_you` submission phase
