"""Build the hosted KUL21 dashboard with checklist completion analytics."""
from pathlib import Path
import requests

SOURCE_HTML = "https://raw.githubusercontent.com/sapoetra/cxalloy-kul21-dashboard/main/index.html"
SHARED_PROJECTED = "https://raw.githubusercontent.com/sapoetra/cxalloy-kul21-dashboard/main/projected_dates.xlsx"
OUT_HTML = Path("index.html")

NAV_ANCHOR = '    <button type="button" data-page="equipment">6. Equipment Register</button>'
TAIL_ANCHOR = '  </details>\n  </section>\n</div>\n\n  </section>\n\n</div>\n<script>'
SCRIPT_ANCHOR = '/* ============================================================== 11. WIRE-UP */'
BOOT_ANCHOR = "document.addEventListener('DOMContentLoaded', ()=>{\n  wire();\n  loadHostedData();\n});"

CHECKLIST_PAGE = r'''

  <!-- PAGE 7 · CHECKLIST COMPLETION -->
  <section class="page" id="page-checklists">
    <div class="sect-title">Checklist completion</div>

    <div class="filterbar" style="position:static;top:auto">
      <div class="filter-row">
        <label class="fld">ELI search<input type="text" id="clQ" placeholder="EDCKUL21…" style="width:160px"></label>
        <label class="fld">Cx Level<select id="clLevel"><option value="ALL">All</option><option value="L1">L1</option><option value="L2">L2</option><option value="L3">L3</option><option value="L4">L4</option><option value="L5">L5</option></select></label>
        <label class="fld">Equipment Type<select id="clType"><option value="ALL">All</option></select></label>
        <label class="fld">Tranche<select id="clTranche"><option value="ALL">All</option></select></label>
        <label class="fld">Discipline<select id="clDiscipline"><option value="ALL">All</option></select></label>
        <label class="fld">System<select id="clSystem"><option value="ALL">All</option></select></label>
        <label class="fld">Equipment Supplier<select id="clSupplier"><option value="ALL">All</option></select></label>
        <button type="button" id="clReset">Reset</button>
      </div>
    </div>

    <div class="kpis" id="clKpis"></div>

    <div class="grid">
      <div class="card c12">
        <div class="card-head">
          <div><h3>Checklist completion gap by equipment type</h3><div class="sub">Completed vs remaining to 100% · follows the Cx Level filter</div></div>
        </div>
        <div class="chart-box" id="clTypeChartBox"><canvas id="checklistByType"></canvas></div>
      </div>

      <div class="card c12">
        <div class="card-head">
          <div><h3>Checklist completion trend</h3><div class="sub">Daily snapshots retained by GitHub · trend starts from the first snapshot date</div></div>
          <div class="toolbar">
            <select id="clTrendMode"><option value="daily">Daily</option><option value="weekly">Weekly</option></select>
            <select id="clTrendLevel"><option value="Overall">Overall</option><option value="L1">L1</option><option value="L2">L2</option><option value="L3">L3</option><option value="L4">L4</option><option value="L5">L5</option></select>
          </div>
        </div>
        <div class="chart-box sm"><canvas id="checklistTrend"></canvas></div>
      </div>

      <div class="card c12">
        <div class="card-head">
          <div><h3>Completion by equipment</h3><div class="sub" id="clTableMeta">Current snapshot</div></div>
          <div class="toolbar">
            <button class="sm" type="button" id="clPrev">‹ Prev</button>
            <span id="clPageInfo" style="font-size:11.5px;color:var(--muted)"></span>
            <button class="sm" type="button" id="clNext">Next ›</button>
          </div>
        </div>
        <div class="tbl-scroll" style="max-height:640px"><table id="clTable"></table></div>
      </div>
    </div>
  </section>
'''

