from pathlib import Path

path = Path('index.html')
html = path.read_text(encoding='utf-8')

marker = '/* UNIVERSAL DASHBOARD TABLE TOOLS V1 */'
if marker in html:
    print('Universal table tools already applied')
    raise SystemExit(0)

css_anchor = '/* Charts */'
css = r'''
/* UNIVERSAL DASHBOARD TABLE TOOLS V1 */
.dash-table-tools{display:flex;gap:7px;align-items:center;justify-content:flex-end;margin:0 0 7px;flex-wrap:wrap}
.dash-table-tools input{min-width:220px;font-size:11px;padding:4px 7px}
.dash-table-tools .dash-table-count{font-size:10.5px;color:var(--muted);margin-right:auto}
.dash-col-filter input{width:100%;min-width:84px;font-size:10px;padding:3px 5px;text-transform:none;letter-spacing:0}
.dash-sortable{cursor:pointer !important}
.dash-sortable:after{content:' ↕';color:var(--muted);font-weight:400}
.dash-sortable.dash-asc:after{content:' ▲';color:var(--accent)}
.dash-sortable.dash-desc:after{content:' ▼';color:var(--accent)}
'''
if css_anchor in html:
    html = html.replace(css_anchor, css + '\n' + css_anchor, 1)
else:
    raise SystemExit('CSS anchor not found')

