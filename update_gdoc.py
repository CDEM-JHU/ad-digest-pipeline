#!/usr/bin/env python3
"""
Overwrite a single Google Doc with today's digest, so NotebookLM can re-sync it.

Auth: OAuth *user* credentials (not a service account — service accounts can't
write to a personal Drive). The authorized-user token JSON is provided, base64,
via the GOOGLE_OAUTH_TOKEN_BASE64 env var; the target Doc id via GOOGLE_DOC_ID.
Both are produced once by gdoc_setup.py.

Run after main.py (it reuses today's digest_<date>.txt if present).
"""

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from main import collect_recent_entries, render_digest

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def load_digest():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = f"digest_{today}.txt"
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = render_digest(collect_recent_entries())
    m = re.search(r"Total new articles:\s*(\d+)", text)
    return text, (int(m.group(1)) if m else 0)


def credentials_from_env():
    blob = os.environ.get("GOOGLE_OAUTH_TOKEN_BASE64")
    if not blob:
        print("ERROR: GOOGLE_OAUTH_TOKEN_BASE64 is not set.", file=sys.stderr)
        sys.exit(1)
    info = json.loads(base64.b64decode(blob))
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        creds.refresh(Request())  # uses the refresh token
    return creds


def overwrite_doc(creds, doc_id, text):
    docs = build("docs", "v1", credentials=creds)
    doc = docs.documents().get(documentId=doc_id).execute()

    # The body always ends with a newline at the segment's final index; the last
    # element's endIndex is that boundary. Index 1 is the first editable position.
    end_index = doc["body"]["content"][-1]["endIndex"]

    requests = []
    if end_index > 2:  # doc has existing content beyond the initial empty paragraph
        requests.append(
            {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": end_index - 1}}}
        )
    requests.append({"insertText": {"location": {"index": 1}, "text": text}})

    docs.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()


def main():
    doc_id = os.environ.get("GOOGLE_DOC_ID")
    if not doc_id:
        print("ERROR: GOOGLE_DOC_ID is not set.", file=sys.stderr)
        sys.exit(1)

    text, count = load_digest()
    if count == 0:
        # Still update the Doc so the morning shows "nothing new" rather than stale content.
        print("No new articles today — updating Doc with the empty-digest notice.", file=sys.stderr)

    creds = credentials_from_env()
    overwrite_doc(creds, doc_id, text)
    print(
        f"Updated Google Doc {doc_id} ({count} articles): "
        f"https://docs.google.com/document/d/{doc_id}/edit",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
