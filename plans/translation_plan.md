# Translation Extraction Plan

## Identified User‑Facing Strings (sample)
- "With RT"
- "Without RT"
- "Two‑Factor Authentication"
- "Please enter the 6‑digit code from your authenticator app"
- "Back to Password Login"
- "Account Manager"
- "Please enter your password to login"
- "Login"
- "Add Proxy (one per line)"
- "http://user:pass@host:port"
- "Region tag (e.g. US, SG)"
- "Confirm deletion of this proxy?"
- "Delete"
- "Cancel"
- "Add"
- "Confirm import"
- "Copy Logs"
- "Copy link"
- "Run"
- "Save"
- "Saved ✓"
- "Start Registration"
- "Registering..."
- "Verify and Login"
- "Email"
- "Password"
- "Confirm"
- "Add account manually"
- "Bulk import"
- "Settings"
- "Configuration"
- "Install/Update Strategy"
- "Batch operations"
- "Run frontend locally"
- "Documentation"
- "Add i18n support and translate UI strings"

## Next Steps
1. **Create a translation source file** (e.g., `frontend/src/locales/en.json`) containing key‑value pairs for all identified strings. Keys should be snake_case identifiers derived from the English text.
2. **Integrate i18n library** (react‑i18next) if not already present in the project. Add the `I18nextProvider` at the root of the app and configure the JSON resource.
3. **Replace hard‑coded strings** with the `t('key')` function throughout the frontend codebase.
4. **Verify UI** by running the frontend locally and ensuring all text appears correctly via the translation system.
5. **Update documentation** (README, developer guides) to reflect the new i18n implementation.
6. **Commit changes** with a clear commit message.

## Notes
- The extraction list above is a sample; a full extraction should be performed using a script that scans all `.tsx`, `.ts`, `.jsx`, and `.js` files for string literals and JSX text nodes.
- Consider using tools like `babel-plugin-react-intl` or a custom script to automate the extraction and key generation.
