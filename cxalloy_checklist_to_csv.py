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

extended_status here holds a 4-stage workflow (Not Started -> In Progress ->
Completed -> Reviewed), same idea as equipment's tag stages but different
stage names. It's flattened into its own columns below, keeping only the
latest date/person per stage (some stages can carry multiple historical
entries if a checklist was reopened/reworked).

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

# The checklist workflow stages returned inside extended_status, in order.
CHECKLIST_STAGES = ["not_started", "in_progress", "completed", "reviewed"]

CHECKLIST_STAGE_LABELS = {
    "not_started": "Not Started",
    "in_progress": "In Progress",
    "completed": "Completed",
    "reviewed": "Reviewed",
}

EXTENDED_STATUS_FIELDS = []
for _stage in CHECKLIST_STAGES:
    EXTENDED_STATUS_FIELDS.append(f"{_stage}_date")
    EXTENDED_STATUS_FIELDS.append(f"{_stage}_person")

FIELDS = (
    ["project_id", "checklist_id", "name", "asset_name", "asset_type",
     "discipline", "status", "status_id", "type_name", "date_created",
     "note", "assigned_name", "number"]
    + EXTENDED_STATUS_FIELDS
    + ["current_stage", "current_stage_date", "current_stage_person", "last_synced"]
)


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


def _latest_entry(date_str: str, person_str: str):
    """
    Picks the single most recent date/person pair out of a field that may
    contain multiple newline-separated historical entries (same logic used
    for equipment's tag stages).
    """
    if not date_str:
        return "", ""

    dates = [d.strip() for d in date_str.split("\n")]
    persons = [p.strip() for p in person_str.split("\n")] if person_str else []
    while len(persons) < len(dates):
        persons.append("")

    def parse(d):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(d, fmt)
            except ValueError:
                continue
        return None

    parsed = [(parse(d), d, p) for d, p in zip(dates, persons) if d]
    valid = [(dt, d, p) for dt, d, p in parsed if dt is not None]

    if valid:
        valid.sort(key=lambda x: x[0])
        _, latest_date, latest_person = valid[-1]
        return latest_date, latest_person

    if dates:
        return dates[-1], persons[-1] if persons else ""
    return "", ""


def flatten_extended_status(extended_status) -> dict:
    """
    Turns the extended_status object (a dict of workflow stages -> date/
    person, where each can hold multiple historical entries) into flat
    columns holding only the LATEST date/person per stage, plus a derived
    "current_stage" = the furthest stage reached so far.

    Handles extended_status being missing, empty, or unexpectedly not a
    dict (falls back gracefully instead of crashing the whole sync).
    """
    flat = {f: "" for f in EXTENDED_STATUS_FIELDS}
    current_stage = ""
    current_stage_date = ""
    current_stage_person = ""

    parsed_status = extended_status
    if isinstance(parsed_status, str) and parsed_status:
        try:
            parsed_status = json.loads(parsed_status)
        except (json.JSONDecodeError, TypeError):
            parsed_status = None

    if isinstance(parsed_status, dict):
        for stage in CHECKLIST_STAGES:
            raw_date = parsed_status.get(f"{stage}_date", "") or ""
            raw_person = parsed_status.get(f"{stage}_person", "") or ""
            latest_date, latest_person = _latest_entry(raw_date, raw_person)

            flat[f"{stage}_date"] = latest_date
            flat[f"{stage}_person"] = latest_person

            if latest_date:
                current_stage = CHECKLIST_STAGE_LABELS[stage]
                current_stage_date = latest_date
                current_stage_person = latest_person

    return {
        **flat,
        "current_stage": current_stage,
        "current_stage_date": current_stage_date,
        "current_stage_person": current_stage_person,
    }


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
            row = {
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
                "last_synced": now,
            }
            row.update(flatten_extended_status(c.get("extended_status")))
            writer.writerow(row)

    print(f"Wrote {len(all_checklists)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
