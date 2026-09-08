"""
CxAlloy checklist lines -> current detail + compact trend snapshots.

Outputs:
  data/checklist_lines.csv
      Current line-level state only. Replaced on every sync.

  data/checklist_progress_current.csv
      Current completion aggregated to equipment x commissioning level.

  data/checklist_progress_history.csv
      Weekly equipment x commissioning level snapshots. During the current
      week, that week's rows are replaced on every daily sync. Once a new
      week starts, the previous week's rows remain as the historical point.

This avoids storing a new 100k-line raw snapshot every week while preserving
exactly the trend grain needed by the dashboard.

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
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests

CXALLOY_IDENTIFIER = os.environ["CXALLOY_IDENTIFIER"]
CXALLOY_SECRET = os.environ["CXALLOY_SECRET"]
CXALLOY_PROJECT_IDS = [
    p.strip() for p in os.environ["CXALLOY_PROJECT_ID"].split(",") if p.strip()
]

CXALLOY_BASE_URL = "https://tq.cxalloy.com/api/v1"
RAW_OUTPUT_PATH = "data/checklist_lines.csv"
CURRENT_PROGRESS_PATH = "data/checklist_progress_current.csv"
HISTORY_PROGRESS_PATH = "data/checklist_progress_history.csv"
PER_PAGE = 500
MYT = ZoneInfo("Asia/Kuala_Lumpur")

RAW_FIELDS = [
    "project_id", "line_id", "line_number", "description", "answer", "value",
    "line_note", "is_header", "is_bold", "is_italic", "is_indented",
    "attribute_id", "attribute_name", "attribute_value", "attribute_unit",
    "type", "line_created_by", "line_datetime_created", "line_datetime_modified",
    "issues", "issue_count", "checklist_id", "checklist_name", "checklist_number",
    "checklist_type", "checklist_note", "checklist_tools", "asset_name",
    "asset_type", "asset_key", "checklist_status", "assigned_name",
    "assigned_type", "assigned_key", "checklist_created_by",
    "checklist_datetime_created", "checklist_datetime_modified",
    "commissioning_level", "checklist_link", "last_synced",
]

PROGRESS_FIELDS = [
    "snapshot_date",
    "week_start",
    "project_id",
    "asset_key",
    "asset_name",
    "asset_type",
    "commissioning_level",
    "checklist_count",
    "checklist_ids",
    "checklist_statuses",
    "total_lines",
    "completed_lines",
    "open_lines",
    "completion_pct",
    "issue_count",
    "last_synced",
]


def get_headers() -> dict:
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
    timestamp = int(time.time())
    signature = hmac.new(
        CXALLOY_SECRET.encode("utf-8"),
        (body_str + str(timestamp)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "cxalloy-identifier": CXALLOY_IDENTIFIER,
        "cxalloy-signature": signature,
        "cxalloy-timestamp": str(timestamp),
        "user-agent": "GitHubActions-CxAlloySync/1.0",
    }


def request_with_retry(method, url, *, headers, max_attempts=5, **kwargs):
    """Retry throttling and temporary server/network failures conservatively."""
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.request(method, url, headers=headers, **kwargs)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == max_attempts:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 30)
                print(f"  HTTP {response.status_code}; retrying in {delay}s ({attempt}/{max_attempts})")
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except (requests.ConnectionError, requests.Timeout):
            if attempt == max_attempts:
                raise
            delay = min(2 ** attempt, 30)
            print(f"  Network error; retrying in {delay}s ({attempt}/{max_attempts})")
            time.sleep(delay)
    raise RuntimeError("request retry loop ended unexpectedly")


def get_checklists(project_id: str) -> list:
    records = []
    page = 1
    while True:
        body = {"project_id": int(project_id), "page": page, "perpage": PER_PAGE}
        body_str = json.dumps(body, separators=(",", ":"))
        response = request_with_retry(
            "POST",
            f"{CXALLOY_BASE_URL}/checklist",
            headers=post_headers(body_str),
            data=body_str,
            timeout=60,
        )
        payload = response.json()
        batch = payload.get("records", []) if isinstance(payload, dict) else []
        records.extend(batch)
        if len(batch) < PER_PAGE:
            break
        page += 1
    return records


def get_lines(project_id: str, checklist_id) -> list:
    lines = []
    page = 1
    while True:
        response = request_with_retry(
            "GET",
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
    text = " ".join(
        str(checklist.get(k, "") or "") for k in ("name", "type_name", "type")
    )
    match = re.search(r"\bL\s*([1-5])\b", text, flags=re.IGNORECASE)
    return f"L{match.group(1)}" if match else ""


def scalar(value):
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


def has_value(value) -> bool:
    """Blank-safe check; numeric 0 and boolean False still count as responses."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def is_actionable_line(row: dict) -> bool:
    """
    Headers are excluded from checklist completion. Other line types remain in
    scope until the real KUL21 export proves that additional instruction-only
    types should also be excluded.
    """
    return not bool(row.get("is_header"))


