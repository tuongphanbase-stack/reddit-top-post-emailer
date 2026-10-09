#!/usr/bin/env python3
"""
Reddit Top Posts of the Day -> Email (HTML digest)

Fetches the day's top posts from one or more subreddits, drops NSFW posts and
anything already emailed recently, and emails the rest as a digest of cards
(thumbnail, title, subreddit, score, comment count).

Runs in two phases, like the sibling 9gag-meme-emailer, so the GitHub Actions
workflow can commit the sent-post history after a successful send:

    python reddit_top_post_emailer.py generate
        -> fetches posts and writes the email (subject/html/text) to ./email/

    python reddit_top_post_emailer.py send
        -> sends ./email/* via Gmail SMTP, then records the posts as sent

SETUP
-----
1. pip install -r requirements.txt

2. Create a Gmail "App Password" (https://myaccount.google.com/apppasswords;
   2-Step Verification must be on).

3. Strongly recommended: create a Reddit "script" app at
   https://www.reddit.com/prefs/apps and use its client ID and secret.
   Reddit often blocks anonymous requests from cloud servers such as GitHub
   Actions; with app credentials the script uses Reddit's official API.

4. Environment variables:
       GMAIL_ADDRESS          sender Gmail address (required for send)
       GMAIL_APP_PASSWORD     Gmail App Password (required for send)
       REDDIT_RECIPIENT       where to send the digest (required for send)
       REDDIT_CLIENT_ID       Reddit app client ID (recommended)
       REDDIT_CLIENT_SECRET   Reddit app secret (recommended)
       SUBREDDITS             optional, "+"-separated, default "all"
                              e.g. "worldnews+technology+vietnam"
       TOP_N                  optional, posts per email, default 25
       TIME_FILTER            optional, hour/day/week/month/year/all, default day
       TIMEZONE               optional, for the subject line, default Asia/Ho_Chi_Minh
       SENT_RETENTION_HOURS   optional, how long a sent post is skipped, default 48
"""

import json
import os
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape, unescape

import requests

USER_AGENT = "python:reddit-top-post-emailer:v1.0 (personal daily digest)"
OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
OAUTH_API_BASE = "https://oauth.reddit.com"
PUBLIC_API_BASE = "https://www.reddit.com"

# Fetch more than TOP_N so there's room to drop NSFW / already-sent posts.
FETCH_LIMIT = 100

EMAIL_DIR = "email"
STATE_DIR = "state"
STATE_FILE = os.path.join(STATE_DIR, "sent_ids.json")
LATEST_FILE = os.path.join("docs", "latest.json")  # read by the docs/ dashboard

SENT_RETENTION_HOURS = float(os.environ.get("SENT_RETENTION_HOURS", "48"))


def get_oauth_token(client_id, client_secret):
    """App-only OAuth token (no Reddit user login needed)."""
    resp = requests.post(
        OAUTH_TOKEN_URL,
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"Reddit returned no access token: {resp.text[:300]}")
    return token


def fetch_top_posts(subreddits, time_filter, limit=FETCH_LIMIT):
    """Return the raw post dicts from /r/<subreddits>/top."""
    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    params = {"t": time_filter, "limit": limit, "raw_json": 1}

    if client_id and client_secret:
        token = get_oauth_token(client_id, client_secret)
        url = f"{OAUTH_API_BASE}/r/{subreddits}/top"
        headers = {"User-Agent": USER_AGENT, "Authorization": f"bearer {token}"}
    else:
        print("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set - using the anonymous "
              "API, which Reddit often blocks from cloud servers.", file=sys.stderr)
        url = f"{PUBLIC_API_BASE}/r/{subreddits}/top.json"
        headers = {"User-Agent": USER_AGENT}

    last_error = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=20)
            if resp.status_code == 429 and attempt < 3:
                time.sleep(5 * attempt)
                continue
            resp.raise_for_status()
            children = resp.json().get("data", {}).get("children", [])
            return [c.get("data", {}) for c in children]
        except (requests.RequestException, ValueError) as e:
            last_error = e
            if attempt < 3:
                time.sleep(2 * attempt)
    raise RuntimeError(f"Failed to fetch top posts from {url}: {last_error}")


