#!/usr/bin/env python3
"""
Turn the daily digest text into a two-host podcast MP3.

Two stages, deliberately decoupled:
  1. Gemini (via litellm) writes the two-host script from the digest. We control
     this prompt entirely — no external/untrusted prompt templates are pulled.
  2. Podcastfy renders that script to audio with Microsoft Edge TTS (free, no key)
     via its transcript-file path, which skips all content generation.

Requirements: GEMINI_API_KEY env var (free from Google AI Studio), and ffmpeg
installed (for audio merge).

The finished episode is written to docs/episodes/AD_Digest_YYYY-MM-DD.mp3 for
build_feed.py to publish. If there were no new articles, no episode is produced.
"""

import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

from main import collect_recent_entries, render_digest

EPISODES_DIR = os.path.join("docs", "episodes")
KEEP_EPISODES = 30  # prune older episodes to keep the repo small
# litellm model id, provider-prefixed. Gemini 2.5 Flash is free-tier eligible.
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini/gemini-2.5-flash")
# litellm reads the provider key from the environment automatically; for the
# gemini/ provider that's GEMINI_API_KEY.
LLM_API_KEY_ENV = os.environ.get("LLM_API_KEY_ENV", "GEMINI_API_KEY")

TRANSCRIPT_PROMPT = """\
You are scripting a daily two-host audio briefing called "AD Daily" for a \
PhD-level expert in neurodegenerative-disease diagnostics (plasma p-tau217, \
amyloid PET, GFAP, NfL, lecanemab/donanemab are all assumed knowledge — never \
define basic terms or oversimplify).

HOSTS:
- Person1 = a neuroscience correspondent who concisely summarizes each development.
- Person2 = a skeptical expert who probes methodology, cohorts, effect sizes, and clinical relevance.

INSTRUCTIONS:
- Base the conversation ONLY on the digest below. Never invent findings, numbers, \
study names, or citations that are not present.
- Order: brief intro (date + headline count) -> Biomarkers & industry news (most \
detail) -> Therapeutics & clinical trials -> Other developments (brief) -> a \
one-sentence wrap-up of what matters most today. Skip any empty section.
- Be precise and technical; name the specific assays/cohorts mentioned; flag \
methodological caveats. Brisk and high-signal. Target roughly 1500-2000 words.

OUTPUT FORMAT — CRITICAL:
- Output ONLY the dialogue, nothing else (no preamble, no markdown, no stage directions).
- Wrap every turn in <Person1>...</Person1> or <Person2>...</Person2> tags.
- Strictly alternate, starting with <Person1> and ending with </Person2>.

DIGEST:
---
{digest}
---
"""


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


def generate_transcript(digest_text):
    """Have Claude write the two-host script in Podcastfy's Person-tag markup."""
    import litellm

    resp = litellm.completion(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": TRANSCRIPT_PROMPT.format(digest=digest_text)}],
        max_tokens=4096,
        temperature=0.6,
    )
    return clean_transcript(resp.choices[0].message.content)


def clean_transcript(text):
    """Reconstruct clean, balanced Person tags from possibly-imperfect LLM output.

    LLMs often drop or duplicate a closing tag. Rather than fail, we treat each
    opening <Person1>/<Person2> as the start of a turn that runs until the next
    opening tag, strip any stray tags from the content, and re-emit well-formed,
    balanced markup that Podcastfy's TTS can split reliably.
    """
    # Each turn = an opening tag + everything up to the next opening tag (or end).
    turns = re.findall(
        r"<\s*Person\s*([12])\s*>(.*?)(?=<\s*Person\s*[12]\s*>|$)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    cleaned = []
    for speaker, content in turns:
        # Remove any stray open/close Person tags left inside the captured content.
        content = re.sub(r"<\s*/?\s*Person\s*[12]\s*>", "", content, flags=re.IGNORECASE)
        content = content.strip()
        if content:
            cleaned.append(f"<Person{speaker}>{content}</Person{speaker}>")

    if len(cleaned) < 2:
        raise ValueError(
            f"Could not recover a usable dialogue from model output "
            f"({len(cleaned)} turn(s) found)."
        )
    return "".join(cleaned)


def prune_old_episodes():
    if not os.path.isdir(EPISODES_DIR):
        return
    mp3s = sorted(f for f in os.listdir(EPISODES_DIR) if f.lower().endswith(".mp3"))
    for stale in mp3s[:-KEEP_EPISODES]:
        os.remove(os.path.join(EPISODES_DIR, stale))
        print(f"Pruned old episode: {stale}", file=sys.stderr)


def main():
    if not os.environ.get(LLM_API_KEY_ENV):
        print(f"ERROR: {LLM_API_KEY_ENV} is not set.", file=sys.stderr)
        sys.exit(1)

    digest_text, count, today = load_or_build_digest()
    if count == 0:
        print("No new articles today — skipping episode generation.", file=sys.stderr)
        return

    print(f"Writing script from {count} articles with {LLM_MODEL}…", file=sys.stderr)
    transcript = generate_transcript(digest_text)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(transcript)
        transcript_path = tf.name

    # Render audio only (transcript_file path skips content generation entirely).
    from podcastfy.client import generate_podcast

    print("Rendering audio with Edge TTS…", file=sys.stderr)
    audio_path = generate_podcast(transcript_file=transcript_path, tts_model="edge")
    if not audio_path or not os.path.exists(audio_path):
        print("ERROR: Podcastfy did not return an audio file.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(EPISODES_DIR, exist_ok=True)
    dest = os.path.join(EPISODES_DIR, f"AD_Digest_{today}.mp3")
    shutil.copyfile(audio_path, dest)
    print(f"Episode written: {dest} ({os.path.getsize(dest)/1_000_000:.1f} MB)", file=sys.stderr)

    prune_old_episodes()


if __name__ == "__main__":
    main()
