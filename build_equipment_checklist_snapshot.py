"""Build a dashboard-friendly checklist completion snapshot.

Input:
  data/checklist_progress_current.csv
  data/equipment_status.csv

Output:
  data/checklist_completion_by_equipment.csv

One row per equipment, with L1-L5 checklist completion percentages and counts.
The actual equipment type is joined from equipment_status.csv.
"""

import csv
from collections import defaultdict

PROGRESS_PATH = "data/checklist_progress_current.csv"
EQUIPMENT_PATH = "data/equipment_status.csv"
OUTPUT_PATH = "data/checklist_completion_by_equipment.csv"
LEVELS = ["L1", "L2", "L3", "L4", "L5"]

BASE_FIELDS = [
    "snapshot_date", "project_id", "asset_key", "asset_name", "asset_type",
    "equipment_type", "discipline", "building", "floor", "space", "tranche",
    "systems", "equipment_supplier", "overall_completion_pct",
    "overall_completed_lines", "overall_total_lines", "overall_open_lines",
]
LEVEL_FIELDS = []
for level in LEVELS:
    LEVEL_FIELDS += [
        f"{level}_completion_pct",
        f"{level}_completed_lines",
        f"{level}_total_lines",
        f"{level}_open_lines",
        f"{level}_checklist_count",
    ]
FIELDS = BASE_FIELDS + LEVEL_FIELDS + ["last_synced"]


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_int(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def main():
    progress = read_csv(PROGRESS_PATH)
    equipment = read_csv(EQUIPMENT_PATH)

    equipment_lookup = {}
    for row in equipment:
        equipment_lookup[(row.get("project_id", ""), row.get("name", ""))] = row

    grouped = defaultdict(lambda: {
        "snapshot_date": "",
        "asset_name": "",
        "asset_type": "",
        "last_synced": "",
        "levels": {},
    })

    for row in progress:
        project_id = row.get("project_id", "")
        asset_key = row.get("asset_key", "") or row.get("asset_name", "")
        level = row.get("commissioning_level", "")
        if not asset_key or level not in LEVELS:
            continue
        bucket = grouped[(project_id, asset_key)]
        bucket["snapshot_date"] = row.get("snapshot_date", "")
        bucket["asset_name"] = row.get("asset_name", "") or bucket["asset_name"]
        bucket["asset_type"] = row.get("asset_type", "") or bucket["asset_type"]
        bucket["last_synced"] = row.get("last_synced", "")
        bucket["levels"][level] = row

    output = []
    for (project_id, asset_key), bucket in sorted(grouped.items()):
        asset_name = bucket["asset_name"]
        eq = equipment_lookup.get((project_id, asset_name), {})

        total_all = 0
        completed_all = 0
        out = {
            "snapshot_date": bucket["snapshot_date"],
            "project_id": project_id,
            "asset_key": asset_key,
            "asset_name": asset_name,
            "asset_type": bucket["asset_type"],
            "equipment_type": eq.get("type", ""),
            "discipline": eq.get("discipline", ""),
            "building": eq.get("building", ""),
            "floor": eq.get("floor", ""),
            "space": eq.get("space", ""),
            "tranche": eq.get("tranche", ""),
            "systems": eq.get("systems", ""),
            "equipment_supplier": eq.get("equipment_supplier", ""),
            "last_synced": bucket["last_synced"],
        }

        for level in LEVELS:
            row = bucket["levels"].get(level)
            if row:
                total = as_int(row.get("total_lines"))
                completed = as_int(row.get("completed_lines"))
                open_lines = as_int(row.get("open_lines"))
                pct = row.get("completion_pct", "")
                checklist_count = as_int(row.get("checklist_count"))
                total_all += total
                completed_all += completed
            else:
                total = completed = open_lines = checklist_count = 0
                pct = ""

            out[f"{level}_completion_pct"] = pct
            out[f"{level}_completed_lines"] = completed
            out[f"{level}_total_lines"] = total
            out[f"{level}_open_lines"] = open_lines
            out[f"{level}_checklist_count"] = checklist_count

        out["overall_total_lines"] = total_all
        out["overall_completed_lines"] = completed_all
        out["overall_open_lines"] = total_all - completed_all
        out["overall_completion_pct"] = round(completed_all / total_all * 100, 2) if total_all else ""
        output.append(out)

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(output)

    print(f"Wrote {len(output)} equipment checklist snapshot rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
