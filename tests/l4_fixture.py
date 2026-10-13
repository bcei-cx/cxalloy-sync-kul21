"""Generate synthetic browser-test data; never publish as dashboard data."""
import json
from datetime import datetime, timezone
from pathlib import Path
from test_l4_sync import test, attempt
from cxalloy_l4_sync import COMPLETE, build_equipment, summary

register = [{"project_id": "67", "equipment_id": str(10+i), "name": f"UPS-{i+1:03d}",
             "type": "UPS", "discipline": "Electrical"} for i in range(103)]
tests = [test(1, asset="equipment-10", name="UPS-001"),
         test(2, asset="equipment-11", name="UPS-002", status="Failed",
              attempts=[attempt(2, status="Failed", answer="failed")]),
         test(3, asset="equipment-12", name="UPS-003", status="In Progress",
              attempts=[attempt(3, status="In Progress", answer="")])]
tests[0]["attempts"][0]["lines"][0]["description"] = "<img src=x onerror=alert(1)>"
equipment = build_equipment(tests, register)
Path("l4-ui-fixture.json").write_text(json.dumps({
    "schema_version": 1, "last_synced": datetime.now(timezone.utc).isoformat(),
    "snapshot_date": "2026-10-13", "complete_statuses": sorted(COMPLETE),
    "summary": summary(tests, equipment), "tests": tests, "equipment": equipment,
}), encoding="utf-8")
