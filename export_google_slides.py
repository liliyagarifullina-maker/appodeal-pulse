#!/usr/bin/env python3
"""
Appodeal Pulse — Google Slides Export

Uploads the daily PPTX to Google Drive, which auto-converts it
to Google Slides format. Each day = a new presentation.

Requires:
  - GOOGLE_SERVICE_ACCOUNT_JSON env var (JSON string of service account credentials)
  - GOOGLE_DRIVE_FOLDER_ID env var (target Google Drive folder ID)
"""

import json
import os
import sys
from datetime import datetime

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

import config


SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def get_drive_service():
    """Build Google Drive API service from env credentials."""
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_json:
        return None

    creds_info = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def upload_to_google_slides(pptx_path, folder_id=None):
    """Upload a PPTX file to Google Drive and convert to Google Slides.

    Args:
        pptx_path: Path to the .pptx file to upload.
        folder_id: Google Drive folder ID. If None, reads from env.

    Returns:
        URL of the created Google Slides presentation, or None on failure.
    """
    if not os.path.exists(pptx_path):
        print(f"  [Google Slides] PPTX not found: {pptx_path}")
        return None

    service = get_drive_service()
    if service is None:
        print("  [Google Slides] Skipped — no GOOGLE_SERVICE_ACCOUNT_JSON set")
        return None

    folder_id = folder_id or os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")
    if not folder_id:
        print("  [Google Slides] Skipped — no GOOGLE_DRIVE_FOLDER_ID set")
        return None

    today = datetime.now().strftime("%Y-%m-%d")
    file_name = f"Pulse {today}"

    file_metadata = {
        "name": file_name,
        "mimeType": "application/vnd.google-apps.presentation",
        "parents": [folder_id],
    }

    media = MediaFileUpload(
        pptx_path,
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        resumable=True,
    )

    result = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    file_id = result.get("id")
    link = result.get("webViewLink", f"https://docs.google.com/presentation/d/{file_id}")

    print(f"  [Google Slides] Uploaded → {link}")
    return link


# ── Entry point ─────────────────────────────────────────────

if __name__ == "__main__":
    # Find the latest PPTX in archive
    archive_dir = os.path.join(config.DATA_DIR, "archive")
    if not os.path.exists(archive_dir):
        print("ERROR: No archive directory found. Run generate.py first.")
        sys.exit(1)

    pptx_files = sorted(
        [f for f in os.listdir(archive_dir) if f.endswith(".pptx")],
        reverse=True,
    )

    if not pptx_files:
        print("ERROR: No PPTX files found in archive.")
        sys.exit(1)

    latest = os.path.join(archive_dir, pptx_files[0])
    print(f"  Uploading {latest} to Google Slides...")
    link = upload_to_google_slides(latest)

    if link:
        print(f"  Done! → {link}")
    else:
        print("  Upload failed or skipped.")