def is_completed_line(row: dict) -> bool:
    """
    A checklist line counts as completed once it has a response in answer,
    value or attribute_value. Responses such as N/A count as completed because
    they represent an explicit checklist disposition rather than an unanswered
    line.
    """
    return any(has_value(row.get(field)) for field in ("answer", "value", "attribute_value"))


def aggregate_progress(rows: list, snapshot_date: str, week_start: str, last_synced: str) -> list:
    grouped = defaultdict(lambda: {
        "asset_name": "",
        "asset_type": "",
        "checklist_ids": set(),
        "checklist_statuses": set(),
        "total_lines": 0,
        "completed_lines": 0,
        "issue_count": 0,
    })

    for row in rows:
        level = row.get("commissioning_level", "")
        asset_key = row.get("asset_key", "") or row.get("asset_name", "")
        if not level or not asset_key or not is_actionable_line(row):
            continue

        key = (row.get("project_id", ""), asset_key, level)
        bucket = grouped[key]
        bucket["asset_name"] = row.get("asset_name", "") or bucket["asset_name"]
        bucket["asset_type"] = row.get("asset_type", "") or bucket["asset_type"]
        if row.get("checklist_id"):
            bucket["checklist_ids"].add(str(row["checklist_id"]))
        if row.get("checklist_status"):
            bucket["checklist_statuses"].add(str(row["checklist_status"]))
        bucket["total_lines"] += 1
        if is_completed_line(row):
            bucket["completed_lines"] += 1
        bucket["issue_count"] += int(row.get("issue_count") or 0)

    result = []
    for (project_id, asset_key, level), bucket in sorted(grouped.items()):
        total = bucket["total_lines"]
        completed = bucket["completed_lines"]
        result.append({
            "snapshot_date": snapshot_date,
            "week_start": week_start,
            "project_id": project_id,
            "asset_key": asset_key,
            "asset_name": bucket["asset_name"],
            "asset_type": bucket["asset_type"],
            "commissioning_level": level,
            "checklist_count": len(bucket["checklist_ids"]),
            "checklist_ids": ";".join(sorted(bucket["checklist_ids"])),
            "checklist_statuses": ";".join(sorted(bucket["checklist_statuses"])),
            "total_lines": total,
            "completed_lines": completed,
            "open_lines": total - completed,
            "completion_pct": round((completed / total * 100), 2) if total else 0,
            "issue_count": bucket["issue_count"],
            "last_synced": last_synced,
        })
    return result


def read_existing_history() -> list:
    if not os.path.exists(HISTORY_PROGRESS_PATH):
        return []
    with open(HISTORY_PROGRESS_PATH, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: str, fields: list, rows: list):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    now_utc = datetime.now(timezone.utc)
    now_myt = now_utc.astimezone(MYT)
    snapshot_date = now_myt.date().isoformat()
    week_start_date = now_myt.date() - timedelta(days=now_myt.weekday())
    week_start = week_start_date.isoformat()
    last_synced = now_utc.isoformat()

    print(f"Projects to sync: {CXALLOY_PROJECT_IDS}")
    print(f"Trend snapshot: {snapshot_date} (week starting {week_start}, MYT)")
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
            except requests.RequestException as exc:
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
                    "last_synced": last_synced,
                }
                rows.append(row)

            if index % 100 == 0:
                print(f"  processed {index}/{len(checklists)} checklists; {len(rows)} lines so far")

    # Current raw detail is replaced, never appended.
    write_csv(RAW_OUTPUT_PATH, RAW_FIELDS, rows)
    print(f"Wrote {len(rows)} current checklist line rows to {RAW_OUTPUT_PATH}")

    current_progress = aggregate_progress(rows, snapshot_date, week_start, last_synced)
    write_csv(CURRENT_PROGRESS_PATH, PROGRESS_FIELDS, current_progress)
    print(f"Wrote {len(current_progress)} equipment-level progress rows to {CURRENT_PROGRESS_PATH}")

    # Preserve previous weeks; refresh only the current week's snapshot.
    existing_history = read_existing_history()
    prior_weeks = [r for r in existing_history if r.get("week_start") != week_start]
    history = prior_weeks + current_progress
    history.sort(key=lambda r: (
        r.get("week_start", ""),
        r.get("project_id", ""),
        r.get("asset_key", ""),
        r.get("commissioning_level", ""),
    ))
    write_csv(HISTORY_PROGRESS_PATH, PROGRESS_FIELDS, history)
    print(
        f"Wrote {len(history)} historical progress rows to {HISTORY_PROGRESS_PATH} "
        f"({len(prior_weeks)} prior-week rows preserved; current week refreshed)"
    )


if __name__ == "__main__":
    main()
