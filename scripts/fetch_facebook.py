import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()

# Graph API version: current docs show v23.0 as available; you can bump later if needed.
GRAPH_VERSION = os.environ.get("FB_GRAPH_VERSION", "v23.0").strip()

LIMIT = int(os.environ.get("FB_LIMIT", "25"))

if not FB_PAGE_ID or not FB_PAGE_ACCESS_TOKEN:
    print("Missing FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN", file=sys.stderr)
    sys.exit(1)

GRAPH = "https://graph.facebook.com"

def parse_dt(s: str) -> datetime:
    # Facebook commonly returns ISO 8601 like: 2026-01-30T12:34:56+0000
    s = s.replace("Z", "+00:00")
    if s.endswith("+0000"):
        s = s[:-5] + "+00:00"
    return datetime.fromisoformat(s)

def main():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    url = f"{GRAPH}/{GRAPH_VERSION}/{FB_PAGE_ID}/feed"
    params = {
        "fields": "message,created_time,permalink_url,full_picture",
        "limit": str(LIMIT),
        "access_token": FB_PAGE_ACCESS_TOKEN,
    }

    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        print("Facebook API error:", r.status_code, r.text, file=sys.stderr)
        sys.exit(1)

    data = r.json()
    items = data.get("data", [])

    # Sort newest first using created_time (string sort works for ISO-ish, but we’ll parse safely)
    def created_dt(item):
        ct = item.get("created_time")
        if not ct:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)
        try:
            return parse_dt(ct)
        except Exception:
            return datetime(1970, 1, 1, tzinfo=timezone.utc)

    items_sorted = sorted(items, key=created_dt, reverse=True)

    last24 = [p for p in items_sorted if created_dt(p) >= cutoff]

    if len(last24) >= 3:
        out_posts = last24[:3]
        mode = "last24"
    else:
        out_posts = items_sorted[:3]
        mode = "fallback_recent"

    out = {
        "generated_at": now.isoformat(),
        "cutoff_utc": cutoff.isoformat(),
        "mode": mode,
        "count": len(out_posts),
        "posts": out_posts,
    }

    os.makedirs("assets/data", exist_ok=True)
    with open("assets/data/facebook.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(out_posts)} posts to assets/data/facebook.json (mode={mode})")

if __name__ == "__main__":
    main()
