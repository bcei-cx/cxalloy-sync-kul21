from pathlib import Path

path = Path('index.html')
html = path.read_text(encoding='utf-8')
anchor = '/* ============================================================== 11. WIRE-UP */'
if anchor not in html:
    raise SystemExit('Dashboard wire-up anchor not found')

patch = r'''
/* ================================================= CHECKLIST MULTI-SELECT */
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
function clRenderHeatmap(){
  const rows=checklistState.baseFiltered,types=clUniqueFromRows(rows,'equipment_type'),chosen=clSelectedLevels(),levels=chosen.length?LEVELS.filter(l=>clMulti.levels.has(l.k)):LEVELS;
  let h='<thead><tr><th>Equipment Type</th><th class="num">Equipment</th>'+levels.map(l=>'<th class="num"><span class="tagdot" style="background:var('+l.varc+')"></span>'+l.k+'</th>').join('')+'</tr></thead><tbody>';
  if(!types.length)h+='<tr><td colspan="'+(2+levels.length)+'" class="empty">No equipment types match the current filters.</td></tr>';
  types.forEach(t=>{const rs=rows.filter(r=>txtValue(r.equipment_type)===t);h+='<tr><td><b>'+esc(t)+'</b></td><td class="num">'+fmtInt(rs.length)+'</td>';levels.forEach(l=>{const x=clLevelStats(rs,l.k),p=x.total?+x.p.toFixed(1):null;h+='<td class="num" style="'+clHeatStyle(p)+';font-weight:700">'+(p===null?'—':p.toFixed(1)+'%')+'</td>';});h+='</tr>';});
  document.getElementById('clHeatmap').innerHTML=h+'</tbody>';
}
function clCombinedStats(rows,levels){let total=0,completed=0;levels.forEach(k=>{const x=clLevelStats(rows,k);total+=x.total;completed+=x.completed;});return {total,completed,p:total?completed/total*100:0};}
function clRenderRankChart(){
  const chosen=clSelectedLevels(),label=chosen.length===0?'Overall':chosen.length===1?chosen[0]:chosen.join(' + '),rows=checklistState.filtered;
  const ranked=clUniqueFromRows(rows,'equipment_type').map(t=>{const rs=rows.filter(r=>txtValue(r.equipment_type)===t),x=chosen.length?clCombinedStats(rs,chosen):clLevelStats(rs,'Overall');return {type:t,p:+x.p.toFixed(1),total:x.total};}).filter(x=>x.total>0).sort((a,b)=>b.p-a.p||a.type.localeCompare(b.type));
  const box=document.getElementById('clRankBox');box.style.height=Math.max(300,ranked.length*27+80)+'px';document.getElementById('clRankSub').textContent=label+' completion ranked by equipment type · bar length shows distance to 100%';
  upsert('checklistRank',{type:'bar',data:{labels:ranked.map(x=>x.type),datasets:[{label:label+' completion',data:ranked.map(x=>x.p),backgroundColor:cssVar('--accent')}]},options:{indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.parsed.x.toFixed(1)+'% complete'}}},scales:{x:{beginAtZero:true,max:100,grid:{color:gridColor()},ticks:{callback:v=>v+'%'},title:{display:true,text:'Completion percentage'}},y:{grid:{display:false},ticks:{autoSkip:false}}}}});
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
print('Applied checklist multi-select filters')