js_anchor = '/* ============================================================== 11. WIRE-UP */'
js = r'''
/* UNIVERSAL DASHBOARD TABLE TOOLS V1 */
const dashTableIds=['trancheTbl','matrixTbl','vendorTbl','aheadTbl','detailTbl','clHeatmap'];
const dashTableState={};
function dashState(id){return dashTableState[id]||(dashTableState[id]={q:'',filters:[],sort:null,dir:1});}
function dashCellText(cell){return (cell?.innerText||cell?.textContent||'').replace(/\s+/g,' ').trim();}
function dashParsed(v){
  const s=String(v||'').trim();
  const num=Number(s.replace(/[%,$]/g,'').replace(/,/g,''));
  if(s!==''&&Number.isFinite(num))return {type:'num',v:num};
  const d=Date.parse(s);if(/^\d{1,4}[\/-]\d{1,2}[\/-]\d{1,4}/.test(s)&&Number.isFinite(d))return {type:'date',v:d};
  return {type:'text',v:s.toLowerCase()};
}
function dashMatchesValue(text,expr){
  expr=String(expr||'').trim();if(!expr)return true;
  const m=expr.match(/^\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*%?\s*$/);
  if(m){const p=dashParsed(text);if(p.type!=='num')return false;const x=Number(m[2]);return m[1]==='>='?p.v>=x:m[1]==='<='?p.v<=x:m[1]==='>'?p.v>x:m[1]==='<'?p.v<x:p.v===x;}
  return String(text||'').toLowerCase().includes(expr.toLowerCase());
}
function dashApplyTable(id){
  const tbl=document.getElementById(id);if(!tbl||!tbl.tBodies.length)return;
  const st=dashState(id),rows=[...tbl.tBodies[0].rows];let shown=0;
  rows.forEach(row=>{
    const cells=[...row.cells],all=cells.map(dashCellText).join(' ').toLowerCase();
    const qok=!st.q||all.includes(st.q.toLowerCase());
    const fok=st.filters.every((f,i)=>!f||dashMatchesValue(dashCellText(cells[i]),f));
    const ok=qok&&fok;row.style.display=ok?'':'none';if(ok)shown++;
  });
  const count=document.querySelector('[data-dash-count="'+id+'"]');if(count)count.textContent=shown+' / '+rows.length+' rows';
}
function dashSortTable(id,col){
  const tbl=document.getElementById(id);if(!tbl||!tbl.tBodies.length)return;
  const st=dashState(id);st.dir=st.sort===col?-st.dir:1;st.sort=col;
  const body=tbl.tBodies[0],rows=[...body.rows];
  rows.sort((a,b)=>{const av=dashParsed(dashCellText(a.cells[col])),bv=dashParsed(dashCellText(b.cells[col]));let d;if(av.type===bv.type)d=av.v<bv.v?-1:av.v>bv.v?1:0;else d=String(av.v).localeCompare(String(bv.v),undefined,{numeric:true});return d*st.dir;});
  rows.forEach(r=>body.appendChild(r));
  tbl.querySelectorAll('thead tr:first-child th').forEach((th,i)=>{th.classList.toggle('dash-asc',i===col&&st.dir>0);th.classList.toggle('dash-desc',i===col&&st.dir<0);});
  dashApplyTable(id);
}
function dashEnhanceTable(id){
  const tbl=document.getElementById(id);if(!tbl||!tbl.tHead||!tbl.tBodies.length)return;
  const st=dashState(id),headRow=tbl.tHead.rows[0];if(!headRow)return;
  let tools=document.querySelector('[data-dash-tools="'+id+'"]');
  if(!tools){
    tools=document.createElement('div');tools.className='dash-table-tools';tools.dataset.dashTools=id;
    tools.innerHTML='<span class="dash-table-count" data-dash-count="'+id+'"></span><input type="search" placeholder="Search this table…" aria-label="Search '+id+'"><button type="button" class="sm">Clear</button>';
    const scroll=tbl.closest('.tbl-scroll');(scroll?.parentNode||tbl.parentNode).insertBefore(tools,scroll||tbl);
    const inp=tools.querySelector('input');inp.value=st.q;inp.oninput=()=>{st.q=inp.value;dashApplyTable(id);};
    tools.querySelector('button').onclick=()=>{st.q='';st.filters=[];inp.value='';const fr=tbl.tHead.querySelector('.dash-col-filter');if(fr)fr.querySelectorAll('input').forEach(x=>x.value='');dashApplyTable(id);};
  }
  let fr=tbl.tHead.querySelector('.dash-col-filter');
  if(!fr||fr.cells.length!==headRow.cells.length){
    if(fr)fr.remove();fr=document.createElement('tr');fr.className='dash-col-filter';
    [...headRow.cells].forEach((th,i)=>{const c=document.createElement('th');c.className='nosort';c.innerHTML='<input type="text" placeholder="Filter" aria-label="Filter '+dashCellText(th)+'">';const inp=c.firstChild;inp.value=st.filters[i]||'';inp.oninput=()=>{st.filters[i]=inp.value;dashApplyTable(id);};inp.onclick=e=>e.stopPropagation();fr.appendChild(c);});
    tbl.tHead.appendChild(fr);
  }
  [...headRow.cells].forEach((th,i)=>{
    const nativeSort=th.hasAttribute('data-sort')||th.hasAttribute('data-clsort');
    if(!nativeSort&&!th.dataset.dashSortBound){th.dataset.dashSortBound='1';th.classList.add('dash-sortable');th.addEventListener('click',e=>{if(e.target.closest('input,button,select'))return;dashSortTable(id,i);});}
  });
  dashApplyTable(id);
}
let dashEnhanceTimer=null;
function dashEnhanceAll(){dashTableIds.forEach(dashEnhanceTable);}
const dashObserver=new MutationObserver(()=>{clearTimeout(dashEnhanceTimer);dashEnhanceTimer=setTimeout(dashEnhanceAll,30);});
document.addEventListener('DOMContentLoaded',()=>{dashEnhanceAll();dashObserver.observe(document.body,{subtree:true,childList:true});});
'''
if js_anchor in html:
    html = html.replace(js_anchor, js + '\n\n' + js_anchor, 1)
else:
    raise SystemExit('JS anchor not found')

path.write_text(html, encoding='utf-8')
print('Universal table search/filter/sort layer applied')
# trigger: 2026-09-17
