# OmniRoute Auto-Upload Integration Plan

## Executive Summary

**Good News**: The OmniRoute `/api/providers` endpoint **already supports OAuth provider connections**! The current implementation in `any-auto-register` is mostly correct, but needs minor adjustments to properly support OAuth authentication type.

**Key Finding**: The existing `POST /api/providers` endpoint in OmniRoute can handle both API key and OAuth connections. The `createProviderConnection` function already has sophisticated logic for OAuth connections including workspace-based deduplication for Codex/ChatGPT accounts.

---

## Current State Analysis

### OmniRoute Capabilities (✅ Already Implemented)

**File**: [`c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/route.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/route.ts:58)

The endpoint currently:
- ✅ Accepts `POST /api/providers` requests
- ✅ Uses `requireManagementAuth()` middleware (cookie-based auth)
- ✅ Validates with Zod schema [`createProviderSchema`](c:/users/administrator/coding/ai-platform/OmniRoute/src/shared/validation/schemas.ts:244)
- ✅ Calls [`createProviderConnection()`](c:/users/administrator/coding/ai-platform/OmniRoute/src/lib/db/providers.ts:98) which supports OAuth
- ❌ **BUT**: Currently hardcoded to `authType: "apikey"` on line 149

### Database Layer (✅ OAuth Ready)

**File**: [`c:/users/administrator/coding/ai-platform/OmniRoute/src/lib/db/providers.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/lib/db/providers.ts:98)

The `createProviderConnection` function:
- ✅ Supports `authType: "oauth"` (line 111)
- ✅ Handles OAuth fields: `accessToken`, `refreshToken`, `idToken`, `expiresAt` (lines 208-213)
- ✅ Has intelligent upsert logic for Codex with workspace deduplication (lines 115-136)
- ✅ Uses email-based deduplication for other OAuth providers (lines 140-145)

### any-auto-register Implementation

**Files**:
- [`platforms/chatgpt/omniroute_upload.py`](platforms/chatgpt/omniroute_upload.py:1)
- [`platforms/kiro/omniroute_upload.py`](platforms/kiro/omniroute_upload.py:1)

Current implementation:
- ✅ Correctly authenticates via `/api/auth/login` to get `auth_token` cookie
- ✅ Sends proper OAuth payload with `authType: "oauth"`
- ✅ Includes all required fields: `accessToken`, `refreshToken`, `email`, etc.
- ⚠️ **Issue**: OmniRoute endpoint ignores `authType` from request body

---

## Root Cause

The `POST /api/providers` endpoint in OmniRoute is hardcoded to create API key connections only:

```typescript
// Line 149 in src/app/api/providers/route.ts
const newConnection = await createProviderConnection({
  provider,
  authType: "apikey",  // ❌ Hardcoded!
  name,
  apiKey,
  // ... other fields
});
```

The validation schema [`createProviderSchema`](c:/users/administrator/coding/ai-platform/OmniRoute/src/shared/validation/schemas.ts:244) doesn't include `authType`, `accessToken`, `refreshToken`, or other OAuth fields.

---

## Solution: Modify OmniRoute Endpoint

### Option 1: Extend Existing Endpoint (Recommended)

Modify [`src/app/api/providers/route.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/route.ts:58) to accept OAuth connections.

**Changes Required**:

1. **Update Validation Schema** ([`src/shared/validation/schemas.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/shared/validation/schemas.ts:244)):
   ```typescript
   export const createProviderSchema = z
     .object({
       provider: z.string().min(1).max(100),
       authType: z.enum(["apikey", "oauth"]).optional().default("apikey"),
       apiKey: z.string().max(10000).optional(),
       // OAuth fields
       accessToken: z.string().max(10000).optional(),
       refreshToken: z.string().max(10000).optional(),
       idToken: z.string().max(10000).optional(),
       email: z.string().email().optional(),
       expiresAt: z.string().optional(),
       // ... existing fields
     })
     .refine(
       (data) => {
         if (data.authType === "apikey") return !!data.apiKey;
         if (data.authType === "oauth") return !!data.accessToken;
         return true;
       },
       { message: "apiKey required for apikey auth, accessToken required for oauth" }
     );
   ```

