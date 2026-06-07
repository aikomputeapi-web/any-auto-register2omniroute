# OmniRoute Auto-Upload Configuration Guide

This guide explains how to configure automatic upload of ChatGPT accounts to your OmniRoute instance at `admin.aikompute.com`.

## Overview

The system already has OmniRoute integration built-in. After successful ChatGPT registration, accounts can be automatically uploaded to your OmniRoute instance as Codex provider connections.

## Configuration Steps

### 1. Set OmniRoute API URL

In your application settings (via the web UI or configuration file), set:

```
omniroute_api_url = https://admin.aikompute.com
```

**Important:** Use `https://` and do NOT include a trailing slash or `/api` path. The system will automatically append `/api/providers` when making requests.

### 2. Set Admin Password

Set your OmniRoute admin dashboard password:

```
omniroute_admin_password = YOUR_ADMIN_PASSWORD
```

This password is used to authenticate with your OmniRoute instance at `/api/auth/login` to obtain an `auth_token` cookie, which is then used for the provider upload request.

### 3. Enable ChatGPT Auto-Upload

Enable automatic upload for ChatGPT accounts:

```
omniroute_chatgpt_enabled = true
```

## How It Works

### Authentication Flow

1. System performs login: `POST https://admin.aikompute.com/api/auth/login`
   ```json
   {
     "password": "YOUR_ADMIN_PASSWORD"
   }
   ```

2. Receives `auth_token` cookie from response

3. Uses cookie to upload provider: `POST https://admin.aikompute.com/api/providers`

### Upload Payload

The system sends a Codex provider connection with OAuth credentials:

```json
{
  "provider": "codex",
  "authType": "oauth",
  "name": "user@example.com",
  "email": "user@example.com",
  "accessToken": "...",
  "refreshToken": "...",
  "idToken": "...",
  "isActive": true,
  "testStatus": "unknown",
  "providerSpecificData": {
    "clientId": "app_EMoamEEZ73f0CkXaXp7hrann"
  }
}
```

### When Upload Happens

Automatic upload is triggered:
- ✅ After successful ChatGPT account registration
- ✅ When manually clicking "Upload to OmniRoute" button in the UI
- ✅ During bulk account sync operations

## Configuration via Web UI

1. Navigate to **Settings** → **Integrations** in your web interface
2. Find the **OmniRoute** section
3. Enter your configuration:
   - **API URL:** `https://admin.aikompute.com`
   - **Admin Password:** Your OmniRoute admin password
   - **Enable ChatGPT Upload:** ✓ Checked

4. Click **Save** or **Test Connection** to verify

## Configuration via Environment Variables

Alternatively, you can set these via environment variables:

```bash
export OMNIROUTE_API_URL="https://admin.aikompute.com"
export OMNIROUTE_ADMIN_PASSWORD="your_password_here"
export OMNIROUTE_CHATGPT_ENABLED="true"
```

Or in a `.env` file:

```env
OMNIROUTE_API_URL=https://admin.aikompute.com
OMNIROUTE_ADMIN_PASSWORD=your_password_here
OMNIROUTE_CHATGPT_ENABLED=true
```

## Verification

### Check Logs

After registration, look for these log messages:

```
[OK] Registration successful: user@example.com
OmniRoute ChatGPT upload -> https://admin.aikompute.com/api/providers (email=user@example.com)
Upload to OmniRoute successful
```

### Check OmniRoute Dashboard

1. Log into your OmniRoute dashboard at `https://admin.aikompute.com`
2. Navigate to **Providers** or **Connections**
3. You should see new Codex provider connections with the registered email addresses

## Troubleshooting

### Upload Failed: "OmniRoute API URL not configured"

**Solution:** Set the `omniroute_api_url` configuration value.

### Upload Failed: "Failed to authenticate with OmniRoute"

**Possible causes:**
- Incorrect admin password
- OmniRoute instance not accessible
- Network/firewall issues

**Solution:** 
1. Verify your admin password is correct
2. Test access: `curl https://admin.aikompute.com/api/auth/login -d '{"password":"YOUR_PASSWORD"}'`
3. Check firewall/network settings

### Upload Failed: HTTP 401 or 403

**Cause:** Authentication failed or insufficient permissions

**Solution:**
1. Verify admin password is correct
2. Ensure the admin account has permission to create provider connections
3. Check OmniRoute logs for authentication errors

### Upload Failed: HTTP 400 or 422

**Cause:** Invalid payload or duplicate provider

