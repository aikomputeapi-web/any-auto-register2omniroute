# Outlook OTP Polling diagnostic log design

## background
ChatGPT The registration link will be entered after sending the email verification code. Outlook Blocking decoding phase for local pool mailboxes.

The current phenomenon is:
- The log only shows“Waiting for email verification code”
- In fact, polling will continue internally IMAP
- But there is no intermediate diagnostic log during the polling process
- IMAP Query exceptions will also be swallowed silently and look like“stuck”

This results in the inability to quickly differentiate between:
1. Didn't receive the email at all
2. Email coming in Junk instead of INBOX
3. IMAP Login or query exception
4. The email was received, but the verification code extraction failed.

## Target
Without changing the existing coding behavior, for Outlook The local pool code collection process supplements minimal but sufficient diagnostic logs to help quickly locate OTP Cause of stage blocking.

## plan
Use minimally scoped implementation: only modify Outlook The code collection logic remains unchanged. ChatGPT The main link does not change the mailbox selection logic.

Change location:
- `core/base_mailbox.py`
- Key functions:`OutlookMailbox.wait_for_code()`

### Log range
This new log includes:

1. **Overview of each polling round**
   - The folder currently being polled
   - IMAP Is the login successful?
   - This round UID total
   - New UID quantity

2. **Compact log of hit messages**
   - hit mail subject
   - Whether to extract the verification code?
   - If the verification code hits but belongs to `exclude_codes`,Print“Skip attempted verification codes”

3. **Exception log**
   - IMAP Login failure reason
   - select/search/fetch Reason for failure
   - Other reasons for polling exceptions

4. **Double folder diagnostics**
   - exist `INBOX` and `Junk` Execute the same polling logic on both folders
   - The current folder is clearly marked in the log
   - Check first `INBOX`, check again `Junk`

## design details
### Keep behavior the same
- Still use the existing timeout mechanism and 5 second polling interval
- Still only returns when a usable verification code is extracted
- still supported `before_ids` and `exclude_codes`
- Do not modify the upper layer ChatGPT Registration process

### Log control principles
To avoid excessively dirty logs:
- Do not print email body
- Do not print the entire mailing list
- Not printing in full token / certificate
- Only print statistical information,subject, extraction results, abnormal reasons

### folder policy
This time only the most common secondary diagnostic folders are added:`Junk`.

Implementation meeting:
- for each round poll, try in turn `INBOX`,`Junk`
- Print each folder independently select/search result
- Share the same group `seen` / `exclude_codes` filter logic

This way you can locate:
- Does the email only go to the trash can?
- Are there no new emails on both sides?
- Whether only a certain folder query failed

## Comparison of alternatives
### plan A: only in OutlookMailbox.wait_for_code Simplify the log and add INBOX/Junk Double folder diagnostics (recommended)
- Advantages: minimal changes, most direct positioning information, close to the real polling point
- Advantages: can clearly distinguish INBOX and Junk the result
- shortcoming:OutlookMailbox Internal logging logic has been slightly increased

### plan B:exist BaseMailbox._run_polling_wait Make a general log
- Advantages: Can be reused for other mailbox implementations
- Disadvantages: Can’t get it Outlook Unique information such as UID quantity,subject, folder differences
- Disadvantages: Limited help for this problem

## Scope of influence
- Modify file:`core/base_mailbox.py`
- Does not involve:ChatGPT Main state machine, email import logic, front-end page, database structure

## Verification method
Once completed you should be able to see this in the actual log:
1. Enter OTP After waiting, periodic Outlook Polling log
2. can distinguish `INBOX` and `Junk` query results
3. like IMAP Exception, the cause of the exception can be seen in the log
4. If the email arrives but the verification code cannot be extracted, at least the hit email can be seen subject
5. If the verification code is `exclude_codes` Filter, you can see the skip prompt in the log

## risk
The risk is lower.

This time only the diagnostic log and `Junk` Folder polling does not modify existing business decisions and timeout behavior.

Main points to note:
- Logs cannot reveal sensitive text
- Do not change the original return conditions because of the log branch
- Dual folder polling cannot break existing `seen` Deduplication logic
