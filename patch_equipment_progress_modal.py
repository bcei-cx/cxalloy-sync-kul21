from pathlib import Path

path = Path('index.html')
html = path.read_text(encoding='utf-8')

MARKER = '/* EQUIPMENT PROGRESS MODAL V1 */'
if MARKER in html:
    print('Equipment progress modal already applied')
    raise SystemExit(0)

css_anchor = '/* Misc */'
if css_anchor not in html:
    raise SystemExit('CSS anchor not found')

css = r'''
/* EQUIPMENT PROGRESS MODAL V1 */
.cl-eli-link{border:0;background:transparent;padding:0;color:var(--accent);font-weight:650;cursor:pointer;text-align:left}
.cl-eli-link:hover{text-decoration:underline;color:var(--accent)}
.cl-progress-cell{min-width:128px;text-align:right}
.cl-progress-current{font-size:12.5px;font-weight:700;color:var(--ink)}
.cl-progress-prior{font-size:10.5px;color:var(--muted);margin-top:2px;white-space:nowrap}
.cl-progress-delta.up{color:var(--st-hit);font-weight:650}
.cl-progress-delta.down{color:var(--st-overdue);font-weight:650}
.cl-progress-delta.flat{color:var(--muted);font-weight:600}
.cl-modal-backdrop{display:none;position:fixed;inset:0;z-index:1000;background:rgba(15,23,42,.48);backdrop-filter:blur(2px);padding:28px;align-items:center;justify-content:center}
.cl-modal-backdrop.open{display:flex}
.cl-modal{width:min(1050px,96vw);max-height:90vh;overflow:auto;background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 24px 70px rgba(0,0,0,.28);padding:18px}
.cl-modal-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:12px}
.cl-modal-head h3{margin:0;font-size:16px}
.cl-modal-meta{color:var(--muted);font-size:11.5px;margin-top:4px}
.cl-modal-close{font-size:18px;line-height:1;padding:4px 9px}
.cl-modal-kpis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0 14px}
.cl-modal-kpi{border:1px solid var(--line);border-radius:10px;padding:10px 12px;background:var(--bg)}
.cl-modal-kpi .lvl{font-size:10.5px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted)}
.cl-modal-kpi .val{font-size:20px;font-weight:700;margin-top:2px}
.cl-modal-kpi .sub{font-size:10.5px;color:var(--muted);margin-top:3px}
@media(max-width:760px){.cl-modal-backdrop{padding:10px}.cl-modal-kpis{grid-template-columns:1fr}.cl-progress-cell{min-width:112px}}
'''
html = html.replace(css_anchor, css + '\n' + css_anchor, 1)

start = html.find('function clRenderTable(){')
end = html.find('\n\nasync function loadChecklistData(){', start)
if start < 0 or end < 0:
    raise SystemExit('Checklist table/history block not found')