2. **Update Route Handler** ([`src/app/api/providers/route.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/route.ts:58)):
   ```typescript
   const {
     provider,
     authType,  // ✅ Accept from request
     apiKey,
     accessToken,
     refreshToken,
     idToken,
     email,
     expiresAt,
     name,
     // ... other fields
   } = validation.data;

   const newConnection = await createProviderConnection({
     provider,
     authType: authType || "apikey",  // ✅ Use from request
     name,
     apiKey,
     // OAuth fields
     accessToken,
     refreshToken,
     idToken,
     email,
     expiresAt,
     // ... other fields
   });
   ```

### Option 2: Create Separate OAuth Endpoint

Create a new endpoint specifically for OAuth connections at [`src/app/api/providers/oauth/route.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/oauth/route.ts).

**Pros**:
- Cleaner separation of concerns
- Dedicated validation for OAuth
- No risk of breaking existing API key flow

**Cons**:
- Requires updating `any-auto-register` to use new endpoint
- More code duplication

---

## Implementation Steps

### Phase 1: Modify OmniRoute (Option 1 - Recommended)

1. **Update validation schema** in [`src/shared/validation/schemas.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/shared/validation/schemas.ts:244)
   - Add `authType`, `accessToken`, `refreshToken`, `idToken`, `email`, `expiresAt` fields
   - Add refinement to validate required fields based on `authType`

2. **Update route handler** in [`src/app/api/providers/route.ts`](c:/users/administrator/coding/ai-platform/OmniRoute/src/app/api/providers/route.ts:58)
   - Extract OAuth fields from validated body
   - Pass `authType` and OAuth fields to `createProviderConnection()`
   - Remove hardcoded `authType: "apikey"`

3. **Test the changes**
   - Create a test that POSTs an OAuth connection
   - Verify it's stored correctly in the database
   - Verify existing API key flow still works

### Phase 2: Verify any-auto-register (No Changes Needed!)

The current implementation in `any-auto-register` is already correct:
- ✅ [`platforms/chatgpt/omniroute_upload.py`](platforms/chatgpt/omniroute_upload.py:86) sends proper OAuth payload
- ✅ [`platforms/kiro/omniroute_upload.py`](platforms/kiro/omniroute_upload.py:82) sends proper OAuth payload
- ✅ Authentication flow is correct
- ✅ Error handling is appropriate

**No changes needed** once OmniRoute is updated!

### Phase 3: Testing

1. **Unit Tests** (OmniRoute):
   - Test API key creation (existing flow)
   - Test OAuth connection creation (new flow)
   - Test validation errors

2. **Integration Tests**:
   - Start OmniRoute locally
   - Run `any-auto-register` ChatGPT registration
   - Verify connection appears in OmniRoute database
   - Verify connection is usable for API calls

3. **Production Verification**:
   - Deploy OmniRoute changes
   - Test with real registration
   - Monitor logs for errors

### Phase 4: Documentation

Update [`docs/OMNIROUTE_AUTO_UPLOAD_GUIDE.md`](docs/OMNIROUTE_AUTO_UPLOAD_GUIDE.md:1) to clarify:
- The endpoint now supports both API key and OAuth connections
- OAuth connections are automatically deduplicated by email/workspace
- Example OAuth payload format

---

## Detailed Code Changes

### File 1: `src/shared/validation/schemas.ts`

**Location**: Line 244

**Change**:
```typescript
export const createProviderSchema = z
  .object({
    provider: z.string().min(1).max(100),
    authType: z.enum(["apikey", "oauth"]).optional().default("apikey"),
    apiKey: z.string().max(10000).optional(),
    // OAuth-specific fields
    accessToken: z.string().max(10000).optional(),
    refreshToken: z.string().max(10000).optional(),
    idToken: z.string().max(10000).optional(),
    email: z.string().email().max(200).optional(),
    expiresAt: z.string().optional(),
    // Existing fields
    name: z.string().min(1).max(200),
    priority: z.number().int().min(1).max(100).optional(),
    globalPriority: z.number().int().min(1).max(100).nullable().optional(),
    defaultModel: z.string().max(200).nullable().optional(),
    testStatus: z.string().max(50).optional(),
    providerSpecificData: z
      .record(z.string(), z.unknown())
      .optional()
      .superRefine((data, ctx) => {
        validateProviderSpecificData(data, ctx);
      }),
  })
  .refine(
    (data) => {
      // Validate required fields based on authType
      if (data.authType === "apikey" && !data.apiKey) {
        return false;
      }
      if (data.authType === "oauth" && !data.accessToken) {
        return false;
      }
      return true;
    },
    {
      message: "apiKey required for apikey authType, accessToken required for oauth authType",
    }
  );
```

### File 2: `src/app/api/providers/route.ts`

**Location**: Lines 72-158

**Change**:
```typescript
const {
  provider,
  authType,  // ✅ NEW: Accept from request
  apiKey,
  // ✅ NEW: OAuth fields
  accessToken,
  refreshToken,
  idToken,
  email,
  expiresAt,
  // Existing fields
  name,
  priority,
  globalPriority,
  defaultModel,
  testStatus,
  providerSpecificData: incomingPsd,
} = validation.data;

// ... existing validation logic ...

const newConnection = await createProviderConnection({
  provider,
  authType: authType || "apikey",  // ✅ CHANGED: Use from request instead of hardcoded
  name,
  apiKey,
  // ✅ NEW: Pass OAuth fields
  accessToken,
  refreshToken,
  idToken,
  email,
  expiresAt,
  // Existing fields
  priority: priority || 1,
  globalPriority: globalPriority || null,
  defaultModel: defaultModel || null,
  providerSpecificData,
  isActive: true,
  testStatus: testStatus || "unknown",
});
```

---

## Testing Checklist

- [ ] Verify OmniRoute schema accepts `authType: "oauth"`
- [ ] Verify OmniRoute schema accepts OAuth fields (`accessToken`, `refreshToken`, etc.)
- [ ] Test creating API key connection (existing flow should still work)
- [ ] Test creating OAuth connection for Codex provider
- [ ] Test creating OAuth connection for Kiro provider
- [ ] Verify workspace-based deduplication works for Codex
- [ ] Verify email-based deduplication works for other providers
- [ ] Test authentication flow with `auth_token` cookie
- [ ] Run `any-auto-register` ChatGPT registration end-to-end
- [ ] Run `any-auto-register` Kiro registration end-to-end
- [ ] Verify connections appear in OmniRoute dashboard
- [ ] Verify connections are usable for API proxying
- [ ] Update documentation

---

## Summary

**The fix is simpler than expected!** OmniRoute's database layer already fully supports OAuth connections. We just need to:

1. ✅ Update the validation schema to accept OAuth fields
2. ✅ Remove the hardcoded `authType: "apikey"` in the route handler
3. ✅ Pass OAuth fields through to `createProviderConnection()`

**No changes needed in `any-auto-register`** - the current implementation is already correct and will work once OmniRoute is updated.

---

*This plan is ready for implementation. The changes are minimal and low-risk since they only extend existing functionality without breaking the API key flow.*
