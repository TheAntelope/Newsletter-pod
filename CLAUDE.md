# Claude session conventions

## On the first turn of a new session

Before responding to the user's first message, sync with the remote so we're not working against a stale checkout (the user develops from multiple devices):

1. `git fetch origin` (no arguments — pulls all branches and tags).
2. Compare the current branch's local `HEAD` against `origin/<current-branch>` and against `origin/main`.
3. Report concisely:
   - If behind on the current branch: how many commits, and offer to fast-forward.
   - If `main` has moved since the branch diverged: note it, but do not auto-rebase.
   - If everything is up to date: a single line confirming so.
4. If the working tree has uncommitted changes, surface that in the same report.

Skip the sync only if the user's first message is purely conversational (no code or repo work implied).
