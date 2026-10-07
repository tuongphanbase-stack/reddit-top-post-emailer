# Reddit Top Post Emailer

Emailed the top Reddit posts (safe-for-work only).

## Status: only the dashboard was restored

The original repository was lost when its GitHub account was suspended, and
**the emailer code could not be recovered**. This repo only has a rebuilt
dashboard page:

- `docs/`: the dashboard (`index.html`, `app.js`, `style.css`, `latest.json`)
- `.github/workflows/pages.yml`: publishes `docs/` to GitHub Pages
- `RECOVERY_STATUS.md`: recovery notes

The emailer itself (the Python script, its requirements and its scheduled
workflow) needs to be found in an old backup or rewritten.
