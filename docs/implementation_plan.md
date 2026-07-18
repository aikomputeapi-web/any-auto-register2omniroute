# Convert All Pages to Brutalist Precision Template

Migrate every page from inline styles to the brutalist precision CSS class system established in `globals.css`. All pages will use the `--bg`, `--accent`, `--surface`, `--border-bright` design tokens, Space Grotesk/Space Mono fonts, and the sharp grid-based layout.

## Scope — 44 files, ~9,500 lines

### Tier 1: Auth Pages (small, high-visibility)
| File | Lines | Notes |
|------|-------|-------|
| `login/page.tsx` | 190 | Login form |
| `signup/page.tsx` | 164 | Registration form |
| `forgot-password/page.tsx` | 62 | Password reset request |
| `reset-password/page.tsx` | 82 | Password reset |
| `verify/page.tsx` | 69 | Email verification |
| `verify-pending/page.tsx` | 70 | Pending verification |
| `admin/login/page.tsx` | 176 | Admin login |

---

### Tier 2: User Dashboard (~750 lines)
| File | Lines | Notes |
|------|-------|-------|
| `dashboard/layout.tsx` | 186 | Sidebar layout wrapper |
| `dashboard/page.tsx` | 113 | Dashboard overview |
| `dashboard/keys/page.tsx` | 168 | API key management |
| `dashboard/billing/page.tsx` | 222 | Billing/subscription |
| `dashboard/settings/page.tsx` | 125 | Account settings |
| `dashboard/usage/page.tsx` | 25 | Usage stats |
| `dashboard/docs/page.tsx` | 39 | Inline docs |

---

### Tier 3: Admin Panel (~5,200 lines — largest)
| File | Lines | Notes |
|------|-------|-------|
| `admin/layout.tsx` | 187 | Admin sidebar layout |
| `admin/page.tsx` | 552 | Admin dashboard overview |
| `admin/usage-tab.tsx` | 400 | Usage analytics |
| `admin/forecast-tab.tsx` | 172 | Revenue forecasting |
| `admin/billing/page.tsx` | 664 | Billing management |
| `admin/billing/plans-tab.tsx` | 260 | Plan configuration |
| `admin/customers/page.tsx` | 73 | Customer list |
| `admin/customers/audit-log-tab.tsx` | 400 | Audit logs |
| `admin/customers/support-tab.tsx` | 591 | Support tickets |
| `admin/infrastructure/page.tsx` | 82 | Infra overview |
| `admin/infrastructure/models-tab.tsx` | 483 | Model management |
| `admin/infrastructure/catalog-tab.tsx` | 486 | Virtual catalog |
| `admin/infrastructure/operations-tab.tsx` | 482 | Operations |
| `admin/infrastructure/routing-tab.tsx` | 446 | Routing rules |
| `admin/infrastructure/reports-tab.tsx` | 505 | Scheduled reports |
| `admin/infrastructure/settings-tab.tsx` | 338 | Infra settings |
| `components/admin/AdminAccountsDashboard.tsx` | 1,600+ | Main admin component |

---

### Tier 4: Marketing / Content Pages (~1,500 lines)
| File | Lines | Notes |
|------|-------|-------|
| `models/page.tsx` | 183 | Model catalog |
| `features/page.tsx` | 122 | Features page |
| `pricing/page.tsx` | 167 | Pricing page |
| `docs/page.tsx` | 465 | API documentation |
| `quickstart/page.tsx` | 170 | Quickstart guide |
| `guides/page.tsx` | 201 | Integration guides |
| `changelog/page.tsx` | 106 | Changelog |
| `faq/page.tsx` | 99 | FAQ |
| `support/page.tsx` | 95 | Support |
| `status/page.tsx` | 113 | Status page |
| `privacy/page.tsx` | 42 | Privacy policy |
| `terms/page.tsx` | 44 | Terms of service |
| `preview/page.tsx` | 112 | Preview page |
| `components/RoutingFlow.tsx` | ~150 | Routing visualization |

## Approach

For each page, I will:
1. Replace inline `style={{...}}` with CSS classes from `globals.css`
2. Add any new utility classes to `globals.css` as needed (sidebar nav, form layouts, table styles, dashboard grids)
3. Fix the brand name split (`AI` + `KOMPUTE`) wherever it appears
4. Keep all functional logic, API calls, and state management untouched
5. Ensure the `'use client'` directive and imports remain correct

> [!IMPORTANT]
> **This is ~9,500 lines across 44 files.** It's a significant undertaking. I recommend tackling it in tiers so you can review as we go.

## Open Questions

1. **Should I proceed tier-by-tier** (auth → dashboard → admin → marketing) so you can review along the way? Or do you want me to blast through everything in one go?
2. **The admin panel is 5,200+ lines** — do you want the same brutalist grid aesthetic for data-heavy admin screens, or a slightly softer/more functional variant?
3. **Are there any pages you want me to skip** (e.g., preview page)?

## Verification Plan

### After Each Tier
- Run `npx next build` to verify zero compile/type errors
- Visual check of key pages in the browser
