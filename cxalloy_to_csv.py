"""
CxAlloy -> CSV file sync.

Pulls all equipment (with extended_status and attributes) for one or more
CxAlloy projects and writes it to a single CSV file in this repo. A GitHub
Actions workflow runs this daily and commits the updated file. Power BI
reads the CSV directly from GitHub.

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
import re
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

# What we ask the /equipment endpoint to include, comma-separated.
# "extended_status" -> tag-stage history (dates/people per commissioning stage)
# "attributes"      -> project-configured custom fields (Supplier, Manufacturer, etc.)
# "systems"         -> systems this equipment is linked to (e.g. Chilled Water System)
EQUIPMENT_INCLUDES = "extended_status,attributes,systems"

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
# Keyed by UPPERCASE so the match works regardless of how CxAlloy actually
# capitalizes status text (seen as all-caps in practice, e.g. "L1 RED TAG").
LABEL_TO_STAGE = {label.upper(): stage for stage, label in TAG_STAGE_LABELS.items()}


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

    If `status` doesn't match any known stage label exactly (case-insensitive),
    nothing is cleared (safer to leave data alone than guess wrong) - the
    unmatched value is recorded in `unmatched_statuses` so it can be
    reported once, at the end of the run, instead of failing silently.
    """
    stage_key = LABEL_TO_STAGE.get((status or "").strip().upper())

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


def slugify_attribute_name(name: str) -> str:
    """
    Turns an attribute's display name into a CSV-safe column name, e.g.
    "Equipment Supplier" -> "equipment_supplier". Any character that isn't
    a letter/digit becomes an underscore, and repeats/edges are collapsed,
    so "Area / Type!" -> "area_type" rather than "area___type_".
    """
    slug = re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
    return slug or "attribute"


def flatten_attributes(attributes, unmatched_attribute_shapes: set) -> dict:
    """
    Turns the equipment's `attributes` field (returned when
    include=attributes) into a flat {column_name: value} dict covering
    EVERY attribute set on that equipment - not just specific ones - so
    the CSV ends up with one column per attribute your project has
    configured (Equipment Supplier, Area Type, Tranche, Manufacturer,
    Serial Number, whatever else exists), generated automatically rather
    than hardcoded here.

    Expects the confirmed shape:
      {"name": "Equipment Supplier", "value": "Bezaire Sdn Bhd",
       "unit": "", "verified": "0", ...}

    Anything that doesn't match this shape (missing a "name" key, or the
    whole `attributes` field not being a list) gets recorded in
    `unmatched_attribute_shapes` instead of silently vanishing, so it
    surfaces as a warning at the end of the run.

    NOTE ON COLUMN STABILITY: since columns are derived from whatever
    attribute names actually appear in this run's data, an attribute that
    happens to be unset on every piece of equipment today won't produce a
    column today - and will reappear once something has it set. If a
    downstream tool expects a fixed set of columns, that's worth knowing
    before relying on this.
    """
    flat = {}

    if not isinstance(attributes, list):
        if attributes:
            unmatched_attribute_shapes.add(repr(attributes)[:80])
        return flat

    for item in attributes:
        if not isinstance(item, dict) or "name" not in item:
            unmatched_attribute_shapes.add(repr(item)[:80])
            continue

        column = slugify_attribute_name(item["name"])
        value = item.get("value")
        flat[column] = value if value is not None else ""

    return flat


def get_system_names(systems, unmatched_system_shapes: set) -> str:
    """
    Turns the equipment's `systems` field (returned when include=systems)
    into a single semicolon-separated string of system names - equipment
    can be linked to more than one system, so this joins all of them
    rather than picking just one.

    Expects a list of dicts, each with a "name" field (matching the
    pattern seen elsewhere in the API, e.g. attribute entries also use
    "name"). Falls back to a couple of other likely key names ("system_name",
    "system") in case that assumption is wrong for this endpoint.

    NOTE: this hasn't been confirmed against the actual schema for this
    include - if the "systems" column comes back empty for every row (the
    same failure mode we just hit with equipment_supplier_value), check the
    unmatched_system_shapes warning printed at the end of the run - it'll
    show you the raw shape so the key name here can be corrected.
    """
    if not isinstance(systems, list):
        if systems:
            unmatched_system_shapes.add(repr(systems)[:80])
        return ""

    names = []
    for item in systems:
        if isinstance(item, dict):
            name = item.get("name") or item.get("system_name") or item.get("system")
            if name:
                names.append(str(name))
            else:
                unmatched_system_shapes.add(repr(item)[:80])
        elif isinstance(item, str):
            names.append(item)
        else:
            unmatched_system_shapes.add(repr(item)[:80])

    return "; ".join(names)


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
        params = {
            "project_id": project_id,
            "include": EQUIPMENT_INCLUDES,
            "page": page,
        }
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

    unmatched_statuses = set()
    unmatched_system_shapes = set()
    unmatched_attribute_shapes = set()

    # Flatten every equipment's attributes up front so we know the full set
    # of attribute columns before writing the CSV header.
    flat_attributes_by_record = []
    attribute_columns = set()
    for eq in all_equipment:
        flat_attrs = flatten_attributes(eq.get("attributes"), unmatched_attribute_shapes)
        flat_attributes_by_record.append(flat_attrs)
        attribute_columns.update(flat_attrs.keys())

    # Sorted for a stable column order across runs (avoids noisy diffs in
    # the committed CSV just because set ordering shifted between runs).
    attribute_columns = sorted(attribute_columns)

    fields = (
        ["project_id", "equipment_id", "name", "type", "discipline",
         "building", "floor", "space", "status"]
        + attribute_columns
        + ["systems"]
        + EXTENDED_STATUS_FIELDS
        + ["current_stage", "current_stage_date", "current_stage_person", "last_synced"]
    )

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        # restval="" fills in blank cells for equipment missing a given
        # attribute (e.g. a VAV box won't have every field an AHU has).
        writer = csv.DictWriter(f, fieldnames=fields, restval="")
        writer.writeheader()
        for eq, flat_attrs in zip(all_equipment, flat_attributes_by_record):
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
                "systems": get_system_names(eq.get("systems"), unmatched_system_shapes),
                "last_synced": now,
            }
            row.update(flat_attrs)

            flat_status = flatten_extended_status(eq.get("extended_status"))
            flat_status = clean_stale_future_dates(flat_status, status, unmatched_statuses)
            row.update(flat_status)

            writer.writerow(row)

    print(f"Wrote {len(all_equipment)} rows to {OUTPUT_PATH}")
    print(f"Attribute columns found this run: {attribute_columns}")

    if unmatched_statuses:
        print(
            f"WARNING: {len(unmatched_statuses)} distinct status value(s) didn't match "
            f"any known tag stage, so rollback cleanup was skipped for those rows: "
            f"{sorted(unmatched_statuses)}"
        )

    if unmatched_system_shapes:
        print(
            f"WARNING: {len(unmatched_system_shapes)} 'systems' entries didn't match "
            f"the expected shape and were skipped - inspect these and update "
            f"get_system_names() key names if needed:\n"
            + "\n".join(f"  {s}" for s in sorted(unmatched_system_shapes))
        )

    if unmatched_attribute_shapes:
        print(
            f"WARNING: {len(unmatched_attribute_shapes)} attribute entries didn't match "
            f"the expected shape and were skipped:\n"
            + "\n".join(f"  {s}" for s in sorted(unmatched_attribute_shapes))
        )




if __name__ == "__main__":
    main()
