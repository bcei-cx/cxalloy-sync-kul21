"""
CxAlloy -> CSV file sync.

Pulls all equipment (with extended_status) for one or more CxAlloy projects
and writes it to a single CSV file in this repo. A GitHub Actions workflow
runs this daily and commits the updated file. Power BI reads the CSV
directly from GitHub.

Required environment variables:
  CXALLOY_IDENTIFIER  - API key identifier from CxAlloy       (Secret)
  CXALLOY_SECRET      - API key secret from CxAlloy           (Secret)
  CXALLOY_PROJECT_ID  - one or more numeric project ids,      (Variable)
                        comma-separated, e.g. "67,89,102"
"""

import os
import time
import hmac
import hashlib
import csv
from datetime import datetime, timezone

import requests

CXALLOY_IDENTIFIER = os.environ["CXALLOY_IDENTIFIER"]
CXALLOY_SECRET = os.environ["CXALLOY_SECRET"]

# Split "67,89,102" into ["67", "89", "102"], ignoring blanks/spaces
CXALLOY_PROJECT_IDS = [
    p.strip() for p in os.environ["CXALLOY_PROJECT_ID"].split(",") if p.strip()
]

CXALLOY_BASE_URL = "https://tq.cxalloy.com/api/v1"
OUTPUT_PATH = "data/equipment_status.csv"

FIELDS = [
    "project_id", "equipment_id", "name", "type", "discipline",
    "building", "floor", "space", "status", "extended_status", "last_synced",
]


def cxalloy_headers() -> dict:
    """Builds the required auth headers, signing the current timestamp."""
    timestamp = int(time.time())
    signature = hmac.new(
        CXALLOY_SECRET.encode("utf-8"),
        str(timestamp).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "cxalloy-identifier": CXALLOY_IDENTIFIER,
        "cxalloy-signature": signature,
        "cxalloy-timestamp": str(timestamp),
        "user-agent": "GitHubActions-CxAlloySync/1.0",
    }


def get_equipment_for_project(project_id: str) -> list:
    """Handles pagination - CxAlloy caps each page at 500 records."""
    equipment = []
    page = 1
    while True:
        params = {"project_id": project_id, "include": "extended_status", "page": page}
        resp = requests.get(
            f"{CXALLOY_BASE_URL}/equipment",
            headers=cxalloy_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            batch = data
        elif isinstance(data, dict):
            batch = data.get("data") or data.get("equipment") or []
        else:
            batch = []

        if not batch:
            break

        equipment.extend(batch)

        if len(batch) < 500:
            break
        page += 1

    return equipment


def main():
    print(f"Projects to sync: {CXALLOY_PROJECT_IDS}")

    all_equipment = []
    for project_id in CXALLOY_PROJECT_IDS:
        print(f"Fetching equipment for project {project_id}...")
        equipment = get_equipment_for_project(project_id)
        print(f"  -> {len(equipment)} records")
        for eq in equipment:
            eq["_project_id"] = project_id  # tag in case CxAlloy omits it
        all_equipment.extend(equipment)

    print(f"Total equipment records across all projects: {len(all_equipment)}")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for eq in all_equipment:
            writer.writerow({
                "project_id": eq.get("project_id", eq.get("_project_id", "")),
                "equipment_id": eq.get("equipment_id", ""),
                "name": eq.get("name", ""),
                "type": eq.get("type", ""),
                "discipline": eq.get("discipline", ""),
                "building": eq.get("building", ""),
                "floor": eq.get("floor", ""),
                "space": eq.get("space", ""),
                "status": eq.get("status", ""),
                "extended_status": eq.get("extended_status", ""),
                "last_synced": now,
            })

    print(f"Wrote {len(all_equipment)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
