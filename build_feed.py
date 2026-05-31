#!/usr/bin/env python3
"""
Regenerate the podcast RSS feed (docs/feed.xml) and a simple index page
(docs/index.html) from the MP3s in docs/episodes/.

Hosted via GitHub Pages (Settings -> Pages -> Deploy from branch: main, /docs).
Subscribe in any podcast app to:  <base>/feed.xml

The public base URL is derived from GITHUB_REPOSITORY (owner/repo) as
https://<owner>.github.io/<repo>, or overridden with PAGES_BASE_URL.
"""

import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

EPISODES_DIR = os.path.join("docs", "episodes")
FEED_PATH = os.path.join("docs", "feed.xml")
INDEX_PATH = os.path.join("docs", "index.html")

PODCAST_TITLE = "AD Daily — Alzheimer's Biomarkers & Therapeutics"
PODCAST_DESC = (
    "An automated daily audio brief on neurodegenerative-disease biomarkers and "
    "treatments, generated from AlzForum and the Alzheimer's & Dementia journal."
)
AUTHOR = "AD Daily (automated)"
LANGUAGE = "en-us"


def base_url():
    override = os.environ.get("PAGES_BASE_URL")
    if override:
        return override.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        print(
            "WARNING: GITHUB_REPOSITORY not set and no PAGES_BASE_URL; using a "
            "placeholder base URL. The feed will need regenerating in CI.",
            file=sys.stderr,
        )
        return "https://example.github.io/ad-digest-pipeline"
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}"


def episode_pubdate(date_str):
    """RFC-822 date for an episode, anchored to 06:00 UTC on its date."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(
        hour=6, tzinfo=timezone.utc
    )
    return format_datetime(dt)


def collect_episodes():
    if not os.path.isdir(EPISODES_DIR):
        return []
    eps = []
    for fn in os.listdir(EPISODES_DIR):
        if not fn.lower().endswith(".mp3"):
            continue
        # Expect AD_Digest_YYYY-MM-DD.mp3
        date_str = fn.replace("AD_Digest_", "").replace(".mp3", "")
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        eps.append(
            {
                "file": fn,
                "date": date_str,
                "size": os.path.getsize(os.path.join(EPISODES_DIR, fn)),
            }
        )
    # newest first
    eps.sort(key=lambda e: e["date"], reverse=True)
    return eps


def build_rss(base, episodes):
    now = format_datetime(datetime.now(timezone.utc))
    items = []
    for ep in episodes:
        url = f"{base}/episodes/{ep['file']}"
        title = f"AD Daily — {ep['date']}"
        items.append(
            "    <item>\n"
            f"      <title>{escape(title)}</title>\n"
            f"      <description>{escape(PODCAST_DESC)}</description>\n"
            f"      <pubDate>{episode_pubdate(ep['date'])}</pubDate>\n"
            f'      <enclosure url="{escape(url)}" length="{ep["size"]}" type="audio/mpeg"/>\n'
            f"      <guid isPermaLink=\"true\">{escape(url)}</guid>\n"
            f"      <itunes:author>{escape(AUTHOR)}</itunes:author>\n"
            f"      <itunes:explicit>false</itunes:explicit>\n"
            "    </item>"
        )
    items_xml = "\n".join(items)
    feed_url = f"{base}/feed.xml"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" '
        'xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" '
        'xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{escape(PODCAST_TITLE)}</title>\n"
        f"    <link>{escape(base)}</link>\n"
        f"    <description>{escape(PODCAST_DESC)}</description>\n"
        f"    <language>{LANGUAGE}</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f'    <atom:link href="{escape(feed_url)}" rel="self" type="application/rss+xml"/>\n'
        f"    <itunes:author>{escape(AUTHOR)}</itunes:author>\n"
        f"    <itunes:summary>{escape(PODCAST_DESC)}</itunes:summary>\n"
        f"    <itunes:explicit>false</itunes:explicit>\n"
        '    <itunes:category text="Science"/>\n'
        f"    <itunes:owner><itunes:name>{escape(AUTHOR)}</itunes:name></itunes:owner>\n"
        f"{items_xml}\n"
        "  </channel>\n"
        "</rss>\n"
    )


def build_index(base, episodes):
    rows = "\n".join(
        f'      <li><a href="episodes/{e["file"]}">AD Daily — {e["date"]}</a> '
        f"({e['size']/1_000_000:.1f} MB)</li>"
        for e in episodes
    )
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
        f"<title>{escape(PODCAST_TITLE)}</title>\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "</head><body style=\"font-family:system-ui;max-width:680px;margin:2rem auto;padding:0 1rem\">\n"
        f"<h1>{escape(PODCAST_TITLE)}</h1>\n"
        f"<p>{escape(PODCAST_DESC)}</p>\n"
        f'<p><strong>Subscribe in your podcast app:</strong><br><code>{escape(base)}/feed.xml</code></p>\n'
        f"<h2>Episodes</h2>\n<ul>\n{rows}\n</ul>\n"
        "</body></html>\n"
    )


def main():
    base = base_url()
    episodes = collect_episodes()
    os.makedirs("docs", exist_ok=True)

    with open(FEED_PATH, "w", encoding="utf-8") as fh:
        fh.write(build_rss(base, episodes))
    with open(INDEX_PATH, "w", encoding="utf-8") as fh:
        fh.write(build_index(base, episodes))

    print(f"Wrote {FEED_PATH} and {INDEX_PATH} with {len(episodes)} episode(s).", file=sys.stderr)
    print(f"Feed URL: {base}/feed.xml", file=sys.stderr)


if __name__ == "__main__":
    main()
