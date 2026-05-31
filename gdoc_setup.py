#!/usr/bin/env python3
"""
ONE-TIME local setup for the Google Doc delivery path. Run on your Mac.

Prereqs (done once in Google Cloud Console — see the instructions Claude gave you):
  - Google Docs API + Google Drive API enabled
  - OAuth consent screen configured, publishing status = "In production"
  - An OAuth "Desktop app" client; its JSON downloaded next to this file as
    client_secret.json

What this does:
  1. Opens your browser to authorize (pick your PERSONAL Google account).
  2. Creates a Google Doc named "AD Daily — Today" in your Drive.
  3. Stores the resulting credentials + Doc id as GitHub repo secrets via `gh`
     (nothing sensitive is printed to the terminal).

Usage:
  source .venv311/bin/activate
  python gdoc_setup.py
"""

import base64
import subprocess
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

REPO = "CDEM-JHU/ad-digest-pipeline"
CLIENT_SECRET_FILE = "client_secret.json"
SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.file",
]


def set_secret(name, value):
    subprocess.run(
        ["gh", "secret", "set", name, "-R", REPO, "--body", value],
        check=True,
    )
    print(f"  set secret: {name}")


def main():
    print("Opening browser for Google authorization…")
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    print("Creating the Google Doc…")
    docs = build("docs", "v1", credentials=creds)
    doc = docs.documents().create(body={"title": "AD Daily — Today"}).execute()
    doc_id = doc["documentId"]

    print("Storing secrets in GitHub via gh (not printing them)…")
    token_b64 = base64.b64encode(creds.to_json().encode()).decode()
    set_secret("GOOGLE_OAUTH_TOKEN_BASE64", token_b64)
    set_secret("GOOGLE_DOC_ID", doc_id)

    print("\nDone. Your daily Doc (add THIS as a NotebookLM source):")
    print(f"  https://docs.google.com/document/d/{doc_id}/edit")


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError:
        print(f"ERROR: {CLIENT_SECRET_FILE} not found in this folder. Download your "
              "OAuth Desktop client JSON and save it as client_secret.json here.",
              file=sys.stderr)
        sys.exit(1)
