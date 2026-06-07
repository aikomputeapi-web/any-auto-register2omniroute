# Outlook OTP Polling Logs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** for Outlook local pool OTP The code collection link is supplemented with simplified diagnostic logs and added `INBOX` / `Junk` Dual folder polling for easy positioning“Wait for verification code”The real choke point of the stage.

**Architecture:** Keep ChatGPT The main process remains unchanged, only `OutlookMailbox.wait_for_code()` Increase diagnostic capabilities. Achieve pressing on each round poll Check in order `INBOX` and `Junk`,Record IMAP connect,UID Quantity, number of new messages, hits subject, Verification code extraction/Skip the results and exception reasons; do not print the text, and do not change the timeout and polling rhythm.

**Tech Stack:** Python, unittest, imaplib-style doubles, existing `BaseMailbox` polling helpers

---

### Task 1: for Outlook OTP Polling to supplement failed tests

**Files:**
- Create: `tests/test_outlook_mailbox.py`
- Test: `tests/test_outlook_mailbox.py`
- Verify against: `core/base_mailbox.py:3068-3405`

- [ ] **Step 1: Write out failed test files and cover Junk Rollback, exception log,exclude log**

Will `tests/test_outlook_mailbox.py` Created with the following content:

```python
import unittest
from unittest import mock

from core.base_mailbox import MailboxAccount, OutlookMailbox


class _FakeImapConnection:
    def __init__(self, folders=None):
        self.folders = folders or {}
        self.selected = []
        self.logged_out = False
        self.current_mailbox = None

    def select(self, mailbox, readonly=True):
        config = self.folders.get(mailbox, {})
        error = config.get("select_error")
        if error:
            raise error
        self.current_mailbox = mailbox
        self.selected.append((mailbox, readonly))
        return config.get("select_status", "OK"), [b""]

    def uid(self, command, *args):
        config = self.folders.get(self.current_mailbox, {})
        if command == "search":
            error = config.get("search_error")
            if error:
                raise error
            ids = config.get("ids", [])
            payload = b" ".join(
                uid if isinstance(uid, bytes) else str(uid).encode("utf-8")
                for uid in ids
            )
            return config.get("search_status", "OK"), [payload]
        if command == "fetch":
            error = config.get("fetch_error")
            if error:
                raise error
            uid = args[0]
            raw = config.get("messages", {}).get(uid)
            if raw is None:
                return "NO", []
            return "OK", [(b"RFC822", raw)]
        raise AssertionError(f"unexpected uid command: {command}")

    def logout(self):
        self.logged_out = True


class OutlookMailboxTests(unittest.TestCase):
    def _build_mailbox(self):
        mailbox = OutlookMailbox()
        self.logs = []
        mailbox._log_fn = self.logs.append
        return mailbox

    def _account(self):
        return MailboxAccount(
            email="demo@outlook.com",
            account_id="acc-1",
            extra={"password": "secret"},
        )

    def _raw_email(self, subject: str, body: str) -> bytes:
        return (
            f"Subject: {subject}\r\n"
            f"From: no-reply@example.com\r\n"
            f"To: demo@outlook.com\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n"
            f"{body}"
        ).encode("utf-8")

    def test_wait_for_code_logs_inbox_and_junk_and_returns_code_from_junk(self):
        mailbox = self._build_mailbox()
        mailbox._open_imap = mock.Mock(
            side_effect=[
                _FakeImapConnection({"INBOX": {"ids": []}}),
                _FakeImapConnection(
                    {
                        "Junk": {
                            "ids": [b"11"],
                            "messages": {
                                b"11": self._raw_email(
                                    "OpenAI verification code",
                                    "Your verification code is 222222",
                                )
                            },
                        }
                    }
                ),
            ]
        )

        code = mailbox.wait_for_code(self._account(), timeout=1)

        self.assertEqual(code, "222222")
        joined = "\n".join(self.logs)
        self.assertIn("[Outlook][OTP] folder=INBOX", joined)
        self.assertIn("[Outlook][OTP] folder=Junk", joined)
        self.assertIn("uid_total=0", joined)
        self.assertIn("new_uid_count=1", joined)
        self.assertIn("subject=OpenAI verification code", joined)
        self.assertIn("Verification code extraction successful: 222222", joined)

    @mock.patch("time.sleep", return_value=None)
    @mock.patch("time.monotonic", side_effect=[0.0, 0.0, 0.2, 0.2, 0.4])
    def test_wait_for_code_logs_imap_exception_and_recovers_on_next_poll(self, _monotonic, _sleep):
        mailbox = self._build_mailbox()
        mailbox._open_imap = mock.Mock(
            side_effect=[
                RuntimeError("imap boom"),
                _FakeImapConnection(
                    {
                        "INBOX": {
                            "ids": [b"21"],
                            "messages": {
                                b"21": self._raw_email(
                                    "Security code",
                                    "Security code: 333333",
                                )
                            },
                        }
                    }
                ),
            ]
        )

        code = mailbox.wait_for_code(self._account(), timeout=2)

        self.assertEqual(code, "333333")
        joined = "\n".join(self.logs)
        self.assertIn("IMAP Query exception: imap boom", joined)
        self.assertIn("subject=Security code", joined)
        self.assertIn("Verification code extraction successful: 333333", joined)

    @mock.patch("time.sleep", return_value=None)
    @mock.patch("time.monotonic", side_effect=[0.0, 0.0, 0.2, 0.2, 0.4])
    def test_wait_for_code_logs_skipped_excluded_code_then_returns_next_code(self, _monotonic, _sleep):
        mailbox = self._build_mailbox()
        mailbox._open_imap = mock.Mock(
            side_effect=[
                _FakeImapConnection(
                    {
                        "INBOX": {
                            "ids": [b"31"],
                            "messages": {
                                b"31": self._raw_email(
                                    "Verification code",
                                    "Your verification code is 111111",
                                )
                            },
                        }
                    }
                ),
                _FakeImapConnection({"INBOX": {"ids": []}}),
                _FakeImapConnection(
                    {
                        "INBOX": {
                            "ids": [b"31", b"32"],
                            "messages": {
                                b"32": self._raw_email(
                                    "Verification code",
                                    "Your verification code is 222222",
                                )
                            },
                        }
                    }
                ),
            ]
        )

        code = mailbox.wait_for_code(
            self._account(),
            timeout=2,
            exclude_codes={"111111"},
        )

        self.assertEqual(code, "222222")
        joined = "\n".join(self.logs)
        self.assertIn("Skip attempted verification codes: 111111", joined)
        self.assertIn("Verification code extraction successful: 222222", joined)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the new test and confirm it fails first**

Run:

```bash
python -m unittest discover -s tests -p "test_outlook_mailbox.py" -v
```

Expected:
- FAIL
- The failure reason should include one or more of the following:
  - not yet `folder=Junk` log
  - not yet `IMAP Query exception` log
  - not yet `Skip attempted verification codes` log
  - The current implementation does not start from `Junk` Return verification code

- [ ] **Step 3: Confirm that the failure is consistent with the design, rather than the test itself being written incorrectly**

Checkpoint:
- current `OutlookMailbox.wait_for_code()` Only `select("INBOX")`
- The current implementation does not `_log(...)` Output polling statistics
- current `except Exception` branch directly `return None`

Expected: It can be clearly stated that the test failed because the feature has not been implemented yet, not because the test is spelled or mock mistake.

- [ ] **Step 4: Submit (only if explicitly requested by the user) git execution)**

```bash
git add tests/test_outlook_mailbox.py
git commit -m "test: add outlook otp polling diagnostics coverage"
```

### Task 2: exist OutlookMailbox.wait_for_code Implement diagnostic logs and Junk rollback

**Files:**
- Modify: `core/base_mailbox.py:3332-3405`
- Test: `tests/test_outlook_mailbox.py`
- Regression: `tests/test_chatgpt_plugin.py`

- [ ] **Step 1: Read current OutlookMailbox.wait_for_code Implementation, locking the minimum scope of changes**

The current objective function is located at:
- `core/base_mailbox.py:3332-3405`

Current features:
- Check only `INBOX`
- share a group `seen`
- Return after extracting the verification code
- Exceptions will be swallowed and returned `None`

Expected: This time only modify the function and leave it unchanged `BaseMailbox._run_polling_wait()`, do not change ChatGPT Upper layer call.

- [ ] **Step 2: Adapted according to design wait_for_code, add streamlined logs and dual-folder polling**

Will `OutlookMailbox.wait_for_code()` Change it to the following implementation:

```python
    def wait_for_code(
        self,
        account: MailboxAccount,
        keyword: str = "",
        timeout: int = 120,
        before_ids: set = None,
        code_pattern: str = None,
        **kwargs,
    ) -> str:
        from email import message_from_bytes
        from email.policy import default as email_default_policy

        seen = {f"INBOX:{mid}" for mid in (before_ids or set())}
        exclude_codes = {
            str(code).strip()
            for code in (kwargs.get("exclude_codes") or set())
            if str(code or "").strip()
        }
        keyword_lower = str(keyword or "").strip().lower()
        folders = ["INBOX", "Junk"]

        def poll_once() -> Optional[str]:
            for folder in folders:
                imap_conn = None
                try:
                    self._log(f"[Outlook][OTP] folder={folder} Start polling")
                    imap_conn = self._open_imap(account)
                    self._log(f"[Outlook][OTP] folder={folder} IMAP Login successful")
                    status, _ = imap_conn.select(folder, readonly=True)
                    if status != "OK":
                        self._log(
                            f"[Outlook][OTP] folder={folder} select fail: status={status}"
                        )
                        continue
                    status, data = imap_conn.uid("search", None, "ALL")
                    if status != "OK":
                        self._log(
                            f"[Outlook][OTP] folder={folder} search fail: status={status}"
                        )
                        continue
                    ids = data[0].split() if data and data[0] else []
                    if len(ids) > 50:
                        ids = ids[-50:]
                    new_uids = []
                    for uid in ids:
                        uid_str = (
                            uid.decode("utf-8", errors="ignore")
                            if isinstance(uid, bytes)
                            else str(uid)
                        )
                        seen_key = f"{folder}:{uid_str}"
                        if not uid_str or seen_key in seen:
                            continue
                        seen.add(seen_key)
                        new_uids.append(uid)
                    self._log(
                        f"[Outlook][OTP] folder={folder} uid_total={len(ids)} new_uid_count={len(new_uids)}"
                    )
                    for uid in new_uids:
                        status, msg_data = imap_conn.uid("fetch", uid, "(RFC822)")
                        if status != "OK":
                            self._log(
                                f"[Outlook][OTP] folder={folder} fetch fail: uid={uid!r} status={status}"
                            )
                            continue
                        raw = None
                        for item in msg_data or []:
                            if isinstance(item, tuple) and item[1]:
                                raw = item[1]
                                break
                        if not raw:
                            self._log(
                                f"[Outlook][OTP] folder={folder} fetch Empty response: uid={uid!r}"
                            )
                            continue
                        msg = message_from_bytes(raw, policy=email_default_policy)
                        subject = self._decode_header_value(msg.get("Subject", ""))
                        text = self._extract_message_text(msg)
                        self._log(
                            f"[Outlook][OTP] folder={folder} hit new mail subject={subject or '-'}"
                        )
                        if keyword_lower and keyword_lower not in text.lower():
                            self._log(
                                f"[Outlook][OTP] folder={folder} Skip emails that don’t match keywords"
                            )
                            continue
                        code = self._safe_extract(text, code_pattern)
                        if not code:
                            self._log(
                                f"[Outlook][OTP] folder={folder} Verification code not retrieved"
                            )
                            continue
                        if code in exclude_codes:
                            self._log(
                                f"[Outlook][OTP] folder={folder} Skip attempted verification codes: {code}"
                            )
                            continue
                        self._log(
                            f"[Outlook][OTP] folder={folder} Verification code extraction successful: {code}"
                        )
                        return code
                except Exception as exc:
                    self._log(f"[Outlook][OTP] folder={folder} IMAP Query exception: {exc}")
                    continue
                finally:
                    try:
                        if imap_conn:
                            imap_conn.logout()
                    except Exception:
                        pass
            return None

        return self._run_polling_wait(
            timeout=timeout,
            poll_interval=5,
            poll_once=poll_once,
        )
```

Implementation requirements:
- reserve `timeout` / `poll_interval=5`
- Only print statistics,subject, extraction results, abnormal reasons
- Do not print text
- `seen` must be added `folder:` prefix, avoid `INBOX` and `Junk` of UID conflict
- `before_ids` Continue to only map to `INBOX`, remain compatible with the current baseline sampling behavior

- [ ] **Step 3: Run a new test and confirm that everything turns green**

Run:

```bash
python -m unittest discover -s tests -p "test_outlook_mailbox.py" -v
```

Expected:
- PASS
- 3 All tests passed

- [ ] **Step 4: Run existing ChatGPT custom_provider Regression testing**

Run:

```bash
python -m unittest discover -s tests -p "test_chatgpt_plugin.py" -v
```

Expected:
- PASS
- `test_custom_provider_uses_mailbox_baseline_for_verification_code`
- `test_custom_provider_prefers_configured_mailbox_timeout`
- `test_custom_provider_rejects_blank_email`

- [ ] **Step 5: Submit (only if explicitly requested by the user) git execution)**

```bash
git add core/base_mailbox.py tests/test_outlook_mailbox.py
git commit -m "fix: log outlook otp polling details"
```
