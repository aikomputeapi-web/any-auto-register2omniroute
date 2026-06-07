# OmniRoute OAuth Support Implementation

## Summary

Enabled OAuth provider connection support in OmniRoute's `/api/providers` endpoint to allow automatic upload of ChatGPT and Kiro accounts from any-auto-register.

## Problem

The OmniRoute `/api/providers` endpoint was hardcoded to only accept API key connections (`authType: "apikey"`), even though:
- The database layer fully supported OAuth connections
- The `any-auto-register` clients were already sending correct OAuth payloads
- Authentication via `auth_token` cookie was working correctly

## Solution

Modified two files in the OmniRoute codebase to accept OAuth connections:

### 1. Updated Validation Schema

**File**: [`c:/users/administrator/coding/ai-platform/OmniRoute/src/shared/validation/schemas.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/shared/validation/schemas.ts:244)

**Changes**:
- Added `authType` field with enum `["apikey", "oauth"]` (defaults to `"apikey"`)
- Added OAuth-specific fields: `accessToken`, `refreshToken`, `idToken`, `email`, `expiresAt`
- Updated validation logic to require `apiKey` for `authType: "apikey"` and `accessToken` for `authType: "oauth"`

### 2. Updated Route Handler

**File**: [`c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/route.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/route.ts:58)

**Changes**:
- Extract `authType` and OAuth fields from request body
- Pass `authType` from request instead of hardcoded `"apikey"`
- Pass OAuth fields (`accessToken`, `refreshToken`, `idToken`, `email`, `expiresAt`) to `createProviderConnection()`
- Updated comment to reflect endpoint now supports both API key and OAuth

## Files Modified

1. `c:/users/administrator/coding/ai-platform/OmniRoute/src/shared/validation/schemas.ts`
2. `c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/route.ts`

## Files NOT Modified (Already Correct)

- [`platforms/chatgpt/omniroute_upload.py`](../../platforms/chatgpt/omniroute_upload.py) - Already sends correct OAuth payload
- [`platforms/kiro/omniroute_upload.py`](../../platforms/kiro/omniroute_upload.py) - Already sends correct OAuth payload

## How It Works

### Request Flow

1. **any-auto-register** completes account registration (ChatGPT or Kiro)
2. Authenticates with OmniRoute via `POST /api/auth/login` to get `auth_token` cookie
3. Sends OAuth connection payload to `POST /api/providers`:
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
4. OmniRoute validates the request with updated schema
5. Creates provider connection with OAuth credentials
6. Database layer handles intelligent deduplication:
   - For Codex: workspace + email uniqueness
   - For other providers: email uniqueness

### Database Layer (No Changes Needed)

The [`createProviderConnection()`](c:/users/administrator/coding/ai-platform/OmniRoute/src/lib/db/providers.ts:98) function already had full OAuth support:
- Accepts `authType: "oauth"` (line 111)
- Stores OAuth fields: `accessToken`, `refreshToken`, `idToken`, `expiresAt` (lines 208-213)
- Implements workspace-based deduplication for Codex (lines 115-136)
- Implements email-based deduplication for other OAuth providers (lines 140-145)

## Testing

### Manual Testing Steps

1. **Start OmniRoute**:
   ```bash
   cd c:/users/administrator/coding/ai-platform/OmniRoute
   npm run dev
   ```

2. **Configure any-auto-register**:
   - Set `omniroute_api_url = https://admin.aikompute.com` (or local URL)
   - Set `omniroute_admin_password = YOUR_PASSWORD`
   - Set `omniroute_chatgpt_enabled = true`

3. **Run ChatGPT Registration**:
   ```bash
   cd c:/users/administrator/coding/any-auto-register
   python main.py
   # Register a ChatGPT account
   ```

4. **Verify**:
   - Check OmniRoute dashboard for new Codex connection
   - Verify connection has OAuth credentials
   - Test connection works for API proxying

### Expected Behavior

- ✅ API key connections continue to work (backward compatible)
- ✅ OAuth connections are created successfully
- ✅ Duplicate connections are updated (not duplicated)
- ✅ Workspace-based deduplication works for Codex
- ✅ Email-based deduplication works for other providers

## Backward Compatibility

The changes are fully backward compatible:
- Existing API key creation flow unchanged
- `authType` defaults to `"apikey"` if not provided
- All existing validation rules preserved
- No breaking changes to API contract

## Security Considerations

- OAuth tokens are encrypted at rest (existing encryption in database layer)
- Authentication still required via `auth_token` cookie
- No changes to authentication/authorization logic
- Sensitive fields still hidden in GET responses

## Related Documentation

- [OmniRoute Auto-Upload Guide](../OMNIROUTE_AUTO_UPLOAD_GUIDE.md)
- [Implementation Plan](../../plans/omni_route_auto_upload_plan.md)

## Date

2026-05-12
