# Reddit Top Post Emailer

Emails a daily digest of the top Reddit posts (safe-for-work only), as cards
with a thumbnail, title, subreddit, score and comment count. Posts already
sent in the last 48 hours are skipped, so each email only has new posts.

Runs on GitHub Actions every day at 8:00 AM Vietnam time
(`.github/workflows/send-reddit.yml`); nothing needs to run on your computer.

> The original emailer code was lost when its GitHub account was suspended.
> `reddit_top_post_emailer.py` and its workflow are a **rewrite**, built the
> same way as the sibling 9gag-meme-emailer. The `docs/` dashboard is from the
> recovery bundle.

## Setup

1. **Gmail App Password**: turn on 2-Step Verification, then create one at
   https://myaccount.google.com/apppasswords.
2. **Reddit app (strongly recommended)**: Reddit often blocks anonymous
   requests from GitHub's servers. Go to https://www.reddit.com/prefs/apps,
   click "create another app", choose **script**, put any URL (e.g.
   `http://localhost`) as the redirect URI, and create it. The client ID is
   the short code under the app name; the secret is labeled "secret".
3. **Add secrets** under Settings -> Secrets and variables -> Actions:
   - `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`
   - `REDDIT_RECIPIENT`: where to send the digest
   - `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`: from step 2
4. **Optional settings**: add them as **Variables** (same page, Variables tab):
   - `SUBREDDITS`: `+`-separated, default `all` (e.g. `worldnews+technology+vietnam`)
   - `TOP_N`: posts per email, default 25
   - `TIME_FILTER`: `hour`, `day`, `week`, `month`, `year` or `all`; default `day`
5. **Test it**: Actions tab -> "Send Reddit Top Posts" -> Run workflow.

## Changing the schedule

Edit the `cron` line in `.github/workflows/send-reddit.yml`. It's always in
UTC: `0 1 * * *` is 01:00 UTC = 8:00 AM in Vietnam.

## Files

- `reddit_top_post_emailer.py`: fetches posts and sends the email
- `state/sent_ids.json`: recently sent posts (committed by the workflow)
- `docs/`: status dashboard; `docs/latest.json` is updated after each run
- `RECOVERY_STATUS.md`: notes from the account recovery
