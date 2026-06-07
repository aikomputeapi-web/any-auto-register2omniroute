# CatchMail.io Integration

## Overview

CatchMail.io is a free temporary email service that has been integrated into the any-auto-register system. This integration allows you to use CatchMail.io as an email provider for account registration.

## Features

- **Free temporary email generation**: No API key required
- **Automatic email polling**: Polls for new messages every 3 seconds
- **Verification code extraction**: Automatically extracts 6-digit verification codes from emails
- **Proxy support**: Can be used with proxy servers
- **Keyword filtering**: Filter emails by keyword before extracting codes

## Configuration

### Basic Usage

To use CatchMail.io, simply select "catchmail" as your email provider in the registration settings.

### Configuration Options

| Option | Description | Default | Required |
|--------|-------------|---------|----------|
| `catchmail_api_url` | CatchMail.io API base URL | `https://api.catchmail.io` | No |

### Example Configuration

```python
from core.base_mailbox import create_mailbox

# Create a CatchMail mailbox
mailbox = create_mailbox("catchmail", extra={
    "catchmail_api_url": "https://api.catchmail.io"  # Optional, uses default if not specified
})

# Generate a temporary email (randomly generated @catchmail.io address)
account = mailbox.get_email()
print(f"Email: {account.email}")

# Wait for verification code
code = mailbox.wait_for_code(
    account=account,
    keyword="verification",  # Optional: filter by keyword
    timeout=120,  # Wait up to 2 minutes
    code_pattern=r"\d{6}"  # Optional: custom regex pattern
)
print(f"Verification code: {code}")
```

## API Endpoints Used

The integration uses the following CatchMail.io API endpoint:

1. **GET /api/v1/mailbox?address={email}** - List messages for a specific email address

Note: CatchMail.io accepts any email address @catchmail.io without pre-registration. The system generates a random address locally.

## How It Works

1. **Email Generation**: The system generates a random email address @catchmail.io locally (no API call needed)
2. **Message Polling**: The system polls `GET /api/v1/mailbox?address={email}` every 3 seconds to check for new messages
3. **Code Extraction**: When a new message arrives, the system:
   - Decodes the message content (handles HTML entities, quoted-printable encoding, etc.)
   - Removes email addresses to avoid false matches
   - Searches for verification codes using regex patterns
   - Returns the first valid code found

## Verification Code Extraction

The system uses multiple regex patterns to extract verification codes:

1. **Semantic patterns**: Looks for codes near keywords like "verification code", "OTP", "security code", etc.
2. **Generic patterns**: Looks for 6-digit numbers with word boundaries
3. **Custom patterns**: You can provide your own regex pattern via the `code_pattern` parameter

## Error Handling

The integration handles the following error scenarios:

- **API unavailable**: Returns empty results and continues polling
- **Invalid response**: Logs error and continues polling
- **Timeout**: Raises `TimeoutError` after the specified timeout period
- **Network errors**: Automatically retries on next poll interval

## Comparison with Other Providers

| Feature | CatchMail | TempMail.lol | MoeMail |
|---------|-----------|--------------|---------|
| API Key Required | No | No | Optional |
| Registration Required | No | No | Yes |
| Proxy Support | Yes | Yes | Yes |
| Poll Interval | 3s | 3s | 3s |
| Free Tier | Yes | Yes | Yes |

## Troubleshooting

### Issue: "CatchMail Failed to create mailbox"

**Possible causes:**
- CatchMail.io API is down
- Network connectivity issues
- Proxy configuration problems

**Solutions:**
1. Check if catchmail.io is accessible from your network
2. Verify proxy settings if using a proxy
3. Try using a different email provider temporarily

### Issue: "Timeout waiting for verification code"

**Possible causes:**
- Email not received within timeout period
- Verification email went to spam/junk
- Email service delayed

**Solutions:**
1. Increase the timeout value
2. Check if the email was actually sent by the service
3. Try generating a new email address

## Integration in Frontend

To add CatchMail.io to the frontend email provider dropdown:

1. Edit `frontend/src/pages/RegisterTask.tsx` or equivalent
2. Add to the email provider options:

```typescript
{
  value: "catchmail",
  label: "CatchMail.io"
}
```

3. No additional configuration fields are required (API URL is optional)

## Testing

Run the test suite to verify the integration:

```bash
python tests/test_catchmail_mailbox.py
```

## Notes

- CatchMail.io is a free service and may have rate limits
- Temporary emails typically expire after a certain period
- For production use, consider using a paid email service with guaranteed uptime
- The integration follows the same pattern as other mailbox providers in the system

## Future Enhancements

Potential improvements for the CatchMail.io integration:

- [ ] Add support for custom domains (if CatchMail.io adds this feature)
- [ ] Implement email content caching to reduce API calls
- [ ] Add metrics/logging for API response times
- [ ] Support for webhook-based email notifications (if available)
- [ ] Add retry logic with exponential backoff for API failures
