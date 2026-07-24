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

# The tag/commissioning stages returned inside extended_status, in workflow order.
# Each stage has a "<stage>_date" and "<stage>_person" field.
TAG_STAGES = [
    "no_tag",
    "l1_red_tag",
    "conditional_yellow_tag",
    "l2_yellow_tag",
    "energized",
    "l3_green_tag",
    "l4_blue_tag",
    "l5_white_tag",
]

TAG_STAGE_LABELS = {
    "no_tag": "No Tag",
    "l1_red_tag": "L1 Red Tag",
    "conditional_yellow_tag": "Conditional Yellow Tag",
    "l2_yellow_tag": "L2 Yellow Tag",
    "energized": "Energized",
    "l3_green_tag": "L3 Green Tag",
    "l4_blue_tag": "L4 Blue Tag",
    "l5_white_tag": "L5 White Tag",
}

EXTENDED_STATUS_FIELDS = []
for _stage in TAG_STAGES:
    EXTENDED_STATUS_FIELDS.append(f"{_stage}_date")
    EXTENDED_STATUS_FIELDS.append(f"{_stage}_person")

FIELDS = (
    ["project_id", "equipment_id", "name", "type", "discipline",
     "building", "floor", "space", "status"]
    + EXTENDED_STATUS_FIELDS
    + ["current_stage", "current_stage_date", "current_stage_person", "last_synced"]
)


def flatten_extended_status(extended_status) -> dict:
    """
    Turns the extended_status object (a dict of tag stages -> date/person)
    into flat columns, plus a derived "current_stage" = the furthest stage
    reached so far (the last one in TAG_STAGES order that has a non-empty date).

    Handles extended_status being missing, empty, or unexpectedly a plain
    string (falls back gracefully instead of crashing the whole sync).
    """
    flat = {f: "" for f in EXTENDED_STATUS_FIELDS}
    current_stage = ""
    current_stage_date = ""
    current_stage_person = ""

    if isinstance(extended_status, dict):
        for stage in TAG_STAGES:
            date_val = extended_status.get(f"{stage}_date", "") or ""
            person_val = extended_status.get(f"{stage}_person", "") or ""
            flat[f"{stage}_date"] = date_val
            flat[f"{stage}_person"] = person_val
            # Multiple dates can appear newline-separated (repeat tagging);
            # take the most recent one for the "current stage" summary.
            if date_val.strip():
                current_stage = TAG_STAGE_LABELS[stage]
                current_stage_date = date_val.strip().split("\n")[-1]
                current_stage_person = person_val.strip().split("\n")[-1]

    return {
        **flat,
        "current_stage": current_stage,
        "current_stage_date": current_stage_date,
        "current_stage_person": current_stage_person,
    }


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
            row = {
                "project_id": eq.get("project_id", eq.get("_project_id", "")),
                "equipment_id": eq.get("equipment_id", ""),
                "name": eq.get("name", ""),
                "type": eq.get("type", ""),
                "discipline": eq.get("discipline", ""),
                "building": eq.get("building", ""),
                "floor": eq.get("floor", ""),
                "space": eq.get("space", ""),
                "status": eq.get("status", ""),
                "last_synced": now,
            }
            row.update(flatten_extended_status(eq.get("extended_status")))
            writer.writerow(row)

    print(f"Wrote {len(all_equipment)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
