from pathlib import Path

path = Path('index.html')
html = path.read_text(encoding='utf-8')

anchor = 'function clEquipmentWeekPct(r,level){'
if anchor not in html:
    raise SystemExit('clEquipmentWeekPct anchor not found')

helpers = r'''
function clWeekInfo(){
  const weeks=uniqSorted((checklistState.history||[]).map(r=>txtValue(r.week_start)).filter(Boolean));
  return {current:weeks.length?weeks[weeks.length-1]:'',previous:weeks.length>1?weeks[weeks.length-2]:''};
}
function clEqKey(r){
  return txtValue(r.project_id)+'|'+txtValue(r.asset_key||r.asset_name);
}
function clLastWeekStats(currentRows,level){
  const wk=clWeekInfo().previous;if(!wk)return null;
  const keys=new Set(currentRows.map(clEqKey));
  let total=0,completed=0;
  (checklistState.history||[]).forEach(r=>{
    if(txtValue(r.week_start)!==wk||txtValue(r.commissioning_level)!==level||!keys.has(clEqKey(r)))return;
    total+=clNum(r.total_lines);completed+=clNum(r.completed_lines);
  });
  return total?{total,completed,p:completed/total*100}:null;
}
'''

missing=[]
if 'function clWeekInfo(){' not in html: missing.append('clWeekInfo')
if 'function clEqKey(r){' not in html: missing.append('clEqKey')
if 'function clLastWeekStats(currentRows,level){' not in html: missing.append('clLastWeekStats')

if not missing:
    print('Weekly helpers already present')
    raise SystemExit(0)

# Insert the complete helper block only once; definitions are guarded above.
insert=''
if 'clWeekInfo' in missing:
    insert += helpers.split('function clEqKey')[0]
if 'clEqKey' in missing:
    insert += 'function clEqKey' + helpers.split('function clEqKey',1)[1].split('function clLastWeekStats',1)[0]
if 'clLastWeekStats' in missing:
    insert += 'function clLastWeekStats' + helpers.split('function clLastWeekStats',1)[1]

html = html.replace(anchor, insert + '\n' + anchor, 1)
path.write_text(html, encoding='utf-8')
print('Restored: ' + ', '.join(missing))
