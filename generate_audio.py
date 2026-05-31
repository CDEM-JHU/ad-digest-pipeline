#!/usr/bin/env python3
"""
Turn the daily digest text into a two-host podcast MP3 via Podcastfy.

- LLM (script writing): Anthropic Claude  -> needs ANTHROPIC_API_KEY
- Voices (TTS): Microsoft Edge (free)     -> no key required
- ffmpeg must be installed for audio stitching.

The finished episode is written to docs/episodes/AD_Digest_YYYY-MM-DD.mp3 so that
build_feed.py can publish it on GitHub Pages as a podcast.

If there were no new articles in the digest, no episode is produced (exit 0).
"""

import os
import re
import shutil
import sys
from datetime import datetime, timezone

from main import collect_recent_entries, render_digest

EPISODES_DIR = os.path.join("docs", "episodes")
KEEP_EPISODES = 30  # prune older episodes to keep the repo small
# litellm-style model id. If Podcastfy/litellm fails to detect the provider,
# set ANTHROPIC_MODEL to "anthropic/claude-sonnet-4-6".
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")

CONVERSATION_CONFIG = {
    "podcast_name": "AD Daily",
    "podcast_tagline": "Your morning brief on Alzheimer's biomarkers and therapeutics",
    "output_language": "English",
    "creativity": 0.6,
    "conversation_style": ["analytical", "concise", "expert-to-expert"],
    "roles_person1": "neuroscience correspondent who summarizes each development",
    "roles_person2": "skeptical expert who probes methodology and clinical relevance",
    "dialogue_structure": [
        "Brief intro with the date and headline count",
        "Biomarkers and industry news (most detail)",
        "Therapeutics and clinical trials",
        "Other developments (brief)",
        "One-line wrap-up of what matters most today",
    ],
    "engagement_techniques": ["rhetorical questions", "analogies"],
    "word_count": 1800,  # ~11-13 minutes of audio
    "user_instructions": (
        "The listener is a PhD-level expert in neurodegenerative disease diagnostics. "
        "Do NOT oversimplify or define basic terms (p-tau217, amyloid PET, GFAP, NfL are known). "
        "Be precise and technical, name the specific assays/studies/cohorts mentioned, and flag "
        "methodological caveats. Never invent findings, numbers, or citations not present in the "
        "source text. If a section has no items, skip it. Keep it brisk and high-signal."
    ),
}


def load_or_build_digest():
    """Prefer the digest file main.py already wrote today; otherwise build it."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"digest_{today}.txt"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = render_digest(collect_recent_entries())

    m = re.search(r"Total new articles:\s*(\d+)", text)
    count = int(m.group(1)) if m else 0
    return text, count, today


def prune_old_episodes():
    if not os.path.isdir(EPISODES_DIR):
        return
    mp3s = sorted(
        f for f in os.listdir(EPISODES_DIR) if f.lower().endswith(".mp3")
    )
    for stale in mp3s[:-KEEP_EPISODES]:
        os.remove(os.path.join(EPISODES_DIR, stale))
        print(f"Pruned old episode: {stale}", file=sys.stderr)


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    digest_text, count, today = load_or_build_digest()
    if count == 0:
        print("No new articles today — skipping episode generation.", file=sys.stderr)
        return

    # Imported here so a missing/heavy dependency only matters when we actually
    # generate audio (keeps `import generate_audio` cheap for the no-news path).
    from podcastfy.client import generate_podcast

    print(f"Generating podcast from {count} articles…", file=sys.stderr)
    audio_path = generate_podcast(
        text=digest_text,
        llm_model_name=ANTHROPIC_MODEL,
        api_key_label="ANTHROPIC_API_KEY",
        tts_model="edge",
        conversation_config=CONVERSATION_CONFIG,
    )
    if not audio_path or not os.path.exists(audio_path):
        print("ERROR: Podcastfy did not return an audio file.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(EPISODES_DIR, exist_ok=True)
    dest = os.path.join(EPISODES_DIR, f"AD_Digest_{today}.mp3")
    shutil.copyfile(audio_path, dest)
    size = os.path.getsize(dest)
    print(f"Episode written: {dest} ({size/1_000_000:.1f} MB)", file=sys.stderr)

    prune_old_episodes()


if __name__ == "__main__":
    main()
