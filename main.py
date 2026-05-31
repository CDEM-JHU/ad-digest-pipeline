#!/usr/bin/env python3
"""
Nightly AD-biomarker RSS -> Google Drive digest.

Pulls the last 24h of entries from a set of feeds, sorts them into three
priority buckets by keyword, compiles a clean text file, and uploads it to a
Google Drive folder (read from the DRIVE_FOLDER_ID env var) using a service
account key at ./credentials.json.

The uploaded text file is intended to be fed to NotebookLM (which can read
directly from a Drive folder) to generate an Audio Overview / podcast.
"""

import calendar
import html
import os
import sys
import time
from datetime import datetime, timezone, timedelta

import feedparser
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

# --- Configuration ---------------------------------------------------------

FEEDS = [
    {
        "name": "Alzheimer's & Dementia (Journal)",
        "url": "https://alz-journals.onlinelibrary.wiley.com/action/showFeed?jc=15525279&type=etoc&feed=rss",
    },
    {
        # AlzForum's own /rss/* paths are Cloudflare-blocked (403). The site
        # publishes via FeedBurner (Google-hosted, not bot-blocked). This is the
        # curated daily-news feed; "Papers of the Week" is skipped because its
        # entries carry no dates and would bypass the 24h window.
        "name": "AlzForum (News)",
        "url": "http://feeds.feedburner.com/alzforum/PpcR",
    },
]

# Some feeds (e.g. anything behind Cloudflare) reject the default feedparser
# user-agent with HTTP 403, so present a browser-like UA on every request.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Buckets in priority order. The FIRST bucket whose keywords match wins, so
# list the highest-priority bucket first. Keywords are matched case-insensitively
# against the entry title + summary.
BUCKETS = [
    (
        "BIOMARKERS AND INDUSTRY NEWS",
        [
            "ptau", "p-tau", "p tau", "tau", "nfl", "neurofilament", "plasma",
            "fda", "assay", "biomarker", "gfap", "amyloid", "abeta", "a-beta",
            "diagnostic", "blood test", "blood-based", "csf", "cerebrospinal",
            "approval", "approved", "clearance", "cleared", "ind ",
        ],
    ),
    (
        "THERAPEUTICS AND CLINICAL TRIALS",
        [
            "treatment", "therap", "trial", "antibod", "lecanemab", "donanemab",
            "aducanumab", "drug", "phase 1", "phase 2", "phase 3", "phase i",
            "phase ii", "phase iii", "efficacy", "clinical", "dosing", "infusion",
            "vaccine", "monoclonal",
        ],
    ),
    (
        "OTHER DEVELOPMENTS",
        [],  # catch-all
    ),
]

LOOKBACK_HOURS = 24
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
CREDENTIALS_FILE = "credentials.json"


# --- Helpers ---------------------------------------------------------------

def entry_timestamp(entry):
    """Return a UTC epoch float for an entry, or None if no date is present."""
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            # feedparser returns time.struct_time in UTC; timegm treats it as UTC.
            return calendar.timegm(struct)
    return None


def classify(entry):
    """Return the bucket name for an entry based on its title + summary."""
    haystack = " ".join(
        [
            entry.get("title", ""),
            entry.get("summary", ""),
            entry.get("description", ""),
        ]
    ).lower()
    for name, keywords in BUCKETS:
        if not keywords:  # catch-all bucket
            return name
        if any(kw in haystack for kw in keywords):
            return name
    return BUCKETS[-1][0]


def collect_recent_entries():
    """Fetch all feeds and return {bucket_name: [entry_dict, ...]}."""
    cutoff = time.time() - LOOKBACK_HOURS * 3600
    buckets = {name: [] for name, _ in BUCKETS}

    for feed in FEEDS:
        print(f"Fetching: {feed['name']} ({feed['url']})", file=sys.stderr)
        parsed = feedparser.parse(feed["url"], agent=USER_AGENT)
        if parsed.bozo:
            print(f"  WARNING: feed parse issue: {parsed.bozo_exception}", file=sys.stderr)

        for entry in parsed.entries:
            ts = entry_timestamp(entry)
            # Keep entries from the last 24h. Undated entries are kept (and
            # flagged) so nothing is silently dropped.
            if ts is not None and ts < cutoff:
                continue

            bucket = classify(entry)
            buckets[bucket].append(
                {
                    "title": html.unescape(entry.get("title", "(untitled)")).strip(),
                    "link": entry.get("link", "").strip(),
                    "source": feed["name"],
                    "summary": html.unescape(entry.get("summary", "") or "").strip(),
                    "ts": ts,
                    "undated": ts is None,
                }
            )

    # Sort each bucket newest-first; undated entries sort last.
    for items in buckets.values():
        items.sort(key=lambda e: (e["ts"] is not None, e["ts"] or 0), reverse=True)

    return buckets


