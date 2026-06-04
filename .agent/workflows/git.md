---
description: Stage, commit, and push changes to remote
---

1. Determine the exact set of changed and untracked files related to the current task.
2. Review the diff of modified files using `git diff` to identify all key modifications.
3. Write a detailed, structured commit message that outlines:
   - What was changed (list of files and descriptions).
   - Why it was changed.
   - How it was verified/tested.
4. Stage only the relevant files using `git add <files>`. Do not stage unrelated temporary files or local build directories unless explicitly requested.
5. Commit the changes using the detailed message.
6. Push the commit to the remote repository using `git push`.
