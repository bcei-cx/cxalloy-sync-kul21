"""
CxAlloy checklist lines -> CSV sync.

Creates one row per checklist line so downstream reporting can calculate
checklist completion by equipment / commissioning level and trend progress
over time.

Required environment variables:
  CXALLOY_IDENTIFIER
  CXALLOY_SECRET
  CXALLOY_PROJECT_ID   comma-separated project ids
"""

import os
import time
import hmac
import hashlib
import json
import csv
import re
from datetime import datetime, timezone

import requests

CXALLOY_IDENTIFIER = os.environ["CXALLOY_IDENTIFIER"]
CXALLOY_SECRET = os.environ["CXALLOY_SECRET"]
CXALLOY_PROJECT_IDS = [
    p.strip() for p in os.environ["CXALLOY_PROJECT_ID"].split(",") if p.strip()
]

CXALLOY_BASE_URL = "https://tq.cxalloy.com/api/v1"
OUTPUT_PATH = "data/checklist_lines.csv"
PER_PAGE = 500

FIELDS = [
    "project_id",
    "line_id",
    "line_number",
    "description",
    "answer",
    "value",
    "line_note",
    "is_header",
    "is_bold",
    "is_italic",
    "is_indented",
    "attribute_id",
    "attribute_name",
    "attribute_value",
    "attribute_unit",
    "type",
    "line_created_by",
    "line_datetime_created",
    "line_datetime_modified",
    "issues",
    "issue_count",
    "checklist_id",
    "checklist_name",
    "checklist_number",
    "checklist_type",
    "checklist_note",
    "checklist_tools",
    "asset_name",
    "asset_type",
    "asset_key",
    "checklist_status",
    "assigned_name",
    "assigned_type",
    "assigned_key",
    "checklist_created_by",
    "checklist_datetime_created",
    "checklist_datetime_modified",
    "commissioning_level",
    "checklist_link",
    "last_synced",
]


def get_headers() -> dict:
    """CxAlloy GET requests are signed using the current timestamp."""
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


def post_headers(body_str: str) -> dict:
    """CxAlloy checklist-list POST requests sign body + timestamp."""
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


def get_checklists(project_id: str) -> list:
    """Fetch all checklist headers for a project."""
    records = []
    page = 1
    while True:
        body = {
            "project_id": int(project_id),
            "page": page,
            "perpage": PER_PAGE,
        }
        body_str = json.dumps(body, separators=(",", ":"))
        response = requests.post(
            f"{CXALLOY_BASE_URL}/checklist",
            headers=post_headers(body_str),
            data=body_str,
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("records", []) if isinstance(payload, dict) else []
        records.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1
    return records


def get_lines(project_id: str, checklist_id) -> list:
    """Fetch every line for one checklist, including linked issues."""
    lines = []
    page = 1
    while True:
        response = requests.get(
            f"{CXALLOY_BASE_URL}/checklistline",
            headers=get_headers(),
            params={
                "project_id": project_id,
                "checklist_id": checklist_id,
                "include": "issues",
                "page": page,
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, list):
            batch = payload
        elif isinstance(payload, dict):
            batch = (
                payload.get("records")
                or payload.get("data")
                or payload.get("checklistlines")
                or payload.get("checklist_lines")
                or []
            )
        else:
            batch = []

        lines.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1
    return lines


def level_from_checklist(checklist: dict) -> str:
    """Derive L1-L5 from checklist name/type without relying on tag colour."""
    text = " ".join(
        str(checklist.get(k, "") or "")
        for k in ("name", "type_name", "type")
    )
    match = re.search(r"\bL\s*([1-5])\b", text, flags=re.IGNORECASE)
    return f"L{match.group(1)}" if match else ""


def scalar(value):
    """Serialize API objects/lists safely into a CSV cell."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return value


def issue_count(issues) -> int:
    if isinstance(issues, list):
        return len(issues)
    if isinstance(issues, dict):
        records = issues.get("records")
        return len(records) if isinstance(records, list) else (1 if issues else 0)
    return 0


def main():
    print(f"Projects to sync: {CXALLOY_PROJECT_IDS}")
    now = datetime.now(timezone.utc).isoformat()
    rows = []

    for project_id in CXALLOY_PROJECT_IDS:
        print(f"Fetching checklists for project {project_id}...")
        checklists = get_checklists(project_id)
        print(f"  -> {len(checklists)} checklists")

        for index, checklist in enumerate(checklists, start=1):
            checklist_id = checklist.get("checklist_id") or checklist.get("id")
            if not checklist_id:
                print("  WARNING: checklist without checklist_id skipped")
                continue

            try:
                lines = get_lines(project_id, checklist_id)
            except requests.HTTPError as exc:
                print(f"  WARNING: checklist {checklist_id} line fetch failed: {exc}")
                continue

            level = level_from_checklist(checklist)
            for line in lines:
                issues = line.get("issues", [])
                configuration = line.get("configuration") or {}
                fmt = configuration.get("format", {}) if isinstance(configuration, dict) else {}

                row = {
                    "project_id": project_id,
                    "line_id": line.get("checklistline_id", line.get("line_id", line.get("id", ""))),
                    "line_number": line.get("line_number", ""),
                    "description": line.get("description", ""),
                    "answer": line.get("answer", ""),
                    "value": scalar(line.get("value", "")),
                    "line_note": line.get("note", line.get("line_note", "")),
                    "is_header": 1 if str(line.get("type", "")).lower() == "header" else 0,
                    "is_bold": fmt.get("bold", line.get("is_bold", "")),
                    "is_italic": fmt.get("italic", line.get("is_italic", "")),
                    "is_indented": fmt.get("indented", line.get("is_indented", "")),
                    "attribute_id": line.get("attribute_id", line.get("fk_attribute", "")),
                    "attribute_name": line.get("attribute", line.get("attribute_name", "")),
                    "attribute_value": line.get("attribute_value", ""),
                    "attribute_unit": line.get("attribute_unit", ""),
                    "type": line.get("type", ""),
                    "line_created_by": line.get("created_by", line.get("line_created_by", "")),
                    "line_datetime_created": line.get("datetime_created", line.get("date_created", "")),
                    "line_datetime_modified": line.get("datetime_modified", line.get("date_modified", "")),
                    "issues": scalar(issues),
                    "issue_count": issue_count(issues),
                    "checklist_id": checklist_id,
                    "checklist_name": checklist.get("name", ""),
                    "checklist_number": checklist.get("number", ""),
                    "checklist_type": checklist.get("type_name", checklist.get("type", "")),
                    "checklist_note": checklist.get("note", ""),
                    "checklist_tools": checklist.get("tools", ""),
                    "asset_name": checklist.get("asset_name", ""),
                    "asset_type": checklist.get("asset_type", ""),
                    "asset_key": checklist.get("asset_key", ""),
                    "checklist_status": checklist.get("status", ""),
                    "assigned_name": checklist.get("assigned_name", ""),
                    "assigned_type": checklist.get("assigned_type", ""),
                    "assigned_key": checklist.get("assigned_key", ""),
                    "checklist_created_by": checklist.get("created_by", ""),
                    "checklist_datetime_created": checklist.get("datetime_created", checklist.get("date_created", "")),
                    "checklist_datetime_modified": checklist.get("datetime_modified", checklist.get("date_modified", "")),
                    "commissioning_level": level,
                    "checklist_link": f"https://tq.cxalloy.com/project/{project_id}/checklists/{checklist_id}",
                    "last_synced": now,
                }
                rows.append(row)

            if index % 100 == 0:
                print(f"  processed {index}/{len(checklists)} checklists; {len(rows)} lines so far")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} checklist line rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