CHECKLIST_JS = r'''
/* ===================================================== CHECKLIST COMPLETION */
const CHECKLIST_DATA={currentUrl:'./data/checklist_completion_by_equipment.csv',dailyUrl:'./data/checklist_progress_daily.csv'};
const checklistState={current:[],daily:[],filtered:[],page:0,pageSize:100,q:'',level:'ALL',type:'ALL',tranche:'ALL',discipline:'ALL',system:'ALL',supplier:'ALL',trendMode:'daily',trendLevel:'Overall'};

function clNum(v){const n=Number(v);return Number.isFinite(n)?n:0;}
function clPctCell(v){
  if(v===null||v===undefined||String(v).trim()==='')return '<span style="color:var(--muted)">—</span>';
  const n=Number(v);if(!Number.isFinite(n))return '—';
  const bg=n<40?'var(--heat-red)':n<=75?'var(--heat-amber)':'var(--heat-green)';
  return '<span style="display:inline-block;min-width:58px;text-align:right;padding:2px 6px;border-radius:5px;background:'+bg+'">'+n.toFixed(1)+'%</span>';
}
function clUnique(k){return uniqSorted(checklistState.current.map(r=>txtValue(r[k])).filter(Boolean));}
function clFill(id,vals){const e=document.getElementById(id);e.innerHTML='<option value="ALL">All</option>'+vals.map(v=>'<option value="'+esc(v)+'">'+esc(v)+'</option>').join('');}
function clBuildFilters(){clFill('clType',clUnique('equipment_type'));clFill('clTranche',clUnique('tranche'));clFill('clDiscipline',clUnique('discipline'));clFill('clSystem',clUnique('systems'));clFill('clSupplier',clUnique('equipment_supplier'));}
function clHasLevel(r,k){return clNum(r[k+'_total_lines'])>0;}
function clApplyFilters(){
  const s=checklistState,q=s.q.trim().toUpperCase();
  s.filtered=s.current.filter(r=>{
    if(q&&!txtValue(r.asset_name).toUpperCase().includes(q))return false;
    if(s.level!=='ALL'&&!clHasLevel(r,s.level))return false;
    if(s.type!=='ALL'&&txtValue(r.equipment_type)!==s.type)return false;
    if(s.tranche!=='ALL'&&txtValue(r.tranche)!==s.tranche)return false;
    if(s.discipline!=='ALL'&&txtValue(r.discipline)!==s.discipline)return false;
    if(s.system!=='ALL'&&txtValue(r.systems)!==s.system)return false;
    if(s.supplier!=='ALL'&&txtValue(r.equipment_supplier)!==s.supplier)return false;
    return true;
  });s.page=0;
}
function clLevelStats(rows,level){
  const tp=level==='Overall'?'overall_total_lines':level+'_total_lines',cp=level==='Overall'?'overall_completed_lines':level+'_completed_lines';
  let total=0,completed=0,eq=0;rows.forEach(r=>{const t=clNum(r[tp]),c=clNum(r[cp]);if(t>0)eq++;total+=t;completed+=c;});
  return {total,completed,eq,p:total?completed/total*100:0};
}
function clRenderKPIs(){
  const levels=checklistState.level==='ALL'?['Overall','L1','L2','L3','L4','L5']:[checklistState.level];
  document.getElementById('clKpis').innerHTML=levels.map(level=>{const x=clLevelStats(checklistState.filtered,level);const label=level==='Overall'?'Overall checklist completion':level+' checklist completion';const l=LEVELS.find(z=>z.k===level);const color=level==='Overall'?'var(--accent)':'var('+(l?l.varc:'--accent')+')';return '<div class="kpi" style="cursor:default"><div class="k-label">'+label+'</div><div class="k-val">'+x.p.toFixed(1)+'<small>%</small></div><div class="bar"><i style="width:'+Math.min(100,x.p).toFixed(1)+'%;background:'+color+'"></i></div><div class="k-sub">'+fmtInt(x.completed)+' / '+fmtInt(x.total)+' lines · '+fmtInt(x.eq)+' equipment</div></div>';}).join('');
}
function clRenderTypeChart(){
  const types=clUniqueFromRows(checklistState.filtered,'equipment_type');
  const level=checklistState.level==='ALL'?'Overall':checklistState.level;
  const completed=types.map(t=>{const rs=checklistState.filtered.filter(r=>txtValue(r.equipment_type)===t);return +clLevelStats(rs,level).p.toFixed(1);});
  const remaining=completed.map(v=>+(100-v).toFixed(1));
  const box=document.getElementById('clTypeChartBox');box.style.height=Math.max(330,types.length*28+90)+'px';
  upsert('checklistByType',{
    type:'bar',
    data:{labels:types,datasets:[
      {label:'Completed',data:completed,backgroundColor:cssVar('--accent'),stack:'progress'},
      {label:'Remaining to 100%',data:remaining,backgroundColor:cssVar('--line'),stack:'progress'}
    ]},
    options:{indexAxis:'y',plugins:{legend:{position:'bottom'},tooltip:{callbacks:{label:c=>c.dataset.label+': '+c.parsed.x.toFixed(1)+'%'}}},scales:{x:{stacked:true,beginAtZero:true,max:100,grid:{color:gridColor()},ticks:{callback:v=>v+'%'},title:{display:true,text:level+' checklist completion'}},y:{stacked:true,grid:{display:false},ticks:{autoSkip:false}}}}
  });
}
function clUniqueFromRows(rows,k){return uniqSorted(rows.map(r=>txtValue(r[k])).filter(Boolean));}
function clFilteredDaily(){const ids=new Set(checklistState.filtered.map(r=>txtValue(r.project_id)));return checklistState.daily.filter(r=>ids.has(txtValue(r.project_id))&&txtValue(r.commissioning_level)===checklistState.trendLevel);}
function clTrendPoints(){
  const by=new Map();clFilteredDaily().forEach(r=>{const d=txtValue(r.snapshot_date);if(!d)return;if(!by.has(d))by.set(d,{completed:0,total:0,week:txtValue(r.week_start)});const x=by.get(d);x.completed+=clNum(r.completed_lines);x.total+=clNum(r.total_lines);});
  let pts=[...by.entries()].map(([date,x])=>({date,week:x.week,p:x.total?x.completed/x.total*100:0})).sort((a,b)=>a.date.localeCompare(b.date));
  if(checklistState.trendMode==='weekly'){const w=new Map();pts.forEach(p=>w.set(p.week,p));pts=[...w.values()].sort((a,b)=>a.date.localeCompare(b.date));}return pts;
}
function clRenderTrend(){const pts=clTrendPoints();upsert('checklistTrend',{type:'line',data:{labels:pts.map(p=>p.date),datasets:[{label:checklistState.trendLevel+' completion %',data:pts.map(p=>+p.p.toFixed(2)),borderColor:cssVar('--accent'),backgroundColor:'rgba(45,127,249,.10)',borderWidth:2.5,pointRadius:3,tension:.25,fill:true}]},options:{plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>c.parsed.y.toFixed(2)+'%'}}},scales:{x:{grid:{display:false}},y:{beginAtZero:true,max:100,grid:{color:gridColor()},ticks:{callback:v=>v+'%'},title:{display:true,text:'Checklist completion'}}}}});}
function clRenderTable(){
  const s=checklistState,rows=s.filtered.slice().sort((a,b)=>txtValue(a.asset_name).localeCompare(txtValue(b.asset_name),undefined,{numeric:true}));const pages=Math.max(1,Math.ceil(rows.length/s.pageSize));if(s.page>=pages)s.page=pages-1;const slice=rows.slice(s.page*s.pageSize,(s.page+1)*s.pageSize);
  let h='<thead><tr><th>ELI</th><th>Equipment Type</th><th>Tranche</th><th>Discipline</th><th>System</th><th>Equipment Supplier</th><th class="num">L1</th><th class="num">L2</th><th class="num">L3</th><th class="num">L4</th><th class="num">L5</th><th class="num">Overall</th></tr></thead><tbody>';
  if(!slice.length)h+='<tr><td colspan="12" class="empty">No equipment matches the current checklist filters.</td></tr>';
  slice.forEach(r=>{h+='<tr><td><b>'+esc(r.asset_name)+'</b></td><td>'+esc(r.equipment_type)+'</td><td>'+esc(r.tranche)+'</td><td>'+esc(r.discipline)+'</td><td>'+esc(r.systems)+'</td><td>'+esc(r.equipment_supplier)+'</td>'+['L1','L2','L3','L4','L5'].map(k=>'<td class="num">'+clPctCell(r[k+'_completion_pct'])+'</td>').join('')+'<td class="num"><b>'+clPctCell(r.overall_completion_pct)+'</b></td></tr>';});
  document.getElementById('clTable').innerHTML=h+'</tbody>';document.getElementById('clTableMeta').textContent=fmtInt(rows.length)+' equipment in scope · snapshot '+(slice[0]?.snapshot_date||'—');document.getElementById('clPageInfo').textContent='Page '+(s.page+1)+' of '+pages;document.getElementById('clPrev').disabled=s.page<=0;document.getElementById('clNext').disabled=s.page>=pages-1;
}
function clRefresh(){clApplyFilters();clRenderKPIs();clRenderTypeChart();clRenderTrend();clRenderTable();}
async function loadChecklistData(){
  try{const [a,b]=await Promise.all([fetch(CHECKLIST_DATA.currentUrl,{cache:'no-store'}),fetch(CHECKLIST_DATA.dailyUrl,{cache:'no-store'})]);if(!a.ok)throw new Error('Checklist snapshot HTTP '+a.status);if(!b.ok)throw new Error('Checklist trend HTTP '+b.status);const parse=t=>new Promise((resolve,reject)=>Papa.parse(t,{header:true,skipEmptyLines:'greedy',complete:r=>resolve(r.data),error:reject}));checklistState.current=await parse(await a.text());checklistState.daily=await parse(await b.text());clBuildFilters();clRefresh();}catch(err){console.error(err);document.getElementById('clTable').innerHTML='<tbody><tr><td class="empty">Checklist data failed to load: '+esc(err.message||err)+'</td></tr></tbody>';}
}
function wireChecklistPage(){
  document.getElementById('clQ').oninput=debounce(e=>{checklistState.q=e.target.value;clRefresh();},250);
  [['clLevel','level'],['clType','type'],['clTranche','tranche'],['clDiscipline','discipline'],['clSystem','system'],['clSupplier','supplier']].forEach(([id,k])=>document.getElementById(id).onchange=e=>{checklistState[k]=e.target.value;if(k==='level'){checklistState.trendLevel=e.target.value==='ALL'?'Overall':e.target.value;document.getElementById('clTrendLevel').value=checklistState.trendLevel;}clRefresh();});
  document.getElementById('clTrendMode').onchange=e=>{checklistState.trendMode=e.target.value;clRenderTrend();};document.getElementById('clTrendLevel').onchange=e=>{checklistState.trendLevel=e.target.value;clRenderTrend();};
  document.getElementById('clPrev').onclick=()=>{if(checklistState.page>0){checklistState.page--;clRenderTable();}};document.getElementById('clNext').onclick=()=>{checklistState.page++;clRenderTable();};
  document.getElementById('clReset').onclick=()=>{Object.assign(checklistState,{q:'',level:'ALL',type:'ALL',tranche:'ALL',discipline:'ALL',system:'ALL',supplier:'ALL',trendLevel:'Overall'});document.getElementById('clQ').value='';['clLevel','clType','clTranche','clDiscipline','clSystem','clSupplier'].forEach(id=>document.getElementById(id).value='ALL');document.getElementById('clTrendLevel').value='Overall';clRefresh();};
}
'''

