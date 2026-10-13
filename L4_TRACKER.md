# KUL21 L4 tracker

Open `index.html#l4-overview`, `#l4-equipment`, or `#l4-tests` on the existing
dashboard. All CxAlloy Tests are treated as L4; Checklists are independent.

## Calculations

- L4 completion: accepted current tests divided by registered tests, equally
  weighted. This is registered scope, not proof that all required tests exist.
- Equipment completion: accepted linked tests divided by linked tests.
  Equipment without tests shows `No tests linked` and an unknown percentage.
- Execution: answered applicable steps in the latest attempt only. Failed
  answers count as executed but cannot make a test accepted. N/A answers,
  headers, and information rows are excluded from applicable steps.
- Total attempts: all recorded attempts, including empty and superseded
  attempts. Tests attempted requires execution evidence/status, not just an
  empty template attempt.
- Default accepted test statuses: `Passed`, `Completed`, `Reviewed`, matched
  case-insensitively. Override with repository variable `L4_COMPLETE_STATUSES`
  (comma-separated). A failed or reopened latest attempt prevents stale parent
  acceptance. Unrecognized statuses are shown for review, never accepted.
- Acceptance date: the accepted latest attempt's status-change date; no date
  is inferred from creation. This is not a separate witness/sign-off date.
- Match equipment by project ID and equipment ID, then exact unique asset
  name. System/space tests stay in project totals without automatically being
  allocated to equipment. Equipment that is out of L4 scope still appears with
  no linked tests until a required-scope register is supplied.

## Sync

`cxalloy_l4_sync.py` uses the existing GitHub Actions secrets and project variable.
It reads Tests/Attempts/Lines only; it never changes CxAlloy records. The script
fetches paginated tests and uses separate paginated attempt/line requests where
embedded records are absent. Requests are throttled and retried. An inconsistent
attempt count, duplicate record, or extraction failure prevents publication.

Outputs:

- `data/l4_current.json`: current equipment, tests, attempts and step details.
- `data/l4_tests.csv`: flat test register.
- `data/l4_daily.csv`: daily project summaries in Malaysia time; reruns replace
  the same day's summary. History begins with the first successful L4 sync.

If L4 extraction fails, existing equipment/checklist/issue updates can still be
committed. The workflow reports the L4 failure and retains its prior snapshot.
The UI never substitutes sample data; it flags a snapshot older than 36 hours.
L4 uses the current snapshot, independently of the tag dashboard's date picker.

Run the regression checks with `python -m unittest -q test_l4_sync.py`.