def pick_thumbnail(post):
    """Best small image URL for a post, or None."""
    try:
        preview = post["preview"]["images"][0]
        # Pick the smallest resolution at least 320px wide, else the source.
        for res in preview.get("resolutions", []):
            if res.get("width", 0) >= 320:
                return unescape(res["url"])
        return unescape(preview["source"]["url"])
    except (KeyError, IndexError, TypeError):
        pass
    thumb = post.get("thumbnail") or ""
    return thumb if thumb.startswith("http") else None


def select_posts(posts, excluded_ids, top_n):
    """SFW, non-stickied, not-recently-sent posts, highest score first."""
    picked = []
    for p in sorted(posts, key=lambda p: p.get("score", 0), reverse=True):
        if p.get("over_18") or p.get("stickied"):
            continue
        post_id = p.get("name") or p.get("id")
        if not post_id or post_id in excluded_ids:
            continue
        picked.append({
            "id": post_id,
            "title": p.get("title", "(untitled)"),
            "subreddit": p.get("subreddit_name_prefixed") or f"r/{p.get('subreddit', '?')}",
            "score": int(p.get("score", 0)),
            "comments": int(p.get("num_comments", 0)),
            "permalink": "https://www.reddit.com" + p.get("permalink", ""),
            "thumbnail": pick_thumbnail(p),
        })
        if len(picked) >= top_n:
            break
    for rank, post in enumerate(picked, start=1):
        post["rank"] = rank
    return picked


def load_sent_ids():
    """{post_id: iso_timestamp} for posts sent within the retention window."""
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    cutoff = time.time() - SENT_RETENTION_HOURS * 3600
    fresh = {}
    for post_id, ts_str in data.items():
        try:
            if datetime.fromisoformat(ts_str).timestamp() >= cutoff:
                fresh[post_id] = ts_str
        except ValueError:
            continue
    return fresh


def save_sent_ids(sent_ids, newly_sent_ids):
    now_iso = datetime.now(timezone.utc).isoformat()
    merged = dict(sent_ids)
    for post_id in newly_sent_ids:
        merged[str(post_id)] = now_iso
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(merged, f, indent=2)


def build_card_html(p):
    title_esc = escape(p["title"])
    thumb = (
        f'<td style="width:110px; padding-right:12px; vertical-align:top;">'
        f'<a href="{escape(p["permalink"])}"><img src="{escape(p["thumbnail"])}" alt="" '
        f'width="110" style="display:block; width:110px; height:auto; max-height:140px; '
        f'object-fit:cover; border-radius:8px; background:#f0f0f0;"></a></td>'
        if p["thumbnail"] else ""
    )
    return f"""
<tr><td style="padding:8px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff; border:1px solid #e0e0e0; border-radius:10px;">
<tr><td style="padding:12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
{thumb}
<td style="vertical-align:top; font-family:Arial,Helvetica,sans-serif;">
<div style="font-size:12px; color:#888;">#{p['rank']} &middot; {escape(p['subreddit'])}</div>
<a href="{escape(p['permalink'])}" style="display:block; margin-top:4px; font-size:15px; line-height:1.35; color:#1a1a1b; text-decoration:none; font-weight:bold;">{title_esc}</a>
<div style="font-size:12px; color:#888; margin-top:6px;">&#9650; {p['score']:,} points &middot; {p['comments']:,} comments</div>
</td>
</tr></table>
</td></tr>
</table>
</td></tr>"""


def build_html(posts, subreddits):
    cards = "".join(build_card_html(p) for p in posts)
    return f"""\
<html>
<body style="margin:0; padding:20px; background:#f4f4f4; font-family:Arial,Helvetica,sans-serif;">
<h1 style="color:#222; font-size:22px;">Top {len(posts)} Reddit posts from r/{escape(subreddits)}</h1>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:700px;">
{cards}
</table>
<p style="color:#999; font-size:12px; margin-top:20px;">Safe-for-work posts only, ranked by score. Posts already sent recently are skipped.</p>
</body>
</html>"""


def build_plain_text(posts, subreddits):
    lines = [f"Top {len(posts)} Reddit posts from r/{subreddits}", ""]
    for p in posts:
        lines.append(f"#{p['rank']} [{p['subreddit']}] {p['title']} "
                     f"({p['score']} points, {p['comments']} comments) - {p['permalink']}")
    return "\n".join(lines)