replacement = r'''function clEquipmentWeekPct(r,level){
  const wk=clWeekInfo().previous;if(!wk)return null;
  const key=clEqKey(r);
  const hit=(checklistState.history||[]).find(x=>txtValue(x.week_start)===wk&&txtValue(x.commissioning_level)===level&&clEqKey(x)===key);
  if(!hit)return null;
  const total=clNum(hit.total_lines),completed=clNum(hit.completed_lines);
  return total?completed/total*100:null;
}
function clProgressCompareCell(r,level){
  const raw=r[level+'_completion_pct'];
  if(raw===null||raw===undefined||String(raw).trim()==='')return '<td class="num cl-progress-cell"><span style="color:var(--muted)">—</span></td>';
  const cur=Number(raw);if(!Number.isFinite(cur))return '<td class="num cl-progress-cell">—</td>';
  const prior=clEquipmentWeekPct(r,level);
  let priorText='Last week —';
  if(prior!==null){
    const delta=+(cur-prior).toFixed(1),cls=delta>0?'up':delta<0?'down':'flat',arrow=delta>0?'▲':delta<0?'▼':'—';
    priorText='Last week '+prior.toFixed(1)+'% · <span class="cl-progress-delta '+cls+'">'+arrow+' '+(delta>0?'+':'')+delta.toFixed(1)+'pp</span>';
  }
  return '<td class="num cl-progress-cell"><div class="cl-progress-current">'+cur.toFixed(1)+'%</div><div class="cl-progress-prior">'+priorText+'</div></td>';
}
function clRenderTable(){
  const s=checklistState,rows=s.filtered.slice().sort((a,b)=>txtValue(a.asset_name).localeCompare(txtValue(b.asset_name),undefined,{numeric:true}));
  const pages=Math.max(1,Math.ceil(rows.length/s.pageSize));if(s.page>=pages)s.page=pages-1;const slice=rows.slice(s.page*s.pageSize,(s.page+1)*s.pageSize);
  let h='<thead><tr><th>ELI</th><th>Equipment Type</th><th>Tranche</th><th>Discipline</th><th>System</th><th>Equipment Supplier</th><th class="num">L1<div style="font-size:9px;font-weight:400;text-transform:none">Current · last week · Δ</div></th><th class="num">L2<div style="font-size:9px;font-weight:400;text-transform:none">Current · last week · Δ</div></th><th class="num">L3<div style="font-size:9px;font-weight:400;text-transform:none">Current · last week · Δ</div></th><th class="num">L4</th><th class="num">L5</th><th class="num">Overall</th></tr></thead><tbody>';
  if(!slice.length)h+='<tr><td colspan="12" class="empty">No equipment matches the current checklist filters.</td></tr>';
  slice.forEach((r,i)=>{
    h+='<tr><td><button type="button" class="cl-eli-link cl-eq-history" data-row="'+i+'">'+esc(r.asset_name)+'</button></td><td>'+esc(r.equipment_type)+'</td><td>'+esc(r.tranche)+'</td><td>'+esc(r.discipline)+'</td><td>'+esc(r.systems)+'</td><td>'+esc(r.equipment_supplier)+'</td>'+clProgressCompareCell(r,'L1')+clProgressCompareCell(r,'L2')+clProgressCompareCell(r,'L3')+'<td class="num">'+clPctCell(r.L4_completion_pct)+'</td><td class="num">'+clPctCell(r.L5_completion_pct)+'</td><td class="num"><b>'+clPctCell(r.overall_completion_pct)+'</b></td></tr>';
  });
  document.getElementById('clTable').innerHTML=h+'</tbody>';
  const wk=clWeekInfo();
  document.getElementById('clTableMeta').textContent=fmtInt(rows.length)+' equipment in scope · L1–L3 compare current vs last completed week'+(wk.previous?' ('+wk.previous+')':'')+' · click an ELI for daily history';
  document.getElementById('clPageInfo').textContent='Page '+(s.page+1)+' of '+pages;document.getElementById('clPrev').disabled=s.page<=0;document.getElementById('clNext').disabled=s.page>=pages-1;
  document.querySelectorAll('.cl-eq-history').forEach(btn=>btn.onclick=()=>clShowEquipmentHistory(slice[Number(btn.dataset.row)]));
}
function clEnsureEquipmentHistoryModal(){
  let wrap=document.getElementById('clEqHistoryModal');if(wrap)return wrap;
  document.body.insertAdjacentHTML('beforeend','<div class="cl-modal-backdrop" id="clEqHistoryModal" role="dialog" aria-modal="true" aria-labelledby="clEqHistoryTitle"><div class="cl-modal"><div class="cl-modal-head"><div><h3 id="clEqHistoryTitle">Equipment checklist progress history</h3><div class="cl-modal-meta" id="clEqHistoryMeta"></div></div><button type="button" class="cl-modal-close" id="clEqHistoryClose" aria-label="Close">×</button></div><div class="cl-modal-kpis" id="clEqHistoryKpis"></div><div class="chart-box" style="height:360px"><canvas id="checklistEqHistory"></canvas></div><div class="cl-modal-meta" id="clEqHistoryFoot" style="margin-top:8px">Daily change points; unchanged days are carried forward.</div></div></div>');
  wrap=document.getElementById('clEqHistoryModal');
  const close=()=>{wrap.classList.remove('open');document.body.style.overflow='';};
  document.getElementById('clEqHistoryClose').onclick=close;
  wrap.addEventListener('click',e=>{if(e.target===wrap)close();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&wrap.classList.contains('open'))close();});
  return wrap;
}
function clModalLevelKpi(r,level){
  const raw=r[level+'_completion_pct'];
  const cur=(raw===null||raw===undefined||String(raw).trim()===''||!Number.isFinite(Number(raw)))?null:Number(raw);
  const prior=clEquipmentWeekPct(r,level);
  let delta='—',cls='flat';
  if(cur!==null&&prior!==null){const d=+(cur-prior).toFixed(1);delta=(d>0?'+':'')+d.toFixed(1)+'pp';cls=d>0?'up':d<0?'down':'flat';}
  return '<div class="cl-modal-kpi"><div class="lvl">'+level+'</div><div class="val">'+(cur===null?'—':cur.toFixed(1)+'%')+'</div><div class="sub">Last week '+(prior===null?'—':prior.toFixed(1)+'%')+' · <span class="cl-progress-delta '+cls+'">'+delta+'</span></div></div>';
}
function clShowEquipmentHistory(r){
  if(!r)return;const modal=clEnsureEquipmentHistoryModal(),pid=txtValue(r.project_id),key=txtValue(r.asset_key||r.asset_name),wk=clWeekInfo();
  const points=(checklistState.eqChanges||[]).filter(x=>txtValue(x.project_id)===pid&&txtValue(x.asset_key||x.asset_name)===key&&['L1','L2','L3'].includes(txtValue(x.commissioning_level))).sort((a,b)=>txtValue(a.snapshot_date).localeCompare(txtValue(b.snapshot_date)));
  document.getElementById('clEqHistoryTitle').textContent=txtValue(r.asset_name)+' · checklist progress history';
  document.getElementById('clEqHistoryMeta').textContent=[txtValue(r.equipment_type),txtValue(r.tranche),txtValue(r.discipline),txtValue(r.systems),txtValue(r.equipment_supplier)].filter(Boolean).join(' · ');
  document.getElementById('clEqHistoryKpis').innerHTML=['L1','L2','L3'].map(k=>clModalLevelKpi(r,k)).join('');
  document.getElementById('clEqHistoryFoot').textContent='Daily L1–L3 change points · unchanged days carried forward'+(wk.previous?' · last completed week starts '+wk.previous:'');
  const dates=uniqSorted(points.map(x=>txtValue(x.snapshot_date)).filter(Boolean));
  const datasets=['L1','L2','L3'].map(k=>{
    const l=LEVELS.find(x=>x.k===k),by=new Map(points.filter(x=>txtValue(x.commissioning_level)===k).map(x=>[txtValue(x.snapshot_date),clNum(x.completion_pct)]));
    let last=null;const data=dates.map(d=>{if(by.has(d))last=by.get(d);return last;});
    return {label:k,data,borderColor:cssVar(l.varc),backgroundColor:cssVar(l.varc),borderWidth:2.5,pointRadius:3,tension:0,stepped:true,spanGaps:true};
  }).filter(ds=>ds.data.some(v=>v!==null));
  upsert('checklistEqHistory',{type:'line',data:{labels:dates,datasets},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'bottom'},tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.parsed.y==null?'—':c.parsed.y.toFixed(1)+'%')}}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,max:100,grid:{color:gridColor()},ticks:{callback:v=>v+'%'},title:{display:true,text:'Checklist completion'}}}}});
  modal.classList.add('open');document.body.style.overflow='hidden';
}
'''

html = html[:start] + replacement + html[end:]
path.write_text(html, encoding='utf-8')
print('Applied equipment current-vs-last-week cells and modal history dialog')
