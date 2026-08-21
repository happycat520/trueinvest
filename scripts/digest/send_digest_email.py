#!/usr/bin/env python3
"""
CrystalWell Daily Digest — Brevo Sender (Campaigns API)
========================================================

Sends the digest already produced by generate_digest.py (HTML only - Campaigns
auto-generates the plain-text version) to the Daily Digest list via Brevo's
Campaigns API. Brevo handles list fan-out, unsubscribe links (the digest's
{{unsubscribe}} merge tag gets swapped per recipient), and suppression tracking
on its own - this script just creates the campaign and triggers the send.

Reads digest_<date>.html / .json from data/digest/ - same file layout
generate_digest.py writes. Run this as a separate step *after* generation,
not merged into it, so a generation failure never triggers a send.

ENV VARS (set as GitHub Actions secrets)
-----------------------------------------
    BREVO_API_KEY   - required, API key with campaign-create/send scope
    BREVO_LIST_ID   - required, numeric ID of the Daily Digest list in Brevo
                       (Contacts > Lists in the Brevo dashboard)

USAGE
-----
    python send_digest_email.py [--date YYYY-MM-DD] [--digest-dir PATH] [--dry-run]

--dry-run prints the subject line and first 200 chars of HTML without creating
or sending a campaign. Note this only previews content - it can't preview
recipient count the way the old Transactional script could, since Brevo
resolves list membership at send time, not campaign-creation time.
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

BREVO_API_BASE = "https://api.brevo.com/v3"
SENDER_EMAIL = "digest@crystalwellanalytics.com"
SENDER_NAME = "CrystalWell Analytics"


def get_api_key() -> str:
    key = os.environ.get("BREVO_API_KEY")
    if not key:
        sys.exit("BREVO_API_KEY is not set.")
    return key


def get_list_id() -> int:
    list_id = os.environ.get("BREVO_LIST_ID")
    if not list_id:
        sys.exit("BREVO_LIST_ID is not set - find it under Contacts > Lists in Brevo.")
    return int(list_id)


def load_digest(digest_dir: Path, digest_date: date):
    stem = digest_dir / f"digest_{digest_date.isoformat()}"
    html_path, json_path = stem.with_suffix(".html"), stem.with_suffix(".json")
    for p in (html_path, json_path):
        if not p.exists():
            sys.exit(f"Missing {p} - run generate_digest.py for {digest_date.isoformat()} first.")
    return html_path.read_text(), json.loads(json_path.read_text())


def build_subject(payload: dict, digest_date: date) -> str:
    count = payload.get("signal_count", 0)
    label = "signal" if count == 1 else "signals"
    return f"CrystalWell Daily Digest — {digest_date.strftime('%b %d')} ({count} {label})"


def create_campaign(api_key: str, list_id: int, subject: str, html: str, digest_date: date) -> int:
    headers = {"api-key": api_key, "accept": "application/json", "content-type": "application/json"}
    payload = {
        "name": f"Daily Digest {digest_date.isoformat()}",
        "subject": subject,
        "sender": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "htmlContent": html,
        "recipients": {"listIds": [list_id]},
    }
    resp = requests.post(f"{BREVO_API_BASE}/emailCampaigns", headers=headers, json=payload, timeout=30)
    if resp.status_code >= 300:
        sys.exit(f"Campaign creation failed: {resp.status_code} {resp.text[:300]}")
    return resp.json()["id"]


def send_campaign_now(api_key: str, campaign_id: int) -> None:
    headers = {"api-key": api_key, "accept": "application/json"}
    resp = requests.post(f"{BREVO_API_BASE}/emailCampaigns/{campaign_id}/sendNow", headers=headers, timeout=30)
    if resp.status_code >= 300:
        sys.exit(f"Send trigger failed for campaign {campaign_id}: {resp.status_code} {resp.text[:300]}")


def main():
    parser = argparse.ArgumentParser(description="Send the CrystalWell daily digest via Brevo Campaigns.")
    default_digest_dir = Path(__file__).resolve().parent.parent.parent / "data" / "digest"
    parser.add_argument("--date", default=None, help="Digest date, YYYY-MM-DD (default: today)")
    parser.add_argument("--digest-dir", default=str(default_digest_dir))
    parser.add_argument("--dry-run", action="store_true", help="Print subject + preview, don't create/send a campaign")
    args = parser.parse_args()

    # Mirrors generate_digest.py's own date default. If you ever run this as a
    # standalone step well after generation, pass --date explicitly.
    digest_date = date.fromisoformat(args.date) if args.date else date.today()
    digest_dir = Path(args.digest_dir)

    html, payload = load_digest(digest_dir, digest_date)
    subject = build_subject(payload, digest_date)

    if args.dry_run:
        print(f'[DRY RUN] Subject: "{subject}"')
        print(f"[DRY RUN] First 200 chars of HTML:\n{html[:200]}")
        return

    api_key = get_api_key()
    list_id = get_list_id()

    campaign_id = create_campaign(api_key, list_id, subject, html, digest_date)
    print(f"Created campaign {campaign_id}: \"{subject}\"")

    send_campaign_now(api_key, campaign_id)
    print(f"Triggered send for campaign {campaign_id}.")


if __name__ == "__main__":
    main()
