from pathlib import Path

path = Path('index.html')
html = path.read_text(encoding='utf-8')
anchor = '/* ============================================================== 11. WIRE-UP */'
if anchor not in html:
    raise SystemExit('Dashboard wire-up anchor not found')

patch = r'''
/* ============================== CHECKLIST MULTI-SELECT + WEEKLY + DRILLDOWN */
const clMulti={levels:new Set(),types:new Set(),tranches:new Set(),disciplines:new Set(),systems:new Set(),suppliers:new Set()};
const clMultiDefs=[
  {id:'clLevel',key:'levels',label:'Cx Level',field:null,values:['L1','L2','L3','L4','L5']},
  {id:'clType',key:'types',label:'Equipment Type',field:'equipment_type'},
  {id:'clTranche',key:'tranches',label:'Tranche',field:'tranche'},
  {id:'clDiscipline',key:'disciplines',label:'Discipline',field:'discipline'},
  {id:'clSystem',key:'systems',label:'System',field:'systems'},
  {id:'clSupplier',key:'suppliers',label:'Equipment Supplier',field:'equipment_supplier'}
];

function clMSValues(def){return def.values||clUnique(def.field);}
function clMSButton(def){
  const n=clMulti[def.key].size, el=document.querySelector('[data-clms="'+def.key+'"]>button');
  if(el)el.innerHTML=def.label+(n?' <span class="n">'+n+'</span>':'')+' ▾';
}
function clMSBuild(def){
  const sel=document.getElementById(def.id);if(!sel||document.querySelector('[data-clms="'+def.key+'"]'))return;
  sel.style.display='none';
  const ms=document.createElement('div');ms.className='ms';ms.dataset.clms=def.key;
  ms.innerHTML='<button type="button">'+def.label+' ▾</button><div class="ms-panel"><div class="ms-actions"><button type="button" class="sm clms-all">All</button></div><div class="clms-opts"></div></div>';
  sel.insertAdjacentElement('afterend',ms);
  const opts=ms.querySelector('.clms-opts');
  clMSValues(def).forEach(v=>{
    const row=document.createElement('label');row.className='opt';
    row.innerHTML='<input type="checkbox" value="'+esc(v)+'"><span>'+esc(v)+'</span>';
    const cb=row.querySelector('input');
    cb.addEventListener('change',()=>{cb.checked?clMulti[def.key].add(v):clMulti[def.key].delete(v);clMSButton(def);clRefresh();});
    opts.appendChild(row);
  });
  ms.querySelector(':scope>button').addEventListener('click',e=>{e.stopPropagation();document.querySelectorAll('.ms.open').forEach(x=>{if(x!==ms)x.classList.remove('open')});ms.classList.toggle('open');});
  ms.querySelector('.clms-all').addEventListener('click',e=>{e.stopPropagation();clMulti[def.key].clear();opts.querySelectorAll('input').forEach(x=>x.checked=false);clMSButton(def);clRefresh();});
  clMSButton(def);
}
function clBuildFilters(){clMultiDefs.forEach(clMSBuild);}
function clMatch(set,v){return !set.size||set.has(txtValue(v));}
function clSelectedLevels(){return clMulti.levels.size?[...clMulti.levels]:[];}
function clHasAnySelectedLevel(r){const lv=clSelectedLevels();return !lv.length||lv.some(k=>clHasLevel(r,k));}
function clApplyFilters(){
  const s=checklistState,q=s.q.trim().toUpperCase();
  s.baseFiltered=s.current.filter(r=>{
    if(q&&!txtValue(r.asset_name).toUpperCase().includes(q))return false;
    if(!clMatch(clMulti.types,r.equipment_type))return false;
    if(!clMatch(clMulti.tranches,r.tranche))return false;
    if(!clMatch(clMulti.disciplines,r.discipline))return false;
    if(!clMatch(clMulti.systems,r.systems))return false;
    if(!clMatch(clMulti.suppliers,r.equipment_supplier))return false;
    return true;
  });
  s.filtered=s.baseFiltered.filter(clHasAnySelectedLevel);s.page=0;
}
function clRenderKPIs(){
  const chosen=clSelectedLevels(),levels=chosen.length?chosen:['Overall','L1','L2','L3','L4','L5'];
  document.getElementById('clKpis').innerHTML=levels.map(level=>{const x=clLevelStats(checklistState.filtered,level),l=LEVELS.find(z=>z.k===level),label=level==='Overall'?'Overall checklist completion':level+' checklist completion',color=level==='Overall'?'var(--accent)':'var('+(l?l.varc:'--accent')+')';return '<div class="kpi" style="cursor:default"><div class="k-label">'+label+'</div><div class="k-val">'+x.p.toFixed(1)+'<small>%</small></div><div class="bar"><i style="width:'+Math.min(100,x.p).toFixed(1)+'%;background:'+color+'"></i></div><div class="k-sub">'+fmtInt(x.completed)+' / '+fmtInt(x.total)+' lines · '+fmtInt(x.eq)+' equipment</div></div>';}).join('');
}

function clWeekInfo(){
  const weeks=uniqSorted((checklistState.history||[]).map(r=>txtValue(r.week_start)).filter(Boolean));
  return {current:weeks.length?weeks[weeks.length-1]:'',previous:weeks.length>1?weeks[weeks.length-2]:''};
}
function clEqKey(r){return txtValue(r.project_id)+'|'+txtValue(r.asset_key||r.asset_name);}
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
function clRenderHeatmap(){
  const rows=checklistState.baseFiltered,types=clUniqueFromRows(rows,'equipment_type'),chosen=clSelectedLevels(),levels=chosen.length?LEVELS.filter(l=>clMulti.levels.has(l.k)):LEVELS,wk=clWeekInfo();
  const card=document.getElementById('clHeatmap')?.closest('.card');
  const sub=card?.querySelector('.sub');
  if(sub)sub.textContent='Current week-to-date vs last completed week · Sunday 23:55 MYT cutoff'+(wk.previous?' · last week '+wk.previous:'');
  let h='<thead><tr><th>Equipment Type</th><th class="num">Equipment</th>'+levels.map(l=>'<th class="num"><span class="tagdot" style="background:var('+l.varc+')"></span>'+l.k+'</th>').join('')+'</tr></thead><tbody>';
  if(!types.length)h+='<tr><td colspan="'+(2+levels.length)+'" class="empty">No equipment types match the current filters.</td></tr>';
  types.forEach(t=>{
    const rs=rows.filter(r=>txtValue(r.equipment_type)===t);
    h+='<tr><td><b>'+esc(t)+'</b></td><td class="num">'+fmtInt(rs.length)+'</td>';
    levels.forEach(l=>{
      const x=clLevelStats(rs,l.k),p=x.total?+x.p.toFixed(1):null,lw=clLastWeekStats(rs,l.k);
      let cell='—';
      if(p!==null){
        const delta=lw?+(p-lw.p).toFixed(1):null;
        const d=delta===null?'':(' · '+(delta>0?'+':'')+delta.toFixed(1)+'pp');
        cell='<div style="font-size:13px;font-weight:700">'+p.toFixed(1)+'%</div><div style="font-size:10.5px;font-weight:500;opacity:.78;margin-top:2px">'+(lw?'Last week '+lw.p.toFixed(1)+'%'+d:'Last week —')+'</div>';
      }
      h+='<td class="num" style="'+clHeatStyle(p)+';vertical-align:middle">'+cell+'</td>';
    });
    h+='</tr>';
  });
  document.getElementById('clHeatmap').innerHTML=h+'</tbody>';
}
function clCombinedStats(rows,levels){let total=0,completed=0;levels.forEach(k=>{const x=clLevelStats(rows,k);total+=x.total;completed+=x.completed;});return {total,completed,p:total?completed/total*100:0};}
function clRenderRankChart(){
  const chosen=clSelectedLevels(),label=chosen.length===0?'Overall':chosen.length===1?chosen[0]:chosen.join(' + '),rows=checklistState.filtered;
  const ranked=clUniqueFromRows(rows,'equipment_type').map(t=>{const rs=rows.filter(r=>txtValue(r.equipment_type)===t),x=chosen.length?clCombinedStats(rs,chosen):clLevelStats(rs,'Overall');return {type:t,p:+x.p.toFixed(1),total:x.total};}).filter(x=>x.total>0).sort((a,b)=>b.p-a.p||a.type.localeCompare(b.type));
  const box=document.getElementById('clRankBox');box.style.height=Math.max(300,ranked.length*27+80)+'px';document.getElementById('clRankSub').textContent=label+' completion ranked by equipment type · bar length shows distance to 100%';
  upsert('checklistRank',{type:'bar',data:{labels:ranked.map(x=>x.type),datasets:[{label:label+' completion',data:ranked.map(x=>x.p),backgroundColor:cssVar('--accent')}]},options:{indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.parsed.x.toFixed(1)+'% complete'}}},scales:{x:{beginAtZero:true,max:100,grid:{color:gridColor()},ticks:{callback:v=>v+'%'},title:{display:true,text:'Completion percentage'}},y:{grid:{display:false},ticks:{autoSkip:false}}}}});
}

function clRenderTable(){
  const s=checklistState,rows=s.filtered.slice().sort((a,b)=>txtValue(a.asset_name).localeCompare(txtValue(b.asset_name),undefined,{numeric:true}));
  const pages=Math.max(1,Math.ceil(rows.length/s.pageSize));if(s.page>=pages)s.page=pages-1;const slice=rows.slice(s.page*s.pageSize,(s.page+1)*s.pageSize);
  let h='<thead><tr><th>ELI</th><th>Equipment Type</th><th>Tranche</th><th>Discipline</th><th>System</th><th>Equipment Supplier</th><th class="num">L1</th><th class="num">L2</th><th class="num">L3</th><th class="num">L4</th><th class="num">L5</th><th class="num">Overall</th></tr></thead><tbody>';
  if(!slice.length)h+='<tr><td colspan="12" class="empty">No equipment matches the current checklist filters.</td></tr>';
  slice.forEach((r,i)=>{
    h+='<tr><td><button type="button" class="sm cl-eq-history" data-row="'+i+'" style="font-weight:650;padding:2px 6px">'+esc(r.asset_name)+'</button></td><td>'+esc(r.equipment_type)+'</td><td>'+esc(r.tranche)+'</td><td>'+esc(r.discipline)+'</td><td>'+esc(r.systems)+'</td><td>'+esc(r.equipment_supplier)+'</td>'+['L1','L2','L3','L4','L5'].map(k=>'<td class="num">'+clPctCell(r[k+'_completion_pct'])+'</td>').join('')+'<td class="num"><b>'+clPctCell(r.overall_completion_pct)+'</b></td></tr>';
  });
  document.getElementById('clTable').innerHTML=h+'</tbody>';
  document.getElementById('clTableMeta').textContent=fmtInt(rows.length)+' equipment in scope · click an ELI to view progress history';
  document.getElementById('clPageInfo').textContent='Page '+(s.page+1)+' of '+pages;document.getElementById('clPrev').disabled=s.page<=0;document.getElementById('clNext').disabled=s.page>=pages-1;
  document.querySelectorAll('.cl-eq-history').forEach(btn=>btn.onclick=()=>clShowEquipmentHistory(slice[Number(btn.dataset.row)]));
}
function clEnsureEquipmentHistoryCard(){
  let card=document.getElementById('clEqHistoryCard');if(card)return card;
  const tableCard=document.getElementById('clTable').closest('.card');
  tableCard.insertAdjacentHTML('afterend','<div class="card c12" id="clEqHistoryCard" style="display:none"><div class="card-head"><div><h3 id="clEqHistoryTitle">Equipment checklist progress history</h3><div class="sub" id="clEqHistorySub">Daily change points · unchanged days are carried forward</div></div><button type="button" class="sm" id="clEqHistoryClose">Close</button></div><div class="chart-box sm" style="height:300px"><canvas id="checklistEqHistory"></canvas></div></div>');
  card=document.getElementById('clEqHistoryCard');document.getElementById('clEqHistoryClose').onclick=()=>card.style.display='none';return card;
}
function clShowEquipmentHistory(r){
  if(!r)return;const card=clEnsureEquipmentHistoryCard(),pid=txtValue(r.project_id),key=txtValue(r.asset_key||r.asset_name);
  const points=(checklistState.eqChanges||[]).filter(x=>txtValue(x.project_id)===pid&&txtValue(x.asset_key||x.asset_name)===key).sort((a,b)=>txtValue(a.snapshot_date).localeCompare(txtValue(b.snapshot_date)));
  card.style.display='block';document.getElementById('clEqHistoryTitle').textContent=txtValue(r.asset_name)+' · checklist progress history';
  document.getElementById('clEqHistorySub').textContent=txtValue(r.equipment_type)+' · '+txtValue(r.tranche)+' · daily change points; unchanged days carried forward';
  if(!points.length){upsert('checklistEqHistory',{type:'line',data:{labels:[],datasets:[]},options:{scales:{y:{beginAtZero:true,max:100}}}});card.scrollIntoView({behavior:'smooth',block:'center'});return;}
  const dates=uniqSorted(points.map(x=>txtValue(x.snapshot_date)).filter(Boolean));
  const datasets=LEVELS.map(l=>{
    const by=new Map(points.filter(x=>txtValue(x.commissioning_level)===l.k).map(x=>[txtValue(x.snapshot_date),clNum(x.completion_pct)]));
    let last=null;const data=dates.map(d=>{if(by.has(d))last=by.get(d);return last;});
    return {label:l.k,data,borderColor:cssVar(l.varc),backgroundColor:cssVar(l.varc),borderWidth:2,pointRadius:2,tension:0,stepped:true,spanGaps:true};
  }).filter(ds=>ds.data.some(v=>v!==null));
  upsert('checklistEqHistory',{type:'line',data:{labels:dates,datasets},options:{plugins:{tooltip:{callbacks:{label:c=>c.dataset.label+': '+(c.parsed.y==null?'—':c.parsed.y.toFixed(1)+'%')}}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,max:100,grid:{color:gridColor()},ticks:{callback:v=>v+'%'},title:{display:true,text:'Completion percentage'}}}}});
  card.scrollIntoView({behavior:'smooth',block:'center'});
}

async function loadChecklistData(){
  try{
    const [a,b,c,d,e]=await Promise.all([
      fetch('./data/checklist_completion_by_equipment.csv',{cache:'no-store'}),
      fetch('./data/checklist_progress_daily.csv',{cache:'no-store'}),
      fetch('./data/checklist_progress_history.csv',{cache:'no-store'}),
      fetch('./data/checklist_progress_daily_type.csv',{cache:'no-store'}),
      fetch('./data/checklist_progress_equipment_changes.csv',{cache:'no-store'})
    ]);
    if(!a.ok)throw new Error('Checklist snapshot HTTP '+a.status);
    if(!b.ok)throw new Error('Checklist trend HTTP '+b.status);
    if(!c.ok)throw new Error('Checklist weekly history HTTP '+c.status);
    const parse=t=>new Promise((resolve,reject)=>Papa.parse(t,{header:true,skipEmptyLines:'greedy',complete:r=>resolve(r.data),error:reject}));
    checklistState.current=await parse(await a.text());
    checklistState.daily=await parse(await b.text());
    checklistState.history=await parse(await c.text());
    checklistState.dailyType=d.ok?await parse(await d.text()):[];
    checklistState.eqChanges=e.ok?await parse(await e.text()):[];
    clBuildFilters();clRefresh();
  }catch(err){console.error(err);document.getElementById('clTable').innerHTML='<tbody><tr><td class="empty">Checklist data failed to load: '+esc(err.message||err)+'</td></tr></tbody>';}
}
function wireChecklistPage(){
  document.getElementById('clQ').oninput=debounce(e=>{checklistState.q=e.target.value;clRefresh();},250);
  document.getElementById('clTrendMode').onchange=e=>{checklistState.trendMode=e.target.value;clRenderTrend();};
  document.getElementById('clTrendLevel').onchange=e=>{checklistState.trendLevel=e.target.value;clRenderTrend();};
  document.getElementById('clPrev').onclick=()=>{if(checklistState.page>0){checklistState.page--;clRenderTable();}};
  document.getElementById('clNext').onclick=()=>{checklistState.page++;clRenderTable();};
  document.getElementById('clReset').onclick=()=>{checklistState.q='';document.getElementById('clQ').value='';Object.values(clMulti).forEach(s=>s.clear());document.querySelectorAll('[data-clms] input[type="checkbox"]').forEach(x=>x.checked=false);clMultiDefs.forEach(clMSButton);checklistState.trendLevel='Overall';document.getElementById('clTrendLevel').value='Overall';clRefresh();};
  document.addEventListener('click',()=>document.querySelectorAll('.ms.open').forEach(x=>x.classList.remove('open')));
}
'''

html = html.replace(anchor, patch + '\n\n' + anchor, 1)
path.write_text(html, encoding='utf-8')
print('Applied checklist multi-select, weekly comparison and equipment history drilldown')
