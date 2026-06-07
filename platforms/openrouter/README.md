# OpenRouter Platform

Automatic registration for OpenRouter.ai with API key generation.

## Features

- Automatic account registration
- Email verification
- Automatic API key generation
- API keys saved to `openrouter_keys.txt`
- API keys displayed in dashboard

## Requirements

- Headless or headed browser executor (no protocol-only support)
- Email service configured
- Playwright browser installed

## Registration Process

1. Navigate to signup page
2. Fill email and password
3. Verify email with OTP code
4. Login to account
5. Navigate to API keys settings
6. Generate new API key
7. Extract and save API key

## API Key Storage

API keys are saved in two places:
1. Database: Stored in the `token` field and `extra.api_key`
2. File: Appended to `openrouter_keys.txt` in format `email:api_key`

## Usage

The API key will be displayed in the dashboard's token column after successful registration.

## Notes

- OpenRouter uses browser-based registration (no protocol-only mode)
- API key format: `sk-or-v1-...` or similar patterns
- Keys are automatically extracted from the settings page after generation
