"""Read-only CxAlloy Tests sync for L4; publish only after a complete extraction.

Every Test is L4. Acceptance is status-based, execution is latest-attempt
step-based. Headers/information and N/A answers are excluded from applicable
steps. Equipment without linked tests has unknown L4 scope, never 100% complete.
"""
import csv
import hashlib
import hmac
import json
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

BASE = "https://tq.cxalloy.com/api/v1"
PAGE_SIZE = 100
COMPLETE = {"passed", "completed", "reviewed"}
FAILED = {"failed", "fail", "retest required"}
NOT_STARTED = {"not started", "not_started", "pending", "open"}
PROGRESS = {"in progress", "in_progress", "started"}
DISPLAY_TYPES = {"header", "information"}
NA = {"na", "n/a", "not applicable", "not_applicable"}


def txt(value):
    return "" if value is None else str(value).strip()


def number(value):
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return 0


def status_key(value):
    return txt(value).lower().replace("_", " ")


def present(value):
    if value is None or value == "":
        return False
    if isinstance(value, dict):
        # is_valid by itself is metadata, never an answer.
        return present(value.get("value"))
    if isinstance(value, list):
        return any(present(x) for x in value)
    return bool(txt(value))  # numeric zero is a valid reading


def records(payload, id_field):
    if isinstance(payload, list):
        result = payload
    elif isinstance(payload, dict) and "records" in payload:
        result = payload["records"]
    elif isinstance(payload, dict) and id_field in payload:
        result = [payload]
    elif isinstance(payload, dict) and not payload:
        result = []
    elif isinstance(payload, dict) and all(isinstance(v, dict) for v in payload.values()):
        result = list(payload.values())
    else:
        raise ValueError(f"Unrecognized {id_field} response shape")
    if not isinstance(result, list) or not all(isinstance(v, dict) for v in result):
        raise ValueError(f"Invalid {id_field} records")
    return result


