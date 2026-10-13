"""Acceptance, execution, mapping and extraction regression checks."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from cxalloy_l4_sync import (Client, COMPLETE, build_equipment, fetch_project,
                            line_stats, normalize_attempt, normalize_line,
                            normalize_test, publish, summary)


def attempt(aid=1, status="Passed", answer="passed", number=1):
    return normalize_attempt({"testattempt_id": aid, "attempt_number": number,
                              "status": status, "status_change_date": "2026-10-13"},
                             [{"testattemptline_id": aid, "line_number": 1,
                               "type": "standard_question", "answer": answer}])


def test(tid=1, status="Passed", attempts=None, asset="equipment-10", name="UPS-01", asset_type="Equipment"):
    return normalize_test({"test_id": tid, "name": "L4 test", "status": status,
                           "asset_key": asset, "asset_name": name, "asset_type": asset_type},
                          [attempt()] if attempts is None else attempts, "67", COMPLETE)


class L4Tests(unittest.TestCase):
    def test_zero_reading_and_empty_metadata(self):
        self.assertTrue(normalize_line({"type": "attribute", "attribute_value": 0})["answered"])
        self.assertFalse(normalize_line({"type": "attribute", "value": {"is_valid": True, "value": ""}})["answered"])

    def test_applicable_steps_exclude_na_and_display_rows(self):
        lines = [normalize_line(x) for x in [
            {"type": "header", "answer": "passed"},
            {"type": "information"},
            {"type": "standard_question", "answer": "na"},
            {"type": "standard_question", "answer": "failed"},
            {"type": "attribute", "attribute_value": 0},
            {"type": "standard_question", "answer": ""},
        ]]
        stats = line_stats(lines)
        self.assertEqual((stats["total_steps"], stats["answered_steps"], stats["failed_steps"], stats["na_steps"]), (3, 2, 1, 1))
        self.assertAlmostEqual(stats["execution_pct"], 66.67)

    def test_failed_answers_never_accept_parent_pass(self):
        t = test(attempts=[attempt(status="Failed", answer="failed")])
        self.assertFalse(t["accepted"])
        self.assertEqual(t["bucket"], "Retest required")
        self.assertEqual(t["execution_pct"], 100)
        self.assertEqual(t["completion_date"], "")

    def test_reopened_uses_latest_attempt_not_historic_pass(self):
        old = attempt(1, number=1)
        new = attempt(2, status="In Progress", answer="", number=2)
        t = test(attempts=[new, old])
        self.assertFalse(t["accepted"])
        self.assertEqual(t["bucket"], "In progress")
        self.assertEqual(t["execution_pct"], 0)
        self.assertEqual(t["latest_attempt_id"], "2")
        self.assertEqual(t["attempt_count"], 2)

    def test_template_attempt_is_not_execution(self):
        t = test(status="Not Started", attempts=[attempt(status="Not Started", answer="")])
        self.assertFalse(t["attempted"])
        self.assertEqual(t["attempt_count"], 1)
        self.assertEqual(t["bucket"], "Not started")

    def test_unknown_status_requires_review(self):
        t = test(status="Witness Pending", attempts=[])
        self.assertEqual(t["bucket"], "Status review required")
        self.assertFalse(t["accepted"])

    def test_equipment_mapping_and_missing_scope(self):
        tests = [test(), test(2, asset="999", name="DUPLICATE"),
                 test(3, asset="10", name="UPS-01", asset_type="System")]
        register = [{"project_id": "67", "equipment_id": "10", "name": "UPS-01"},
                    {"project_id": "67", "equipment_id": "11", "name": "DUPLICATE"},
                    {"project_id": "67", "equipment_id": "12", "name": "DUPLICATE"}]
        equipment = build_equipment(tests, register)
        self.assertEqual(tests[0]["equipment_id"], "10")
        self.assertEqual(tests[1]["equipment_link"], "Unmatched equipment")
        self.assertEqual(tests[2]["equipment_link"], "Non-equipment asset")
        missing = [e for e in equipment if not e["test_count"]]
        self.assertEqual(len(missing), 2)
        self.assertTrue(all(e["completion_pct"] is None and e["status"] == "No tests linked" for e in missing))
        s = summary(tests, equipment)
        self.assertEqual(s["test_count"], 3)
        self.assertEqual(s["tracked_equipment"], 1)

    def test_no_tests_is_unknown_not_complete(self):
        self.assertIsNone(summary([], [])["completion_pct"])

    def test_pagination_rejects_repeated_ids(self):
        class Mock(Client):
            def __init__(self):
                pass
            def request(self, *args, **kwargs):
                return {"records": [{"test_id": n} for n in range(100)]}
        with self.assertRaises(ValueError):
            Mock().pages("/test", "67", "test_id", body={})

    def test_missing_embedded_attempts_and_lines_use_get(self):
        class Mock:
            requests = 3
            calls = []
            def pages(self, endpoint, *args, **kwargs):
                self.calls.append(endpoint)
                if endpoint == "/test":
                    return [{"test_id": 1, "status": "Passed", "attempt_count": 1}]
                if endpoint == "/testattempt":
                    return [{"testattempt_id": 2, "attempt_number": 1, "status": "Passed"}]
                return [{"testattemptline_id": 3, "type": "attribute", "attribute_value": 0}]
        mock = Mock()
        rows = fetch_project(mock, "67", COMPLETE)
        self.assertEqual(mock.calls, ["/test", "/testattempt", "/testattemptline"])
        self.assertEqual(rows[0]["execution_pct"], 100)

    def test_attempt_count_mismatch_fails_extraction(self):
        class Mock:
            def pages(self, endpoint, *args, **kwargs):
                if endpoint == "/test":
                    return [{"test_id": 1, "attempt_count": 2, "attempts": []}]
                return [{"testattempt_id": 2, "attempt_number": 1, "status": "Passed", "lines": []}]
        with self.assertRaises(ValueError):
            fetch_project(Mock(), "67", COMPLETE)

    def test_daily_snapshot_is_replaced_not_duplicated(self):
        tests = [test()]
        eq = build_equipment(tests, [{"project_id": "67", "equipment_id": "10", "name": "UPS-01"}])
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            publish(tests, eq, COMPLETE, directory)
            publish(tests, eq, COMPLETE, directory)
            with (directory / "l4_daily.csv").open() as f:
                self.assertEqual(len(list(csv.DictReader(f))), 1)
            current = json.loads((directory / "l4_current.json").read_text())
            self.assertEqual(current["summary"]["completion_pct"], 100)


if __name__ == "__main__":
    unittest.main()
