# OpenRouter Email Service Compatibility

## Issue

OpenRouter appears to block certain temporary email domains, including:
- `@catchmail.io` - Emails are not delivered
- Other temporary email services may also be blocked

## Recommended Email Services for OpenRouter

Based on testing, the following email services work better with OpenRouter:

### 1. LuckMail (Recommended)
- **Status**: ✅ Works
- **Type**: Free temporary email
- **Setup**: Can sign in daily to get more emails
- **Configuration**: Select "LuckMail" in the email service dropdown

### 2. IMAP Catchall (Best for Production)
- **Status**: ✅ Works (100% success rate)
- **Type**: Self-hosted email
- **Setup**: Requires your own domain and IMAP server
- **Configuration**: Configure IMAP settings in the email service settings

### 3. MoeMail
- **Status**: ⚠️ Needs testing
- **Type**: Temporary email
- **Setup**: Automatic registration
- **Configuration**: Select "MoeMail" in the email service dropdown

### 4. CatchMail.io
- **Status**: ❌ Does not work
- **Issue**: OpenRouter does not send emails to @catchmail.io addresses
- **Recommendation**: Use LuckMail or IMAP Catchall instead

## How to Change Email Service

1. Go to Settings → Email Service
2. Select a different email service (e.g., LuckMail)
3. Configure any required API keys or settings
4. Try registration again

## Troubleshooting

If you're still not receiving verification codes:

1. **Check email service logs** - Look for any errors in the email polling
2. **Try with headed browser** - Set executor to "headed" to see what's happening
3. **Increase timeout** - Increase the OTP timeout in settings (default is 120s)
4. **Check spam/junk** - Some email services may filter OpenRouter emails
5. **Use a real email** - For testing, try with a real email address to confirm OpenRouter is sending emails

## Technical Details

The issue occurs because:
1. OpenRouter uses Clerk for authentication
2. Clerk sends verification emails through their email service
3. Many temporary email domains are blocked by email reputation systems
4. CatchMail.io appears to be on a blocklist

The verification code format is typically:
- 6-digit numeric code
- Sent in an email with subject containing "verification" or "code"
- Pattern: `(?is)(?:verification\s+code|code|verify)[^0-9]{0,50}(\d{6})`
