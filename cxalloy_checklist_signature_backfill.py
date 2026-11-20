"""Preview or add missing KUL21 checklist signature roles."""
import csv
import json
import os
import re

import requests

from cxalloy_checklist_lines_to_csv import (
    CXALLOY_BASE_URL,
    CXALLOY_PROJECT_IDS,
    lines_from_checklist,
    post_headers,
    post_json_with_retry,
    throttle_request_rate,
)
from cxalloy_checklist_signature_report import (
    checklist_lines_available,
    checklist_records,
    spreadsheet_value,
)

ROLES = {
    "Equipment Installer": {"equipment installer", "installer", "equipment installation contractor"},
    "General Contractor": {"general contractor", "gc", "g c"},
    "BCEI": {"bcei", "b c e i"},
}
FIELDS = [
    "project_id", "checklist_id", "checklist_number", "checklist_status",
    "present_roles", "missing_roles", "unmatched_signature_titles", "action",
]


def role_label(title):
    words = re.sub(r"[^a-z0-9]+", " ", title.casefold()).strip()
    words = re.sub(r"^(signature|sign off|signoff)\s+", "", words)
    return re.sub(r"\s+(signature|sign off|signoff)$", "", words)


def assess(checklist):
    if not checklist_lines_available(checklist):
        return None
    present = set()
    unmatched = []
    for line in lines_from_checklist(checklist):
        if not isinstance(line, dict) or not str(line.get("type") or "").strip():
            return None
        if str(line["type"]).strip().casefold() != "signature":
            continue
        config = line.get("configuration")
        config_title = config.get("title") if isinstance(config, dict) else None
        title = str(line.get("title") or config_title or line.get("description") or "")
        label = role_label(title)
        match = next((role for role, aliases in ROLES.items() if label in aliases), None)
        if match:
            present.add(match)
        else:
            unmatched.append(title or "(blank title)")
    return present, [role for role in ROLES if role not in present], unmatched


def read_checklist(project_id, checklist_id):
    body = {
        "project_id": int(project_id),
        "filter": {"id": [int(checklist_id)]},
        "page": 1,
        "perpage": 2,
        "include": ["lines"],
    }
    try:
        payload = post_json_with_retry(f"{CXALLOY_BASE_URL}/checklist", body)
    except requests.HTTPError as error:
        if error.response is None or error.response.status_code != 400:
            raise
        body["include"] = ["sections", "lines"]
        payload = post_json_with_retry(f"{CXALLOY_BASE_URL}/checklist", body)
    records = payload.get("records")
    if not isinstance(records, list) or len(records) != 1:
        raise ValueError(f"Expected one checklist for {project_id}/{checklist_id}.")
    checklist = records[0]
    if str(checklist.get("checklist_id") or checklist.get("id")) != checklist_id:
        raise ValueError(f"CxAlloy did not return checklist {project_id}/{checklist_id}.")
    return checklist


