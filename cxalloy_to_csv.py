"""
One-off diagnostic: find where "supplier" data actually lives in the
CxAlloy /equipment response.

Why this exists: the flat top-level "equipment_supplier_value" field came
back empty for every record in the real sync. Rather than guess a third
possible shape blind, this walks the ENTIRE raw JSON response for a batch
of equipment records and reports every spot where a key name OR a string
value contains "supplier" (case-insensitive) - along with the surrounding
object, so you can see the real field names to use back in cxalloy_sync.py.

This catches shapes like:
  {"equipment_supplier_value": "Trane"}                       <- key match
  {"attribute": "Equipment Supplier", "value": "Trane"}       <- value match
  {"name": "Supplier", "attribute_value": "Trane"}             <- value match

Run this once locally (or as a manual GitHub Actions run) with the same
env vars as the main sync script:
  CXALLOY_IDENTIFIER
  CXALLOY_SECRET
  CXALLOY_PROJECT_ID   - one project id is enough for this diagnostic

    python diagnose_supplier_field.py
"""

import os
import time
import hmac
import hashlib
import json

import requests

CXALLOY_IDENTIFIER = os.environ["CXALLOY_IDENTIFIER"]
CXALLOY_SECRET = os.environ["CXALLOY_SECRET"]
CXALLOY_PROJECT_IDS = [
    p.strip() for p in os.environ["CXALLOY_PROJECT_ID"].split(",") if p.strip()
]

CXALLOY_BASE_URL = "https://tq.cxalloy.com/api/v1"

# How many equipment records to pull per project while searching. Small on
# purpose since this is just a diagnostic - raise it if nothing turns up.
SAMPLE_SIZE = 25


def cxalloy_headers() -> dict:
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
        "user-agent": "GitHubActions-CxAlloySync-Diagnostic/1.0",
    }


def fetch_sample_equipment(project_id: str, limit: int) -> list:
    resp = requests.get(
        f"{CXALLOY_BASE_URL}/equipment",
        headers=cxalloy_headers(),
        params={
            "project_id": project_id,
            "include": "extended_status,attributes",
            "page": 1,
        },
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

    return batch[:limit]


def find_supplier_mentions(obj, path=""):
    """
    Recursively walks obj (nested dicts/lists) and returns a list of
    (path, context) for every spot where either a key name or a string
    value contains "supplier" (case-insensitive). `context` is the
    dict the match was found in, so you can see the real field names
    sitting right next to it.
    """
    matches = []

    if isinstance(obj, dict):
        hit_here = False
        for k, v in obj.items():
            if "supplier" in str(k).lower():
                hit_here = True
            if isinstance(v, str) and "supplier" in v.lower():
                hit_here = True
        if hit_here:
            matches.append((path or "(root)", obj))

        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else str(k)
            matches.extend(find_supplier_mentions(v, new_path))

    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            matches.extend(find_supplier_mentions(item, f"{path}[{i}]"))

    return matches


def dedupe(matches):
    seen = set()
    deduped = []
    for path, context in matches:
        key = (path, json.dumps(context, sort_keys=True, default=str))
        if key not in seen:
            seen.add(key)
            deduped.append((path, context))
    return deduped


def main():
    any_match_found = False
    first_record_for_fallback = None

    for project_id in CXALLOY_PROJECT_IDS:
        print(f"\n=== Project {project_id}: sampling {SAMPLE_SIZE} equipment records ===")
        sample = fetch_sample_equipment(project_id, SAMPLE_SIZE)
        print(f"  Pulled {len(sample)} records")

        for eq in sample:
            if first_record_for_fallback is None:
                first_record_for_fallback = eq

            matches = dedupe(find_supplier_mentions(eq))
            if matches:
                any_match_found = True
                eq_label = eq.get("name") or eq.get("equipment_id") or "(unnamed)"
                print(f"\n  Equipment: {eq_label}")
                for path, context in matches:
                    print(f"    Path:  {path}")
                    print(f"    Value: {json.dumps(context, indent=2, default=str)}")

    if not any_match_found:
        print(
            "\nNo mention of 'supplier' found anywhere (key or value) in the "
            f"sampled equipment records across {len(CXALLOY_PROJECT_IDS)} project(s)."
        )
        if first_record_for_fallback is not None:
            print(
                "\nHere's one full raw record so you can scan it manually - "
                "maybe it's labeled differently in your project (e.g. "
                "'Vendor', 'Manufacturer', 'Mfr'):\n"
            )
            print(json.dumps(first_record_for_fallback, indent=2, default=str))
        else:
            print("No equipment records were returned at all - check project_id/env vars.")


if __name__ == "__main__":
    main()