class Client:
    def __init__(self):
        self.identifier = os.environ["CXALLOY_IDENTIFIER"]
        self.secret = os.environ["CXALLOY_SECRET"]
        self.last = 0
        self.requests = 0

    def request(self, endpoint, body=None, params=None):
        data = json.dumps(body, separators=(",", ":")) if body is not None else ""
        url = BASE + endpoint + ("?" + urlencode(params) if params else "")
        for retry in range(5):
            time.sleep(max(0, .5 - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            self.requests += 1
            timestamp = str(int(time.time()))
            signature = hmac.new(self.secret.encode(), (data + timestamp).encode(), hashlib.sha256).hexdigest()
            req = Request(url, data=data.encode() if body is not None else None, headers={
                "Content-Type": "application/json", "cxalloy-identifier": self.identifier,
                "cxalloy-signature": signature, "cxalloy-timestamp": timestamp,
                "User-Agent": "GitHubActions-CxAlloy-L4/1.0",
            })
            try:
                with urlopen(req, timeout=120) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or retry == 4:
                    # Do not print response bodies or credentials.
                    raise RuntimeError(f"CxAlloy {endpoint}: HTTP {exc.code}") from None
                delay = exc.headers.get("Retry-After", "")
                time.sleep(min(int(delay), 60) if delay.isdigit() else min(2 ** (retry + 1), 30))
            except (URLError, TimeoutError):
                if retry == 4:
                    raise RuntimeError(f"CxAlloy {endpoint}: network request failed") from None
                time.sleep(min(2 ** (retry + 1), 30))

    def pages(self, endpoint, project_id, id_field, body=None, params=None):
        result, seen = [], set()
        limit = PAGE_SIZE if body is not None else 500
        for page in range(1, 2001):
            if body is not None:
                payload = self.request(endpoint, body={**body, "project_id": int(project_id), "page": page, "perpage": limit})
            else:
                payload = self.request(endpoint, params={**(params or {}), "project_id": int(project_id), "page": page})
            batch = records(payload, id_field)
            for row in batch:
                key = txt(row.get(id_field))
                if not key or key in seen:
                    raise ValueError(f"Missing/duplicate {id_field}; refusing partial publication")
                seen.add(key)
                result.append(row)
            if len(batch) < limit:
                return result
        raise RuntimeError(f"{endpoint}: pagination cap reached; refusing partial publication")


def normalize_line(line):
    answer = txt(line.get("answer"))
    value = line.get("value")
    if isinstance(value, dict):
        value = value.get("value")
    actionable = txt(line.get("type")).lower() not in DISPLAY_TYPES
    na = actionable and status_key(answer) in NA
    answered = actionable and any(present(line.get(k)) for k in ("answer", "value", "attribute_value"))
    return {
        "id": txt(line.get("testattemptline_id")), "number": line.get("line_number", ""),
        "description": txt(line.get("description")), "type": txt(line.get("type")),
        "answer": answer, "value": value, "attribute": txt(line.get("attribute")),
        "attribute_value": line.get("attribute_value"), "unit": txt(line.get("attribute_unit")),
        "note": txt(line.get("note")), "actionable": actionable, "na": na,
        "answered": answered, "failed": actionable and status_key(answer) in {"failed", "fail", "f"},
    }


def line_stats(lines):
    applicable = [x for x in lines if x["actionable"] and not x["na"]]
    answered = sum(x["answered"] for x in applicable)
    return {"total_steps": len(applicable), "answered_steps": answered,
            "failed_steps": sum(x["failed"] for x in applicable),
            "na_steps": sum(x["na"] for x in lines),
            "execution_pct": round(100 * answered / len(applicable), 2) if applicable else None}


def normalize_attempt(raw, lines):
    normalized = [normalize_line(x) for x in lines]
    return {"id": txt(raw.get("testattempt_id")), "number": number(raw.get("attempt_number")),
            "name": txt(raw.get("name")), "status": txt(raw.get("status")),
            "status_id": raw.get("status_id"), "status_change_date": txt(raw.get("status_change_date")),
            "status_change_person": txt(raw.get("status_change_person")),
            "date_created": txt(raw.get("date_created")), "template_name": txt(raw.get("template_name")),
            "time_to_close_seconds": raw.get("time_to_close_seconds"),
            "lines": normalized, **line_stats(normalized)}


def asset_id(key):
    return re.sub(r"^equipment[-:]", "", txt(key), flags=re.I)


def normalize_test(raw, attempts, project_id, complete_statuses):
    attempts.sort(key=lambda a: (a["number"], number(a["id"])))
    latest = attempts[-1] if attempts else None
    status = status_key(raw.get("status"))
    latest_status = status_key(latest["status"]) if latest else ""
    # Current test status is authoritative; a newer failed or open attempt
    # prevents a stale parent Passed status from overstating acceptance.
    accepted = status in complete_statuses and latest_status not in (FAILED | NOT_STARTED | PROGRESS)
    if status in FAILED or (latest and (latest_status in FAILED or latest["failed_steps"] > 0)):
        accepted = False
        bucket = "Retest required"
    elif accepted:
        bucket = "Complete"
    elif status in PROGRESS or (latest and (latest_status in PROGRESS or latest["answered_steps"] > 0)):
        bucket = "In progress"
    elif not status or status in NOT_STARTED:
        bucket = "Not started"
    else:
        bucket = "Status review required"
    return {"id": txt(raw.get("test_id")), "project_id": txt(project_id),
            "number": raw.get("number", ""), "name": txt(raw.get("name")),
            "asset_key": txt(raw.get("asset_key")), "asset_name": txt(raw.get("asset_name")),
            "asset_type": txt(raw.get("asset_type")), "discipline": txt(raw.get("discipline")),
            "assigned_name": txt(raw.get("assigned_name")), "status": txt(raw.get("status")),
            "status_id": raw.get("status_id"), "bucket": bucket, "accepted": accepted,
            "attempted": bucket in {"Complete", "In progress", "Retest required"},
            "attempt_count": len(attempts), "attempts": attempts,
            "latest_attempt_id": latest["id"] if latest else "",
            "completion_date": latest["status_change_date"] if accepted and latest else "",
            "total_steps": latest["total_steps"] if latest else 0,
            "answered_steps": latest["answered_steps"] if latest else 0,
            "failed_steps": latest["failed_steps"] if latest else 0,
            "na_steps": latest["na_steps"] if latest else 0,
            "execution_pct": latest["execution_pct"] if latest else None}


def fetch_project(client, project_id, complete_statuses):
    raw_tests = client.pages("/test", project_id, "test_id", body={"include": ["attempts", "lines", "extended_status", "time_to_close"]})
    result = []
    for i, raw in enumerate(raw_tests, 1):
        raw_attempts = records(raw["attempts"], "testattempt_id") if "attempts" in raw else []
        expected = number(raw.get("attempt_count"))
        if "attempts" not in raw or len(raw_attempts) != expected:
            raw_attempts = client.pages("/testattempt", project_id, "testattempt_id", params={"test_id": raw["test_id"], "include": "lines,time_to_close,extended_status"})
        if "attempt_count" in raw and len(raw_attempts) != expected:
            raise ValueError(f"Test {raw['test_id']}: attempt count changed; retry sync")
        attempts, seen = [], set()
        for a in raw_attempts:
            aid = txt(a.get("testattempt_id"))
            if not aid or aid in seen:
                raise ValueError("Missing/duplicate attempt ID")
            seen.add(aid)
            lines = records(a["lines"], "testattemptline_id") if "lines" in a else None
            if lines is None or len(lines) >= 500:
                lines = client.pages("/testattemptline", project_id, "testattemptline_id", params={"testattempt_id": aid})
            attempts.append(normalize_attempt(a, lines))
        result.append(normalize_test(raw, attempts, project_id, complete_statuses))
        if i % 100 == 0:
            print(f"Project {project_id}: {i}/{len(raw_tests)} tests normalized; {client.requests} requests")
    print(f"Project {project_id}: {len(result)} tests; statuses: {dict(Counter(t['status'] for t in result))}")
    return result


def build_equipment(tests, register):
    by_id, by_name = {}, defaultdict(list)
    equipment = []
    for r in register:
        e = {"project_id": txt(r.get("project_id")), "id": txt(r.get("equipment_id")),
             "name": txt(r.get("name")), "type": txt(r.get("type")),
             "discipline": txt(r.get("discipline")), "systems": txt(r.get("systems")),
             "building": txt(r.get("building")), "space": txt(r.get("space")), "test_ids": []}
        equipment.append(e)
        by_id[(e["project_id"], e["id"])] = e
        by_name[(e["project_id"], e["name"].casefold())].append(e)
    for t in tests:
        t["equipment_id"] = ""
        t["equipment_link"] = "Non-equipment asset"
        if txt(t["asset_type"]).casefold() != "equipment":
            continue
        match = by_id.get((t["project_id"], asset_id(t["asset_key"])))
        # Only fall back to an exact, unique name within this project.
        if match is None:
            candidates = by_name[(t["project_id"], t["asset_name"].casefold())]
            match = candidates[0] if len(candidates) == 1 else None
        if match is None:
            t["equipment_link"] = "Unmatched equipment"
            continue
        t["equipment_id"] = match["id"]
        t["equipment_link"] = "Linked equipment"
        match["test_ids"].append(t["id"])
    lookup = {(t["project_id"], t["id"]): t for t in tests}
    for e in equipment:
        linked = [lookup[(e["project_id"], k)] for k in e["test_ids"]]
        done = sum(t["accepted"] for t in linked)
        e.update({"test_count": len(linked), "completed_tests": done,
                  "attempt_count": sum(t["attempt_count"] for t in linked),
                  "total_steps": sum(t["total_steps"] for t in linked),
                  "answered_steps": sum(t["answered_steps"] for t in linked),
                  "failed_steps": sum(t["failed_steps"] for t in linked),
                  "completion_pct": round(100 * done / len(linked), 2) if linked else None})
        e["execution_pct"] = round(100 * e["answered_steps"] / e["total_steps"], 2) if e["total_steps"] else None
        buckets = {t["bucket"] for t in linked}
        e["status"] = ("No tests linked" if not linked else "Complete" if done == len(linked)
                       else "Retest required" if "Retest required" in buckets
                       else "Status review required" if "Status review required" in buckets
                       else "In progress" if buckets & {"Complete", "In progress"} else "Not started")
    return sorted(equipment, key=lambda e: (e["project_id"], e["name"]))


def summary(tests, equipment):
    statuses = Counter(t["bucket"] for t in tests)
    total = sum(t["total_steps"] for t in tests)
    done = sum(t["accepted"] for t in tests)
    tracked = [e for e in equipment if e["test_count"]]
    return {"test_count": len(tests), "completed_tests": done,
            "completion_pct": round(100 * done / len(tests), 2) if tests else None,
            "attempt_count": sum(t["attempt_count"] for t in tests),
            "attempted_tests": sum(t["attempted"] for t in tests),
            "total_steps": total, "answered_steps": sum(t["answered_steps"] for t in tests),
            "execution_pct": round(100 * sum(t["answered_steps"] for t in tests) / total, 2) if total else None,
            "equipment_count": len(equipment), "tracked_equipment": len(tracked),
            "completed_equipment": sum(e["status"] == "Complete" for e in tracked),
            "equipment_no_tests": len(equipment) - len(tracked), "statuses": dict(statuses),
            "unmapped_tests": sum(t["equipment_link"] != "Linked equipment" for t in tests)}


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def publish(tests, equipment, complete_statuses, directory=Path("data")):
    directory.mkdir(exist_ok=True, parents=True)
    now = datetime.now(timezone.utc)
    snapshot = now.astimezone(ZoneInfo("Asia/Kuala_Lumpur")).date().isoformat()
    s = summary(tests, equipment)
    current = {"schema_version": 1, "last_synced": now.isoformat(), "snapshot_date": snapshot,
               "complete_statuses": sorted(complete_statuses), "summary": s, "tests": tests, "equipment": equipment}
    history_path = directory / "l4_daily.csv"
    fields = ["snapshot_date", "project_id", "test_count", "completed_tests", "completion_pct", "attempt_count",
              "attempted_tests", "total_steps", "answered_steps", "execution_pct", "tracked_equipment", "completed_equipment", "last_synced"]
    old = []
    if history_path.exists():
        with history_path.open(encoding="utf-8", newline="") as f:
            old = list(csv.DictReader(f))
    projects = sorted({t["project_id"] for t in tests} | {e["project_id"] for e in equipment})
    old = [r for r in old if not (r.get("snapshot_date") == snapshot and r.get("project_id") in projects)]
    for pid in projects:
        old.append({"snapshot_date": snapshot, "project_id": pid, "last_synced": now.isoformat(),
                    **summary([t for t in tests if t["project_id"] == pid], [e for e in equipment if e["project_id"] == pid])})
    # Build temporary outputs only after all projects/attempts/lines succeeded.
    temp = directory / "l4_current.json.tmp"
    temp.write_text(json.dumps(current, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    write_csv(directory / "l4_daily.csv.tmp", sorted(old, key=lambda r: (r["snapshot_date"], r["project_id"])), fields)
    export_fields = ["project_id", "id", "number", "name", "asset_name", "asset_type", "equipment_id", "equipment_link",
                     "discipline", "assigned_name", "status", "bucket", "accepted", "attempt_count", "latest_attempt_id",
                     "completion_date", "total_steps", "answered_steps", "failed_steps", "na_steps", "execution_pct"]
    write_csv(directory / "l4_tests.csv.tmp", tests, export_fields)
    for name in ["l4_current.json", "l4_daily.csv", "l4_tests.csv"]:
        (directory / (name + ".tmp")).replace(directory / name)
    print(f"L4 published: {s['test_count']} tests, {s['completed_tests']} accepted, {s['attempt_count']} attempts")


def main():
    complete_statuses = {status_key(s) for s in os.environ.get("L4_COMPLETE_STATUSES", "passed,completed,reviewed").split(",") if txt(s)}
    client = Client()
    projects = [p.strip() for p in os.environ["CXALLOY_PROJECT_ID"].split(",") if p.strip()]
    tests = []
    for project in projects:
        tests.extend(fetch_project(client, project, complete_statuses))
    with Path("data/equipment_status.csv").open(encoding="utf-8-sig", newline="") as f:
        register = [r for r in csv.DictReader(f) if txt(r.get("project_id")) in projects]
    equipment = build_equipment(tests, register)
    publish(tests, equipment, complete_statuses)


if __name__ == "__main__":
    main()