**Solution:**
1. Check if the provider already exists in OmniRoute
2. Verify the account has valid tokens (access_token, refresh_token)
3. Check OmniRoute API logs for validation errors

### Upload Skipped

If you see `Skipped upload: Registered directly via OmniRoute dashboard`, this means the account was registered through OmniRoute's own registration flow and doesn't need to be uploaded back.

## Manual Upload

If automatic upload fails or is disabled, you can manually upload accounts:

1. Go to **Accounts** page in the web UI
2. Select the ChatGPT account(s) you want to upload
3. Click **Actions** → **Upload to OmniRoute**
4. Confirm the upload

## Security Notes

- **Password Storage:** The admin password is stored in your configuration database. Ensure your database is properly secured.
- **HTTPS:** Always use HTTPS for your OmniRoute instance to protect credentials in transit.
- **Access Control:** The admin password grants full access to your OmniRoute instance. Keep it secure.

## API Reference

### Configuration Keys

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `omniroute_api_url` | string | Yes | Base URL of your OmniRoute instance (e.g., `https://admin.aikompute.com`) |
| `omniroute_admin_password` | string | Yes | Admin dashboard password for authentication |
| `omniroute_chatgpt_enabled` | boolean | No | Enable automatic upload for ChatGPT accounts (default: true if URL is set) |
| `omniroute_kiro_enabled` | boolean | No | Enable automatic upload for Kiro accounts (default: true if URL is set) |
| `omniroute_cloudflare_enabled` | boolean | No | Enable automatic upload for Cloudflare accounts (default: true if URL is set) |
| `omniroute_cursor_enabled` | boolean | No | Enable automatic upload for Cursor accounts (default: true if URL is set) |
| `omniroute_grok_enabled` | boolean | No | Enable automatic upload for Grok accounts (default: true if URL is set) |
| `omniroute_mistral_enabled` | boolean | No | Enable automatic upload for Mistral accounts (default: true if URL is set) |
| `omniroute_nvidia_nim_enabled` | boolean | No | Enable automatic upload for Nvidia NIM accounts (default: true if URL is set) |
| `omniroute_openblocklabs_enabled` | boolean | No | Enable automatic upload for OpenBlockLabs accounts (default: true if URL is set) |
| `omniroute_openrouter_enabled` | boolean | No | Enable automatic upload for OpenRouter accounts (default: true if URL is set) |
| `omniroute_tavily_enabled` | boolean | No | Enable automatic upload for Tavily accounts (default: true if URL is set) |

### Extending to New Platforms (For Developers)

When a new platform is added to the system under `platforms/`, it will automatically be synced to OmniRoute if `omniroute_api_url` is configured. To customize this behavior:

1. **Settings Toggle**: Add `omniroute_<new_platform>_enabled` to `CONFIG_KEYS` in [`api/config.py`](../api/config.py) and update the form parsing/fields in [`frontend/src/pages/Settings.tsx`](../frontend/src/pages/Settings.tsx).
2. **Payload Mapping**: Check [`services/omniroute_sync.py`](../services/omniroute_sync.py). If the new platform uses OAuth (requiring `accessToken`, `refreshToken`, etc.), add its platform key to `oauth_platforms`. If it uses standard API keys, it will automatically fall back to `apikey` and map `token` or `api_key` to `apiKey`.

### Implementation Files

- **Unified Upload Logic:** [`services/omniroute_sync.py`](../services/omniroute_sync.py)
- **Auto-Sync Trigger:** [`services/external_sync.py`](../services/external_sync.py)
- **API Endpoints:** [`api/integrations.py`](../api/integrations.py)
- **Config Management:** [`api/config.py`](../api/config.py)

## Example: Complete Setup

```bash
# 1. Set configuration
curl -X POST http://localhost:8000/api/config \
  -H "Content-Type: application/json" \
  -d '{
    "omniroute_api_url": "https://admin.aikompute.com",
    "omniroute_admin_password": "your_secure_password",
    "omniroute_chatgpt_enabled": true
  }'

# 2. Register a ChatGPT account (will auto-upload)
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "chatgpt",
    "count": 1
  }'

# 3. Check upload status in logs
tail -f logs/app.log | grep OmniRoute
```

## Next Steps

After configuration:
1. ✅ Test with a single account registration
2. ✅ Verify the account appears in your OmniRoute dashboard
3. ✅ Enable bulk registration if needed
4. ✅ Monitor logs for any upload failures

For additional help, check the OmniRoute documentation or contact support.
