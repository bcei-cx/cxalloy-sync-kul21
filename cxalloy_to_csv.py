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

# Position of each stage in the workflow, e.g. no_tag=0, l1_red_tag=1, ...
STAGE_INDEX = {stage: i for i, stage in enumerate(TAG_STAGES)}

# Reverse of TAG_STAGE_LABELS: "L1 Red Tag" -> "l1_red_tag", used to translate
# the equipment's actual `status` field into a position in the workflow.
LABEL_TO_STAGE = {label: stage for stage, label in TAG_STAGE_LABELS.items()}

FIELDS = (
    ["project_id", "equipment_id", "name", "type", "discipline",
     "building", "floor", "space", "status"]
    + EXTENDED_STATUS_FIELDS
    + ["current_stage", "current_stage_date", "current_stage_person", "last_synced"]
)


def _latest_entry(date_str: str, person_str: str):
    """
    A stage's date/person fields can contain multiple entries separated by
    newlines (equipment gets tagged, un-tagged, and re-tagged over time).
    This picks out the single most recent entry by actually parsing and
    comparing the dates, rather than assuming the last item listed is newest.

    Returns (latest_date, latest_person) as plain strings, or ("", "") if
    there's nothing usable.
    """
    if not date_str:
        return "", ""

    dates = [d.strip() for d in date_str.split("\n")]
    persons = [p.strip() for p in person_str.split("\n")] if person_str else []
    # If a person entry is missing for some date, pad so indexes still line up
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

    # Nothing parsed successfully (unexpected date format) - fall back to
    # the last listed entry rather than losing the data entirely.
    if dates:
        return dates[-1], persons[-1] if persons else ""
    return "", ""


def flatten_extended_status(extended_status) -> dict:
    """
    Turns the extended_status object (a dict of tag stages -> date/person,
    where each can hold multiple newline-separated historical entries) into
    flat columns holding only the LATEST date/person per stage, plus a
    derived "current_stage" = the furthest stage reached so far.

    Handles extended_status being missing, empty, or unexpectedly a plain
    string (falls back gracefully instead of crashing the whole sync).
    """
    flat = {f: "" for f in EXTENDED_STATUS_FIELDS}
    current_stage = ""
    current_stage_date = ""
    current_stage_person = ""

    if isinstance(extended_status, dict):
        for stage in TAG_STAGES:
            raw_date = extended_status.get(f"{stage}_date", "") or ""
            raw_person = extended_status.get(f"{stage}_person", "") or ""
            latest_date, latest_person = _latest_entry(raw_date, raw_person)

            flat[f"{stage}_date"] = latest_date
            flat[f"{stage}_person"] = latest_person

            if latest_date:
                current_stage = TAG_STAGE_LABELS[stage]
                current_stage_date = latest_date
                current_stage_person = latest_person

    return {
        **flat,
        "current_stage": current_stage,
        "current_stage_date": current_stage_date,
        "current_stage_person": current_stage_person,
    }


def clean_stale_future_dates(flat: dict, status: str, unmatched_statuses: set) -> dict:
    """
    Uses the equipment's actual `status` field (the ground truth for where
    it sits RIGHT NOW) to invalidate any stage dates that shouldn't still
    be there.

    Why this is needed: extended_status keeps historical dates forever,
    even after a rollback. If equipment reached L2 Yellow Tag and was later
    rolled back to L1 Red Tag, the old l2_yellow_tag_date is still sitting
    in the data - which would incorrectly make it look like it's still at
    (or has reached) L2 in any date-based check. Since `status` reflects
    where the equipment actually is now, any stage AFTER that point gets
    cleared out here.

    If `status` doesn't match any known stage label exactly, nothing is
    cleared (safer to leave data alone than guess wrong) - the unmatched
    value is recorded in `unmatched_statuses` so it can be reported once,
    at the end of the run, instead of failing silently.
    """
    stage_key = LABEL_TO_STAGE.get((status or "").strip())

    if stage_key is None:
        if status:
            unmatched_statuses.add(status)
        return flat

    cutoff_index = STAGE_INDEX[stage_key]

    for stage, idx in STAGE_INDEX.items():
        if idx > cutoff_index:
            flat[f"{stage}_date"] = ""
            flat[f"{stage}_person"] = ""

    # Recompute current_stage/date/person now that stale future dates are
    # gone - scan stages up to (and including) the cutoff, in order, so the
    # furthest one that still has a real date wins. Normally this will just
    # be the status's own stage, but this also covers the rare case where
    # that stage's own date is unexpectedly blank.
    current_stage = ""
    current_stage_date = ""
    current_stage_person = ""
    for stage, idx in STAGE_INDEX.items():
        if idx <= cutoff_index and flat.get(f"{stage}_date"):
            current_stage = TAG_STAGE_LABELS[stage]
            current_stage_date = flat[f"{stage}_date"]
            current_stage_person = flat[f"{stage}_person"]

    flat["current_stage"] = current_stage
    flat["current_stage_date"] = current_stage_date
    flat["current_stage_person"] = current_stage_person

    return flat


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
    unmatched_statuses = set()

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for eq in all_equipment:
            status = eq.get("status", "")
            row = {
                "project_id": eq.get("project_id", eq.get("_project_id", "")),
                "equipment_id": eq.get("equipment_id", ""),
                "name": eq.get("name", ""),
                "type": eq.get("type", ""),
                "discipline": eq.get("discipline", ""),
                "building": eq.get("building", ""),
                "floor": eq.get("floor", ""),
                "space": eq.get("space", ""),
                "status": status,
                "last_synced": now,
            }
            flat = flatten_extended_status(eq.get("extended_status"))
            flat = clean_stale_future_dates(flat, status, unmatched_statuses)
            row.update(flat)
            writer.writerow(row)

    print(f"Wrote {len(all_equipment)} rows to {OUTPUT_PATH}")

    if unmatched_statuses:
        print(
            f"WARNING: {len(unmatched_statuses)} distinct status value(s) didn't match "
            f"any known tag stage, so rollback cleanup was skipped for those rows: "
            f"{sorted(unmatched_statuses)}"
        )


if __name__ == "__main__":
    main()
