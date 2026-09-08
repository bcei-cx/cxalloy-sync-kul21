import csv
import os
from collections import defaultdict

CURRENT_PATH='data/checklist_progress_current.csv'
EQUIPMENT_PATH='data/equipment_status.csv'
DAILY_TYPE_PATH='data/checklist_progress_daily_type.csv'
EQUIPMENT_CHANGES_PATH='data/checklist_progress_equipment_changes.csv'

TYPE_FIELDS=['snapshot_date','week_start','project_id','equipment_type','commissioning_level','equipment_count','total_lines','completed_lines','open_lines','completion_pct','last_synced']
CHANGE_FIELDS=['snapshot_date','week_start','project_id','asset_key','asset_name','commissioning_level','total_lines','completed_lines','completion_pct']

def read_csv(path):
    if not os.path.exists(path): return []
    with open(path,newline='',encoding='utf-8') as f:
        return list(csv.DictReader(f))

def write_csv(path,fields,rows):
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,'w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)

def n(v):
    try:return int(float(v or 0))
    except:return 0

def pct(c,t):
    return round(c/t*100,2) if t else 0

def main():
    current=read_csv(CURRENT_PATH)
    equipment=read_csv(EQUIPMENT_PATH)
    if not current: raise SystemExit('No current checklist progress found')

    type_map={(str(r.get('project_id','')),str(r.get('name',''))):str(r.get('type','') or '') for r in equipment}
    snapshot=current[0].get('snapshot_date','')
    week_start=current[0].get('week_start','')
    last_synced=current[0].get('last_synced','')

    grouped=defaultdict(lambda:{'equipment':set(),'total':0,'completed':0})
    for r in current:
        pid=str(r.get('project_id','')); name=str(r.get('asset_name','')); level=str(r.get('commissioning_level',''))
        etype=type_map.get((pid,name),'') or 'Unknown'
        k=(pid,etype,level)
        grouped[k]['equipment'].add(str(r.get('asset_key') or name))
        grouped[k]['total']+=n(r.get('total_lines'))
        grouped[k]['completed']+=n(r.get('completed_lines'))

    today=[]
    for (pid,etype,level),b in sorted(grouped.items()):
        today.append({'snapshot_date':snapshot,'week_start':week_start,'project_id':pid,'equipment_type':etype,'commissioning_level':level,'equipment_count':len(b['equipment']),'total_lines':b['total'],'completed_lines':b['completed'],'open_lines':b['total']-b['completed'],'completion_pct':pct(b['completed'],b['total']),'last_synced':last_synced})

    existing=read_csv(DAILY_TYPE_PATH)
    existing=[r for r in existing if r.get('snapshot_date')!=snapshot]
    type_history=existing+today
    type_history.sort(key=lambda r:(r.get('snapshot_date',''),r.get('project_id',''),r.get('equipment_type',''),r.get('commissioning_level','')))
    write_csv(DAILY_TYPE_PATH,TYPE_FIELDS,type_history)
    print(f'Wrote {len(type_history)} daily equipment-type history rows')

    changes=read_csv(EQUIPMENT_CHANGES_PATH)
    prior=[r for r in changes if r.get('snapshot_date')!=snapshot]
    latest={}
    for r in prior:
        key=(r.get('project_id',''),r.get('asset_key','') or r.get('asset_name',''),r.get('commissioning_level',''))
        if key not in latest or r.get('snapshot_date','')>latest[key].get('snapshot_date',''):
            latest[key]=r

    new_changes=[]
    for r in current:
        key=(str(r.get('project_id','')),str(r.get('asset_key') or r.get('asset_name','')),str(r.get('commissioning_level','')))
        total=n(r.get('total_lines')); completed=n(r.get('completed_lines'))
        prev=latest.get(key)
        if prev and n(prev.get('total_lines'))==total and n(prev.get('completed_lines'))==completed:
            continue
        new_changes.append({'snapshot_date':snapshot,'week_start':week_start,'project_id':key[0],'asset_key':key[1],'asset_name':r.get('asset_name',''),'commissioning_level':key[2],'total_lines':total,'completed_lines':completed,'completion_pct':pct(completed,total)})

    change_history=prior+new_changes
    change_history.sort(key=lambda r:(r.get('snapshot_date',''),r.get('project_id',''),r.get('asset_key',''),r.get('commissioning_level','')))
    write_csv(EQUIPMENT_CHANGES_PATH,CHANGE_FIELDS,change_history)
    print(f'Added {len(new_changes)} equipment change points; {len(change_history)} total rows')

if __name__=='__main__': main()
