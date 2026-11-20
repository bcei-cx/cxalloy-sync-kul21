"""Export one signature-status row per CxAlloy checklist."""
import csv
from collections import Counter
from datetime import datetime, timezone

import requests

from cxalloy_checklist_lines_to_csv import (
    CXALLOY_PROJECT_IDS,
    PER_PAGE,
    fetch_checklist_page,
    level_from_checklist,
    lines_from_checklist,
)

FIELDS = [
    "as_of_utc", "project_id", "checklist_id", "checklist_number",
    "checklist_name", "equipment_tag", "cx_level", "checklist_type",
    "checklist_status", "assignee", "signature_status", "signature_lines",
    "signed", "unsigned", "na", "unknown", "pending_signoffs",
]


def line_records(value):
    """Distinguish an empty line collection from one absent in the response."""
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("records", "data", "lines", "sections"):
            if isinstance(value.get(key), list):
                return value[key]
    return None


def checklist_lines_available(checklist):
    if line_records(checklist.get("lines")):
        return True
    sections = line_records(checklist.get("sections"))
    if sections is not None:
        return all(
            isinstance(section, dict) and line_records(section.get("lines")) is not None
            for section in sections
        )
    return line_records(checklist.get("lines")) is not None


def normalized(value):
    return str(value if value is not None else "").strip().casefold()


def blank_value(value):
    if isinstance(value, dict):
        return all(blank_value(item) for item in value.values())
    if isinstance(value, list):
        return all(blank_value(item) for item in value)
    return value is None or (isinstance(value, str) and not value.strip())


def line_status(line):
    answer = normalized(line.get("answer"))
    if answer in {"na", "n/a", "not applicable"}:
        return "na"
    # CxAlloy requires a signature to pass a Signature line.
    if answer in {"passed", "pass", "signed"}:
        return "signed"
    if answer in {"unsigned", "unanswered", "not signed"}:
        return "unsigned"
    if "answer" in line and not answer and blank_value(line.get("value")):
        return "unsigned"
    return "unknown"


def summarize(checklist):
    counts = Counter()
    pending = []
    incomplete = not checklist_lines_available(checklist)
    if not incomplete:
        for line in lines_from_checklist(checklist):
            if not isinstance(line, dict) or not normalized(line.get("type")):
                incomplete = True
                continue
            if normalized(line["type"]) != "signature":
                continue
            state = line_status(line)
            counts[state] += 1
            if state == "unsigned":
                config = line.get("configuration")
                title = config.get("title") if isinstance(config, dict) else None
                pending.append(str(
                    line.get("title") or title or line.get("description")
                    or f"Line {line.get('line_number') or line.get('checklistline_id') or '?'}"
                ))

    total = sum(counts.values())
    if incomplete or counts["unknown"]:
        status = "Unknown"
    elif not total:
        status = "No signature lines"
    elif counts["na"] == total:
        status = "N/A"
    elif not counts["unsigned"]:
        status = "Fully signed"
    elif counts["signed"]:
        status = "Partially signed"
    else:
        status = "Unsigned"
    return {
        "signature_status": status,
        "signature_lines": "" if incomplete else total,
        **{key: "" if incomplete else counts[key] for key in ("signed", "unsigned", "na", "unknown")},
        "pending_signoffs": " | ".join(pending),
    }


def checklist_records(project_id):
    page = 1
    legacy = False
    seen = set()
    reported_total = None
    while True:
        try:
            payload = fetch_checklist_page(project_id, page, legacy_mode=legacy)
        except requests.HTTPError as error:
            if page != 1 or legacy or error.response is None or error.response.status_code != 400:
                raise
            legacy = True
            continue

        records = payload.get("records") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            raise ValueError(f"Missing checklist records on API page {page}")
        if isinstance(payload.get("total_count"), (int, str)):
            total = int(payload["total_count"])
            if reported_total is not None and total != reported_total:
                raise ValueError("Checklist total changed during pagination. Run the report again.")
            reported_total = total

        for checklist in records:
            checklist_id = str(checklist.get("checklist_id") or checklist.get("id") or "")
            if not checklist_id or checklist_id in seen:
                raise ValueError("Missing or repeated checklist ID during pagination.")
            seen.add(checklist_id)
            yield checklist_id, checklist

        if reported_total == len(seen) or len(records) < PER_PAGE:
            if reported_total is not None and reported_total != len(seen):
                raise ValueError("Checklist count does not match the API total. Run the report again.")
            return
        page += 1


def spreadsheet_value(value):
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return value


def main():
    as_of = datetime.now(timezone.utc).isoformat()
    with open("checklist_signature_status.csv", "w", newline="", encoding="utf-8-sig") as report:
        writer = csv.DictWriter(report, fieldnames=FIELDS)
        writer.writeheader()
        for project_id in CXALLOY_PROJECT_IDS:
            for checklist_id, checklist in checklist_records(project_id):
                row = {
                    "as_of_utc": as_of,
                    "project_id": project_id,
                    "checklist_id": checklist_id,
                    "checklist_number": checklist.get("number"),
                    "checklist_name": checklist.get("name"),
                    "equipment_tag": checklist.get("asset_name"),
                    "cx_level": level_from_checklist(checklist),
                    "checklist_type": checklist.get("type_name"),
                    "checklist_status": checklist.get("status"),
                    "assignee": checklist.get("assigned_name"),
                    **summarize(checklist),
                }
                writer.writerow({key: spreadsheet_value(value) for key, value in row.items()})


if __name__ == "__main__":
    main()