def render_digest(buckets):
    """Render the bucketed entries into a clean, NotebookLM-friendly text file."""
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=LOOKBACK_HOURS)

    total = sum(len(v) for v in buckets.values())
    lines = []
    lines.append("ALZHEIMER'S & NEURODEGENERATIVE DISEASE — DAILY BIOMARKER & THERAPEUTICS DIGEST")
    lines.append(f"Generated: {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"Window: last {LOOKBACK_HOURS}h (since {window_start.strftime('%Y-%m-%d %H:%M UTC')})")
    lines.append(f"Sources: {', '.join(f['name'] for f in FEEDS)}")
    lines.append(f"Total new articles: {total}")
    lines.append("")

    if total == 0:
        lines.append("No new articles in the last 24 hours.")
        return "\n".join(lines) + "\n"

    for name, _ in BUCKETS:
        items = buckets[name]
        if not items:
            continue
        lines.append("=" * 78)
        lines.append(f"{name}  ({len(items)})")
        lines.append("=" * 78)
        lines.append("")
        for i, e in enumerate(items, 1):
            date_str = (
                datetime.fromtimestamp(e["ts"], timezone.utc).strftime("%Y-%m-%d")
                if e["ts"] is not None
                else "undated"
            )
            lines.append(f"{i}. {e['title']}")
            lines.append(f"   Source: {e['source']}  |  Date: {date_str}")
            if e["link"]:
                lines.append(f"   Link: {e['link']}")
            if e["summary"]:
                summary = e["summary"]
                if len(summary) > 1200:
                    summary = summary[:1200].rsplit(" ", 1)[0] + "…"
                lines.append(f"   Summary: {summary}")
            lines.append("")

    return "\n".join(lines) + "\n"


def upload_to_drive(text, folder_id):
    """Upload the digest text as a .txt file into the given Drive folder."""
    if not os.path.exists(CREDENTIALS_FILE):
        raise FileNotFoundError(
            f"{CREDENTIALS_FILE} not found in working directory. "
            "Place the service-account key here (locally) or have the GitHub "
            "Action decode it from the GOOGLE_CREDENTIALS_BASE64 secret."
        )

    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=DRIVE_SCOPES
    )
    service = build("drive", "v3", credentials=creds)

    filename = f"AD_Digest_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.txt"
    metadata = {"name": filename, "parents": [folder_id]}
    media = MediaInMemoryUpload(text.encode("utf-8"), mimetype="text/plain", resumable=False)

    created = (
        service.files()
        .create(
            body=metadata,
            media_body=media,
            fields="id, name, webViewLink",
            supportsAllDrives=True,  # required for Shared Drive folders
        )
        .execute()
    )
    return created


# --- Main ------------------------------------------------------------------

def main():
    buckets = collect_recent_entries()
    digest = render_digest(buckets)

    # Always write a local copy. The audio step (generate_audio.py) reads this
    # file, so it must be written regardless of whether Drive is configured.
    local_name = f"digest_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.txt"
    with open(local_name, "w", encoding="utf-8") as fh:
        fh.write(digest)
    print(f"Wrote local copy: {local_name}", file=sys.stderr)

    # Drive upload is optional: skip gracefully if it isn't set up, so the rest
    # of the pipeline (audio + podcast feed) still runs.
    folder_id = os.environ.get("DRIVE_FOLDER_ID")
    if not folder_id:
        print("NOTE: DRIVE_FOLDER_ID not set — skipping Google Drive upload.", file=sys.stderr)
        return
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"NOTE: {CREDENTIALS_FILE} not found — skipping Google Drive upload.", file=sys.stderr)
        return

    created = upload_to_drive(digest, folder_id)
    print(
        f"Uploaded to Drive: {created.get('name')} "
        f"(id={created.get('id')}) {created.get('webViewLink', '')}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
