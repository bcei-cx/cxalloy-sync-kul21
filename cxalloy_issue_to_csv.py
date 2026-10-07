"""
CxAlloy issues -> CSV sync.

Fetches the project issue log using POST /issue for all configured projects.
"""
import os, time, hmac, hashlib, json, csv
from datetime import datetime, timezone
import requests

CXALLOY_IDENTIFIER=os.environ["CXALLOY_IDENTIFIER"]
CXALLOY_SECRET=os.environ["CXALLOY_SECRET"]
CXALLOY_PROJECT_IDS=[p.strip() for p in os.environ["CXALLOY_PROJECT_ID"].split(",") if p.strip()]
CXALLOY_BASE_URL="https://tq.cxalloy.com/api/v1"
OUTPUT_PATH="data/issues.csv"
PER_PAGE=500

FIELDS=[
    "project_id","issue_id","name","description","asset_name","asset_type","asset_key",
    "section","drawing","priority_id","priority","due_date","date_closed","assigned_name",
    "assigned_type","assigned_key","discipline_id","discipline","issuetype_id","issuetype",
    "status_id","status","source_name","source_type","source_id","created_by","date_created",
    "last_synced"
]

def headers(body_str):
    ts=int(time.time())
    sig=hmac.new(CXALLOY_SECRET.encode(),(body_str+str(ts)).encode(),hashlib.sha256).hexdigest()
    return {
        "Content-Type":"application/json",
        "cxalloy-identifier":CXALLOY_IDENTIFIER,
        "cxalloy-signature":sig,
        "cxalloy-timestamp":str(ts),
        "user-agent":"GitHubActions-CxAlloySync/1.0",
    }

def fetch_project(project_id):
    out=[]; page=1
    while page<=500:
        body={"project_id":int(project_id),"page":page,"perpage":PER_PAGE}
        body_str=json.dumps(body,separators=(",",":"))
        r=requests.post(f"{CXALLOY_BASE_URL}/issue",headers=headers(body_str),data=body_str,timeout=45)
        r.raise_for_status()
        payload=r.json()
        records=payload.get("records",[])
        out.extend(records)
        if len(records)<PER_PAGE: break
        page+=1
    return out

def first(record,*keys):
    for k in keys:
        v=record.get(k)
        if v not in (None,""): return v
    return ""

def main():
    all_rows=[]
    for pid in CXALLOY_PROJECT_IDS:
        print(f"Fetching issues for project {pid}...")
        rows=fetch_project(pid)
        print(f"  -> {len(rows)} records")
        for x in rows:
            all_rows.append({
                "project_id":first(x,"project_id") or pid,
                "issue_id":first(x,"issue_id","id"),
                "name":first(x,"name","number"),
                "description":first(x,"description"),
                "asset_name":first(x,"asset_name"),
                "asset_type":first(x,"asset_type"),
                "asset_key":first(x,"asset_key"),
                "section":first(x,"section"),
                "drawing":first(x,"drawing"),
                "priority_id":first(x,"priority_id"),
                "priority":first(x,"priority"),
                "due_date":first(x,"due_date"),
                "date_closed":first(x,"date_closed"),
                "assigned_name":first(x,"assigned_name"),
                "assigned_type":first(x,"assigned_type"),
                "assigned_key":first(x,"assigned_key"),
                "discipline_id":first(x,"discipline_id","disipline_id"),
                "discipline":first(x,"discipline","disipline"),
                "issuetype_id":first(x,"issuetype_id"),
                "issuetype":first(x,"issuetype","issue_type"),
                "status_id":first(x,"status_id"),
                "status":first(x,"status"),
                "source_name":first(x,"source_name"),
                "source_type":first(x,"source_type"),
                "source_id":first(x,"source_id"),
                "created_by":first(x,"created_by"),
                "date_created":first(x,"date_created"),
            })
    os.makedirs("data",exist_ok=True)
    now=datetime.now(timezone.utc).isoformat()
    with open(OUTPUT_PATH,"w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS)
        w.writeheader()
        for row in all_rows:
            row["last_synced"]=now
            w.writerow({k:row.get(k,"") for k in FIELDS})
    print(f"Wrote {len(all_rows)} issues to {OUTPUT_PATH}")

if __name__=="__main__":
    main()
