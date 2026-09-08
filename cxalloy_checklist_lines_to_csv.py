"""
CxAlloy checklist progress sync.

This script deliberately does NOT persist individual checklist lines.
CxAlloy returns checklist records in pages of up to 500 and can include the
related line data in the same POST /checklist response. The line data is
processed in memory inside GitHub Actions and reduced to compact progress CSVs.

Outputs:
  data/checklist_progress_current.csv
      Current completion by equipment x commissioning level.

  data/checklist_progress_daily.csv
      Daily project-level trend, Overall + L1-L5. This is the lightweight
      time-series file the HTML dashboard should use for daily/weekly charts.

  data/checklist_progress_history.csv
      Weekly equipment x commissioning level snapshots. The current week's
      rows are refreshed on each run; previous weeks are retained.

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
CURRENT_PROGRESS_PATH = "data/checklist_progress_current.csv"
DAILY_PROGRESS_PATH = "data/checklist_progress_daily.csv"
WEEKLY_HISTORY_PATH = "data/checklist_progress_history.csv"
PER_PAGE = 500
MYT = ZoneInfo("Asia/Kuala_Lumpur")

# Well below CxAlloy's 10,000 requests/hour API-key ceiling. With bulk checklist
# pagination this script should normally use only tens of requests, not thousands.
SAFE_REQUESTS_PER_HOUR = 7500
MIN_REQUEST_INTERVAL = 3600.0 / SAFE_REQUESTS_PER_HOUR
_last_request_started = 0.0
_request_count = 0

CURRENT_FIELDS = [
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
    "last_synced",
]

DAILY_FIELDS = [
    "snapshot_date",
    "week_start",
    "project_id",
    "commissioning_level",
    "equipment_count",
    "checklist_count",
    "total_lines",
    "completed_lines",
    "open_lines",
    "completion_pct",
    "last_synced",
]


def throttle_request_rate():
    global _last_request_started, _request_count
    now = time.monotonic()
    elapsed = now - _last_request_started
    if _last_request_started and elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    _last_request_started = time.monotonic()
    _request_count += 1


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


def post_json_with_retry(url: str, body: dict, max_attempts: int = 5):
    """POST signed JSON with throttling and conservative retries."""
    body_str = json.dumps(body, separators=(",", ":"))
    for attempt in range(1, max_attempts + 1):
        try:
            throttle_request_rate()
            response = requests.post(
                url,
                headers=post_headers(body_str),
                data=body_str,
                timeout=120,
            )
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt == max_attempts:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                delay = int(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 30)
                print(f"  HTTP {response.status_code}; retrying in {delay}s ({attempt}/{max_attempts})")
                time.sleep(delay)
                continue
            response.raise_for_status()
            return response.json()
        except (requests.ConnectionError, requests.Timeout):
            if attempt == max_attempts:
                raise
            delay = min(2 ** attempt, 30)
            print(f"  Network error; retrying in {delay}s ({attempt}/{max_attempts})")
            time.sleep(delay)
    raise RuntimeError("request retry loop ended unexpectedly")


def fetch_checklist_page(project_id: str, page: int, legacy_mode: bool = False) -> dict:
    """
    Fetch one page of up to 500 checklists including line data.

    Upgraded CxAlloy projects support include=["lines"]. Older projects require
    sections to be included when lines are requested, so the caller can retry
    with legacy_mode=True if CxAlloy rejects the upgraded-project request.
    """
    includes = ["sections", "lines"] if legacy_mode else ["lines"]
    body = {
        "project_id": int(project_id),
        "page": page,
        "perpage": PER_PAGE,
        "include": includes,
    }
    return post_json_with_retry(f"{CXALLOY_BASE_URL}/checklist", body)


def as_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("records", "data", "lines", "sections"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def lines_from_checklist(checklist: dict) -> list:
    """Support both upgraded checklists and legacy section-based checklists."""
    direct = as_list(checklist.get("lines"))
    if direct:
        return direct

    lines = []
    for section in as_list(checklist.get("sections")):
        lines.extend(as_list(section.get("lines")))
    return lines


def level_from_checklist(checklist: dict) -> str:
    text = " ".join(
        str(checklist.get(k, "") or "") for k in ("name", "type_name", "type")
    )
    match = re.search(r"\bL\s*([1-5])\b", text, flags=re.IGNORECASE)
    return f"L{match.group(1)}" if match else ""


def has_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def is_actionable_line(line: dict) -> bool:
    """
    Exclude structural/display-only rows from the completion denominator.
    CxAlloy line types 'header' and 'information' do not represent checklist
    actions to be completed.
    """
    line_type = str(line.get("type", "") or "").strip().lower()
    return line_type not in {"header", "information"}


def is_completed_line(line: dict) -> bool:
    """
    A line is complete once CxAlloy contains an answer or a populated value.
    Explicit passed/failed/NA responses all count as completed checklist work.
    """
    return any(
        has_value(line.get(field))
        for field in ("answer", "value", "attribute_value")
    )


def new_bucket():
    return {
        "asset_name": "",
        "asset_type": "",
        "checklist_ids": set(),
        "checklist_statuses": set(),
        "total_lines": 0,
        "completed_lines": 0,
    }


def process_checklist(checklist: dict, project_id: str, grouped: dict):
    level = level_from_checklist(checklist)
    asset_name = str(checklist.get("asset_name", "") or "")
    asset_key = str(checklist.get("asset_key", "") or asset_name)
    if not level or not asset_key:
        return

    key = (project_id, asset_key, level)
    bucket = grouped[key]
    bucket["asset_name"] = asset_name or bucket["asset_name"]
    bucket["asset_type"] = str(checklist.get("asset_type", "") or bucket["asset_type"])

    checklist_id = checklist.get("checklist_id") or checklist.get("id")
    if checklist_id:
        bucket["checklist_ids"].add(str(checklist_id))
    if checklist.get("status"):
        bucket["checklist_statuses"].add(str(checklist["status"]))

    for line in lines_from_checklist(checklist):
        if not is_actionable_line(line):
            continue
        bucket["total_lines"] += 1
        if is_completed_line(line):
            bucket["completed_lines"] += 1


def fetch_and_aggregate_project(project_id: str, grouped: dict):
    """Bulk-fetch all checklists for one project, 500 checklists per request."""
    page = 1
    legacy_mode = False
    processed = 0
    reported_total = None

    while True:
        try:
            payload = fetch_checklist_page(project_id, page, legacy_mode=legacy_mode)
        except requests.HTTPError as exc:
            # CxAlloy documents that legacy projects cannot include lines unless
            # sections are included too. Retry page 1 once in that mode.
            if page == 1 and not legacy_mode and exc.response is not None and exc.response.status_code == 400:
                print("  Project requires legacy checklist sections; retrying with sections + lines")
                legacy_mode = True
                continue
            raise

        records = payload.get("records", []) if isinstance(payload, dict) else []
        if reported_total is None and isinstance(payload, dict):
            reported_total = payload.get("total_count")
            if reported_total is not None:
                print(f"  CxAlloy reports {reported_total} checklists")

        for checklist in records:
            process_checklist(checklist, project_id, grouped)
        processed += len(records)

        print(
            f"  page {page}: {len(records)} checklists; "
            f"{processed} processed; {_request_count} API requests"
        )

        if len(records) < PER_PAGE:
            break
        page += 1

    return processed


def build_current_rows(grouped: dict, snapshot_date: str, week_start: str, last_synced: str) -> list:
    rows = []
    for (project_id, asset_key, level), bucket in sorted(grouped.items()):
        total = bucket["total_lines"]
        completed = bucket["completed_lines"]
        rows.append({
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
            "completion_pct": round(completed / total * 100, 2) if total else 0,
            "last_synced": last_synced,
        })
    return rows


def build_daily_rows(current_rows: list, snapshot_date: str, week_start: str, last_synced: str) -> list:
    """Create tiny project trend rows: Overall plus each L1-L5 level."""
    grouped = defaultdict(lambda: {
        "equipment": set(),
        "checklists": 0,
        "total": 0,
        "completed": 0,
    })

    for row in current_rows:
        project_id = row["project_id"]
        level = row["commissioning_level"]
        for trend_level in (level, "Overall"):
            key = (project_id, trend_level)
            grouped[key]["equipment"].add(row["asset_key"])
            grouped[key]["checklists"] += int(row["checklist_count"] or 0)
            grouped[key]["total"] += int(row["total_lines"] or 0)
            grouped[key]["completed"] += int(row["completed_lines"] or 0)

    rows = []
    for (project_id, level), bucket in sorted(grouped.items()):
        total = bucket["total"]
        completed = bucket["completed"]
        rows.append({
            "snapshot_date": snapshot_date,
            "week_start": week_start,
            "project_id": project_id,
            "commissioning_level": level,
            "equipment_count": len(bucket["equipment"]),
            "checklist_count": bucket["checklists"],
            "total_lines": total,
            "completed_lines": completed,
            "open_lines": total - completed,
            "completion_pct": round(completed / total * 100, 2) if total else 0,
            "last_synced": last_synced,
        })
    return rows


def read_csv(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
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
    print(f"Snapshot date: {snapshot_date}; week starting {week_start} (MYT)")
    print(f"Bulk checklist page size: {PER_PAGE}")

    grouped = defaultdict(new_bucket)
    total_checklists = 0

    for project_id in CXALLOY_PROJECT_IDS:
        print(f"Fetching project {project_id} checklists with embedded lines...")
        total_checklists += fetch_and_aggregate_project(project_id, grouped)

    current_rows = build_current_rows(grouped, snapshot_date, week_start, last_synced)
    write_csv(CURRENT_PROGRESS_PATH, CURRENT_FIELDS, current_rows)
    print(f"Wrote {len(current_rows)} current equipment x level rows to {CURRENT_PROGRESS_PATH}")

    # Daily project/level trend: replace today's rows if the workflow is rerun.
    today_rows = build_daily_rows(current_rows, snapshot_date, week_start, last_synced)
    existing_daily = read_csv(DAILY_PROGRESS_PATH)
    existing_daily = [r for r in existing_daily if r.get("snapshot_date") != snapshot_date]
    daily_history = existing_daily + today_rows
    daily_history.sort(key=lambda r: (
        r.get("snapshot_date", ""),
        r.get("project_id", ""),
        r.get("commissioning_level", ""),
    ))
    write_csv(DAILY_PROGRESS_PATH, DAILY_FIELDS, daily_history)
    print(f"Wrote {len(daily_history)} daily trend rows to {DAILY_PROGRESS_PATH}")

    # Weekly equipment x level history: refresh only this week's point.
    existing_weekly = read_csv(WEEKLY_HISTORY_PATH)
    prior_weeks = [r for r in existing_weekly if r.get("week_start") != week_start]
    weekly_history = prior_weeks + current_rows
    weekly_history.sort(key=lambda r: (
        r.get("week_start", ""),
        r.get("project_id", ""),
        r.get("asset_key", ""),
        r.get("commissioning_level", ""),
    ))
    write_csv(WEEKLY_HISTORY_PATH, CURRENT_FIELDS, weekly_history)
    print(f"Wrote {len(weekly_history)} weekly equipment history rows to {WEEKLY_HISTORY_PATH}")

    print(
        f"Completed: {total_checklists} checklists processed using {_request_count} API requests. "
        "Individual checklist lines were processed in memory and were not written to GitHub."
    )


if __name__ == "__main__":
    main()
