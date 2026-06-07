# README Image Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair root directory README The two interface preview images cannot be displayed.

**Architecture:** Only modifications are made this time `README.md` The two image links do not change the image resource files nor other copywriting. The fix is ​​to delete the non-standard `null` suffix, and unify the path into a standard Markdown parsable `docs/images/...` Relative path.

**Tech Stack:** Markdown, GitHub-style Markdown rendering

---

### Task 1: repair README Image link

**Files:**
- Modify: `README.md:63-67`
- Verify: `docs/images/dashboard.png`
- Verify: `docs/images/settings-integrations.png`

- [ ] **Step 1: Read current README Preview snippet**

```markdown
### Dashboard

![Dashboard](./docs/images/dashboard.png null)

### Global configuration / Plug-in management

![Global configuration / Plug-in management](./docs/images/settings-integrations.png null)
```

- [ ] **Step 2: Confirm that the current writing method does not meet the target design**

Checkpoint:
- The end of the link contains `null`
- This way of writing is not standard Markdown Picture Grammar
- Design requirements are unified into `docs/images/...`

Expected: Confirm that two links need to be replaced.

- [ ] **Step 3: Change to standard by design Markdown Image link**

Change the snippet to:

```markdown
### Dashboard

![Dashboard](docs/images/dashboard.png)

### Global configuration / Plug-in management

![Global configuration / Plug-in management](docs/images/settings-integrations.png)
```

- [ ] **Step 4: Verify that the image resource path exists**

Check if the following files exist:

```text
docs/images/dashboard.png
docs/images/settings-integrations.png
```

Expected: Both files exist.

- [ ] **Step 5: reread README Relevant fragments confirm the modification results**

Expected: `README.md` The corresponding position in is shown as:
- `![Dashboard](docs/images/dashboard.png)`
- `![Global configuration / Plug-in management](docs/images/settings-integrations.png)`

- [ ] **Step 6: Submit (only if explicitly requested by the user) git execution)**

```bash
git add README.md
git commit -m "docs: fix README image links"
```
