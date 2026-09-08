"""One-time migration: make the hosted dashboard independent of cxalloy-kul21-dashboard."""
from pathlib import Path
import requests

OLD_REPO = "https://raw.githubusercontent.com/sapoetra/cxalloy-kul21-dashboard/main"
PROJECTED_LOCAL = Path("data/projected_dates.xlsx")
INDEX = Path("index.html")

PROJECTED_REMOTE_URL = f"{OLD_REPO}/projected_dates.xlsx"


def main():
    if not INDEX.exists():
        raise SystemExit("index.html is missing; refusing standalone migration")

    # Copy the projected schedule into this repository once. The workflow commits
    # the binary file, so future runs/clones no longer need the old repository.
    if not PROJECTED_LOCAL.exists():
        PROJECTED_LOCAL.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(PROJECTED_REMOTE_URL, timeout=120)
        r.raise_for_status()
        PROJECTED_LOCAL.write_bytes(r.content)
        print(f"Copied projected dates to {PROJECTED_LOCAL} ({len(r.content)} bytes)")
    else:
        print(f"Projected dates already local: {PROJECTED_LOCAL}")

    html = INDEX.read_text(encoding="utf-8")
    replacements = [
        PROJECTED_REMOTE_URL,
        "https://raw.githubusercontent.com/sapoetra/cxalloy-kul21-dashboard/main/projected_dates.xlsx",
    ]
    for old in replacements:
        html = html.replace(old, "./data/projected_dates.xlsx")

    # The equipment data should also be local in the standalone repository.
    html = html.replace(
        "https://raw.githubusercontent.com/sapoetra/cxalloy-kul21-dashboard/main/equipment_status.csv",
        "./data/equipment_status.csv",
    )

    if "cxalloy-kul21-dashboard" in html:
        raise SystemExit("index.html still contains a cxalloy-kul21-dashboard reference")

    INDEX.write_text(html, encoding="utf-8")
    print("index.html now uses only local dashboard data files")


if __name__ == "__main__":
    main()