def write_error_detail(response):
    """Report the API's error message without dumping headers or a response body."""
    content_type = response.headers.get("Content-Type", "").split(";")[0].lower().strip()
    try:
        payload = response.json()
    except ValueError:
        payload = None
    message = ""
    if isinstance(payload, dict):
        for key in ("message", "error_description", "detail", "error", "description"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("message") or value.get("detail")
            if isinstance(value, str) and value.strip():
                message = value
                break
    elif isinstance(payload, str):
        message = payload
    elif content_type == "text/plain" and not response.text.lstrip().startswith(("<", "{", "[")):
        message = response.text.splitlines()[0] if response.text else ""

    # The repository's Actions logs are public. Never emit credentials or request dumps.
    for name in ("CXALLOY_IDENTIFIER", "CXALLOY_SECRET", "BACKFILL_IDENTIFIER", "BACKFILL_SECRET"):
        secret = os.environ.get(name)
        if secret:
            message = message.replace(secret, "[redacted]")
    message = next((line.strip() for line in message.splitlines() if line.strip()), "")
    message = re.sub(
        r"(?i)\b(?:authorization|token|password|api[_ -]?key|secret|cxalloy-(?:identifier|signature))"
        r"\s*[:=]\s*[^,;]+", "[redacted]", message,
    )
    message = re.sub(r"(?i)\b(?:https?://|bearer\s+)\S+", "[redacted]", message)
    message = re.sub(r"(?i)\b[\w.+%-]+@[\w.-]+\.[a-z]{2,}\b|[\w+/=-]{24,}", "[redacted]", message)
    message = " ".join(message.split())[:320]
    if not message or "<" in message or ">" in message:
        message = "No usable API error message in the response."
    details = [message]
    if re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", content_type):
        details.append(f"Content-Type={content_type}")
    for header in ("X-Request-ID", "CF-Ray", "X-Amz-Cf-Id"):
        ref = response.headers.get(header, "")
        if re.fullmatch(r"[a-zA-Z0-9_+/=-]{4,128}", ref):
            details.append(f"{header}={ref}")
    return " | ".join(details)


def create_line(project_id, checklist_id, role):
    body = json.dumps({
        "project_id": int(project_id),
        "checklist_id": int(checklist_id),
        "type": "signature",
        "title": role,
        "description": f"{role} sign-off",
        "allow_na": False,
    }, separators=(",", ":"))
    # Creation is non-idempotent. Let a subsequent run re-read the checklist
    # before retrying a request whose outcome is uncertain.
    throttle_request_rate()
    response = requests.post(
        f"{CXALLOY_BASE_URL}/checklistline_create",
        headers=post_headers(body),
        data=body,
        timeout=60,
        allow_redirects=False,
    )
    if not 200 <= response.status_code < 300:
        raise RuntimeError(
            f"Creating {role} signature line returned HTTP {response.status_code}. "
            f"{write_error_detail(response)}"
        )


def add_missing(project_id, checklist_id):
    live = assess(read_checklist(project_id, checklist_id))
    if live is None or (live[1] and live[2]):
        return "Review needed"
    _, missing, _ = live
    if not missing:
        return "Already complete"
    for role in missing:
        create_line(project_id, checklist_id, role)
    verified = assess(read_checklist(project_id, checklist_id))
    if verified is None or verified[1]:
        raise RuntimeError(f"Could not verify all roles for {project_id}/{checklist_id}.")
    return "Added: " + " | ".join(missing)


def targets(mode):
    if mode == "pilot":
        project_id = os.environ["PILOT_PROJECT_ID"].strip()
        checklist_id = os.environ["PILOT_CHECKLIST_ID"].strip()
        if project_id not in CXALLOY_PROJECT_IDS or not checklist_id.isdecimal():
            raise ValueError("For pilot, choose a KUL21 project ID and a numeric checklist ID.")
        yield project_id, checklist_id, read_checklist(project_id, checklist_id)
        return
    for project_id in CXALLOY_PROJECT_IDS:
        for checklist_id, checklist in checklist_records(project_id):
            yield project_id, checklist_id, checklist


def main():
    mode = os.environ["BACKFILL_MODE"]
    limit = int(os.environ["BATCH_SIZE"])
    if mode not in {"preview", "pilot", "apply"} or not 1 <= limit <= 2000:
        raise ValueError("Choose preview, pilot, or apply and a batch size of 1 to 2000.")
    plan = []
    for project_id, checklist_id, checklist in targets(mode):
        assessment = assess(checklist)
        present, missing, unmatched = assessment or (set(), [], [])
        plan.append(({
            "project_id": project_id,
            "checklist_id": checklist_id,
            "checklist_number": checklist.get("number"),
            "checklist_status": checklist.get("status"),
            "present_roles": " | ".join(role for role in ROLES if role in present),
            "missing_roles": " | ".join(missing),
            "unmatched_signature_titles": " | ".join(unmatched),
        }, assessment is None or bool(missing and unmatched)))

    planned = attempted = added = review = 0
    with open("checklist_signature_backfill.csv", "w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        for row, needs_review in plan:
            project_id = row["project_id"]
            checklist_id = row["checklist_id"]
            try:
                if needs_review:
                    action = "Review needed"
                elif not row["missing_roles"]:
                    action = "Already complete"
                else:
                    planned += 1
                    if mode == "preview":
                        action = "Would add"
                    elif mode == "apply" and attempted >= limit:
                        action = "Pending next batch"
                    else:
                        attempted += 1
                        action = add_missing(project_id, checklist_id)
                added += action.startswith("Added:")
                review += action == "Review needed"
            except Exception as error:
                writer.writerow({**{k: spreadsheet_value(v) for k, v in row.items()},
                                 "action": "Stopped: verify live record before rerunning"})
                raise RuntimeError(
                    f"Stopped at project {project_id}, checklist {checklist_id}. "
                    f"Check the live record before rerunning. {type(error).__name__}: {error}"
                ) from None
            writer.writerow({k: spreadsheet_value(v) for k, v in {**row, "action": action}.items()})
            if mode == "apply" and attempted and attempted % 100 == 0 and action.startswith("Added:"):
                output.flush()
                print(f"Attempted {attempted} checklists; verified updates on {added}.", flush=True)
    print(f"Scanned {len(plan)} checklists; {planned} eligible for additions; "
          f"{added} updated; {review} need title or line-data review.")


if __name__ == "__main__":
    main()
