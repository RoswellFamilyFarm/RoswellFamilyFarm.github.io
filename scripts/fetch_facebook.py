import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

FB_PAGE_ID = os.environ.get("FB_PAGE_ID", "").strip()
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
GRAPH_VERSION = os.environ.get("FB_GRAPH_VERSION", "v23.0").strip()
LIMIT = int(os.environ.get("FB_LIMIT", "25"))

GRAPH = "https://graph.facebook.com"
OUT_PATH = "assets/data/facebook.json"

FIELDS = "id,message,created_time,permalink_url,full_picture"


def iso_z(dt: datetime) -> str:
    """UTC ISO string ending in Z."""
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(s: str) -> datetime:
    """
    Facebook often returns:
      2026-01-30T12:34:56+0000
      2026-01-30T12:34:56+00:00
      2026-01-30T12:34:56Z
    Normalize so datetime.fromisoformat can parse it.
    """
    if not s:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    s = s.replace("Z", "+00:00")

    # +0000 -> +00:00
    if len(s) >= 5 and (s.endswith("+0000") or s.endswith("-0000")):
        s = s[:-5] + s[-5:-2] + ":" + s[-2:]

    # Some APIs return +HHMM / -HHMM
    if len(s) >= 5 and (s[-5] in ["+", "-"]) and s[-3] != ":":
        s = s[:-5] + s[-5:-2] + ":" + s[-2:]

    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clean_post(item: dict) -> dict:
    """Keep only fields we actually use (and keep output stable)."""
    return {
        "id": item.get("id"),
        "message": item.get("message"),
        "created_time": item.get("created_time"),
        "permalink_url": item.get("permalink_url"),
        "full_picture": item.get("full_picture"),
    }


def fetch_feed(session: requests.Session, since_unix: int | None = None) -> list[dict]:
    url = f"{GRAPH}/{GRAPH_VERSION}/{FB_PAGE_ID}/feed"
    params = {
        "fields": FIELDS,
        "limit": str(LIMIT),
        "access_token": FB_PAGE_ACCESS_TOKEN,
    }
    if since_unix is not None:
        params["since"] = str(since_unix)

    r = session.get(url, params=params, timeout=30)
    if r.status_code != 200:
        # Helpful error text for common token mistakes
        try:
            err = r.json().get("error", {})
        except Exception:
            err = {}
        print(f"Facebook API error: {r.status_code} {r.text}", file=sys.stderr)
        if err:
            print(f"FB error details: {err}", file=sys.stderr)
        sys.exit(1)

    data = r.json()
    return data.get("data", [])


def main():
    if not FB_PAGE_ID or not FB_PAGE_ACCESS_TOKEN:
        print("Missing FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    cutoff_unix = int(cutoff.timestamp())

    session = requests.Session()

    # 1) Try last-24-hours first (fast + relevant)
    items = fetch_feed(session, since_unix=cutoff_unix)

    # Sort newest first
    items_sorted = sorted(items, key=lambda p: parse_dt(p.get("created_time", "")), reverse=True)

    # Filter out totally empty posts (no message + no picture)
    last24 = [
        p for p in items_sorted
        if parse_dt(p.get("created_time", "")) >= cutoff and (p.get("message") or p.get("full_picture"))
    ]

    if len(last24) >= 3:
        out_posts = last24[:3]
        mode = "last24"
    else:
        # 2) Fallback: grab recent feed (no since), use newest 3 usable
        items2 = fetch_feed(session, since_unix=None)
        items2_sorted = sorted(items2, key=lambda p: parse_dt(p.get("created_time", "")), reverse=True)
        usable = [p for p in items2_sorted if (p.get("message") or p.get("full_picture"))]
        out_posts = usable[:3]
        mode = "fallback_recent"

    out = {
        "generated_at": iso_z(now),
        "cutoff_utc": iso_z(cutoff),
        "mode": mode,
        "count": len(out_posts),
        "posts": [clean_post(p) for p in out_posts],
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(out_posts)} posts to {OUT_PATH} (mode={mode})")


if __name__ == "__main__":
    # small retry for occasional network hiccups
    for attempt in range(1, 4):
        try:
            main()
            break
        except requests.RequestException as e:
            if attempt == 3:
                raise
            print(f"Network error ({attempt}/3): {e}. Retrying...", file=sys.stderr)
            time.sleep(2)
