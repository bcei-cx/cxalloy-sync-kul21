"""
CxAlloy checklists -> CSV file sync.

Pulls all checklists (with extended_status) for one or more CxAlloy projects
and writes them to a CSV file in this repo. Runs as part of the same daily
GitHub Actions workflow as the equipment sync.

Checklists use a different request pattern than equipment:
  - POST instead of GET, with a JSON body describing filters
  - The signature is computed over the JSON body + timestamp (not just
    the timestamp alone)
  - The response is a wrapper: {description, page, records, total_count} -
    pagination is driven by total_count, not by counting a returned batch

NOTE: extended_status is written out as raw JSON text in this first pass,
since (unlike equipment's tag-stage structure) we haven't seen its shape
yet. Once you've run this once and shared a sample, we can flatten it into
proper columns the same way we did for equipment.

Required environment variables (same ones used by the equipment script):
  CXALLOY_IDENTIFIER  - API key identifier from CxAlloy       (Secret)
  CXALLOY_SECRET      - API key secret from CxAlloy           (Secret)
  CXALLOY_PROJECT_ID  - one or more numeric project ids,      (Variable)
                        comma-separated, e.g. "67,89,102"
"""

import os
import time
import hmac
import hashlib
import json
import csv
from datetime import datetime, timezone

import requests

CXALLOY_IDENTIFIER = os.environ["CXALLOY_IDENTIFIER"]
CXALLOY_SECRET = os.environ["CXALLOY_SECRET"]

CXALLOY_PROJECT_IDS = [
    p.strip() for p in os.environ["CXALLOY_PROJECT_ID"].split(",") if p.strip()
]

CXALLOY_BASE_URL = "https://tq.cxalloy.com/api/v1"
OUTPUT_PATH = "data/checklist_status.csv"
PER_PAGE = 500

FIELDS = [
    "project_id", "checklist_id", "name", "asset_name", "asset_type",
    "discipline", "status", "status_id", "type_name", "date_created",
    "note", "assigned_name", "number", "extended_status_raw", "last_synced",
]


def cxalloy_headers(body_str: str) -> dict:
    """
    Builds auth headers for a POST request. Unlike the equipment GET
    endpoint, the signature here covers the JSON body PLUS the timestamp.
    """
    timestamp = int(time.time())
    message = body_str + str(timestamp)
    signature = hmac.new(
        CXALLOY_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "cxalloy-identifier": CXALLOY_IDENTIFIER,
        "cxalloy-signature": signature,
        "cxalloy-timestamp": str(timestamp),
        "user-agent": "GitHubActions-CxAlloySync/1.0",
    }


def get_checklists_for_project(project_id: str) -> list:
    checklists = []
    page = 1

    while True:
        body = {
            "project_id": int(project_id),
            "include": ["extended_status"],
            "page": page,
            "perpage": PER_PAGE,
        }
        # Serialize once, deterministically - the exact same string is used
        # both to compute the signature and as the actual request body, so
        # they can't ever drift apart from each other.
        body_str = json.dumps(body, separators=(",", ":"))

        resp = requests.post(
            f"{CXALLOY_BASE_URL}/checklist",
            headers=cxalloy_headers(body_str),
            data=body_str,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()

        records = payload.get("records", [])
        total_count = payload.get("total_count", 0)

        checklists.extend(records)

        if not records or len(checklists) >= total_count:
            break
        page += 1

    return checklists


def serialize_extended_status(extended_status) -> str:
    """Keeps extended_status intact as JSON text so we can inspect its
    real shape before deciding how to flatten it."""
    if extended_status is None:
        return ""
    if isinstance(extended_status, str):
        return extended_status
    try:
        return json.dumps(extended_status, ensure_ascii=False)
    except TypeError:
        return str(extended_status)


def main():
    print(f"Projects to sync: {CXALLOY_PROJECT_IDS}")

    all_checklists = []
    for project_id in CXALLOY_PROJECT_IDS:
        print(f"Fetching checklists for project {project_id}...")
        checklists = get_checklists_for_project(project_id)
        print(f"  -> {len(checklists)} records")
        for c in checklists:
            c["_project_id"] = project_id
        all_checklists.extend(checklists)

    print(f"Total checklist records across all projects: {len(all_checklists)}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for c in all_checklists:
            writer.writerow({
                "project_id": c.get("project_id", c.get("_project_id", "")),
                "checklist_id": c.get("checklist_id", ""),
                "name": c.get("name", ""),
                "asset_name": c.get("asset_name", ""),
                "asset_type": c.get("asset_type", ""),
                "discipline": c.get("discipline", ""),
                "status": c.get("status", ""),
                "status_id": c.get("status_id", ""),
                "type_name": c.get("type_name", ""),
                "date_created": c.get("date_created", ""),
                "note": c.get("note", ""),
                "assigned_name": c.get("assigned_name", ""),
                "number": c.get("number", ""),
                "extended_status_raw": serialize_extended_status(c.get("extended_status")),
                "last_synced": now,
            })

    print(f"Wrote {len(all_checklists)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