def download(url):
    r=requests.get(url,timeout=60);r.raise_for_status();return r.text

def build():
    html=download(SOURCE_HTML)
    html=html.replace("equipmentUrl: './equipment_status.csv'","equipmentUrl: './data/equipment_status.csv'")
    html=html.replace("projectedUrl: './projected_dates.xlsx'",f"projectedUrl: '{SHARED_PROJECTED}'")
    if NAV_ANCHOR not in html: raise RuntimeError('Navigation anchor not found')
    html=html.replace(NAV_ANCHOR,NAV_ANCHOR+'\n    <button type="button" data-page="checklists">7. Checklist Completion</button>',1)
    if TAIL_ANCHOR not in html: raise RuntimeError('Dashboard tail anchor not found')
    html=html.replace(TAIL_ANCHOR,'  </details>\n  </section>\n'+CHECKLIST_PAGE+'\n</div>\n\n  </section>\n\n</div>\n<script>',1)
    if SCRIPT_ANCHOR not in html: raise RuntimeError('Script anchor not found')
    html=html.replace(SCRIPT_ANCHOR,CHECKLIST_JS+'\n\n'+SCRIPT_ANCHOR,1)
    if BOOT_ANCHOR not in html: raise RuntimeError('Boot anchor not found')
    html=html.replace(BOOT_ANCHOR,"document.addEventListener('DOMContentLoaded', ()=>{\n  wire();\n  wireChecklistPage();\n  loadHostedData();\n  loadChecklistData();\n});",1)
    OUT_HTML.write_text(html,encoding='utf-8');Path('.nojekyll').write_text('',encoding='utf-8')
    print(f'Built {OUT_HTML} ({OUT_HTML.stat().st_size:,} bytes)')

if __name__=='__main__':build()