def write_latest(item_count, status):
    os.makedirs(os.path.dirname(LATEST_FILE), exist_ok=True)
    with open(LATEST_FILE, "w") as f:
        json.dump({
            "repo": "reddit-top-post-emailer",
            "status": status,
            "item_count": item_count,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, f, indent=2)


def cmd_generate():
    subreddits = os.environ.get("SUBREDDITS") or "all"
    top_n = int(os.environ.get("TOP_N") or "25")
    time_filter = os.environ.get("TIME_FILTER") or "day"

    os.makedirs(EMAIL_DIR, exist_ok=True)
    sent_ids = load_sent_ids()
    print(f"Skipping {len(sent_ids)} post(s) sent in the last {SENT_RETENTION_HOURS:g}h.")

    print(f"Fetching top posts from r/{subreddits} (t={time_filter})...")
    try:
        raw_posts = fetch_top_posts(subreddits, time_filter)
    except RuntimeError as e:
        # Without API credentials Reddit blocks GitHub's servers almost every
        # day. Skip instead of failing the run (and emailing a failure
        # notice); with credentials set, a failure is real and still raises.
        if os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"):
            raise
        print(f"::warning::Reddit blocked the anonymous API, so no email was sent. "
              f"Add the REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET secrets to fix this. ({e})")
        with open(os.path.join(EMAIL_DIR, "meta.json"), "w") as f:
            json.dump({"total": 0, "ids": []}, f)
        write_latest(0, "blocked by Reddit - API credentials needed")
        return
    posts = select_posts(raw_posts, sent_ids, top_n)

    if not posts:
        print("No new qualifying posts.")
        with open(os.path.join(EMAIL_DIR, "meta.json"), "w") as f:
            json.dump({"total": 0, "ids": []}, f)
        write_latest(0, "no new posts")
        return

    timezone_name = os.environ.get("TIMEZONE") or "Asia/Ho_Chi_Minh"
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(timezone_name))
    except Exception:
        now = datetime.now()

    subject = f"Top {len(posts)} Reddit posts - {now.strftime('%b %d, %Y')}"
    with open(os.path.join(EMAIL_DIR, "subject.txt"), "w") as f:
        f.write(subject)
    with open(os.path.join(EMAIL_DIR, "body.html"), "w") as f:
        f.write(build_html(posts, subreddits))
    with open(os.path.join(EMAIL_DIR, "body.txt"), "w") as f:
        f.write(build_plain_text(posts, subreddits))
    with open(os.path.join(EMAIL_DIR, "meta.json"), "w") as f:
        json.dump({"total": len(posts), "ids": [p["id"] for p in posts]}, f)
    write_latest(len(posts), "ok")

    for p in posts:
        print(f"  #{p['rank']} [{p['subreddit']}] {p['title']} ({p['score']} points)")
    print(f"Generated {len(posts)} post(s). Email saved to ./{EMAIL_DIR}/")


def cmd_send():
    sender = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("REDDIT_RECIPIENT")

    missing = [name for name, val in [
        ("GMAIL_ADDRESS", sender),
        ("GMAIL_APP_PASSWORD", app_password),
        ("REDDIT_RECIPIENT", recipient),
    ] if not val]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    with open(os.path.join(EMAIL_DIR, "meta.json")) as f:
        meta = json.load(f)
    if meta.get("total", 0) == 0:
        print("No posts were found in the generate step - not sending an email.")
        return

    with open(os.path.join(EMAIL_DIR, "subject.txt")) as f:
        subject = f.read()
    with open(os.path.join(EMAIL_DIR, "body.html")) as f:
        html = f.read()
    with open(os.path.join(EMAIL_DIR, "body.txt")) as f:
        text = f.read()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(sender, app_password)
        server.send_message(msg)
    print(f"Sent to {recipient}!")

    # Only record posts as sent once the email actually went out.
    save_sent_ids(load_sent_ids(), meta.get("ids", []))
    print(f"Recorded {len(meta.get('ids', []))} post ID(s) in {STATE_FILE}.")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("generate", "send"):
        print("Usage: python reddit_top_post_emailer.py [generate|send]", file=sys.stderr)
        sys.exit(1)
    if sys.argv[1] == "generate":
        cmd_generate()
    else:
        cmd_send()


if __name__ == "__main__":
    main()
