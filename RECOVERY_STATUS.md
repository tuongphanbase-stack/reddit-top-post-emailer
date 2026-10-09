# Recovery status: REBUILT, WORKING

**Current state (October 2026):** the repository is complete. The original
code was lost; `reddit_top_post_emailer.py` was written anew after the
recovery (the day's top SFW posts, already-sent posts skipped), with its
scheduled workflow, tests and the status dashboard in `docs/`. Reddit blocks
its anonymous API from GitHub's servers, so emails need the
`REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` secrets; without them each run
is skipped with a warning.

The notes below describe the recovery itself.

## At recovery time

No original repository bytes for this repo were retained in Library. This folder reconstructs the GitHub Pages/dashboard role from prior work notes. It is **not** a byte-for-byte copy of the original backend/emailer.

Remembered role: SFW-only top-post dashboard metadata.
