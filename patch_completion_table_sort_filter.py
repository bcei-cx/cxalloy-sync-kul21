from pathlib import Path

path = Path('index.html')
html = path.read_text(encoding='utf-8')

start = html.find('function clRenderTable(){')
end = html.find('function clEnsureEquipmentHistoryModal(){', start)
if start < 0 or end < 0:
    raise SystemExit('Completion table block not found')

new_block = r'''function clTableNumericMatch(value,expr){
  expr=String(expr||'').trim();
  if(!expr)return true;
  if(value===null||value===undefined||String(value).trim()==='')return false;
  const n=Number(value);if(!Number.isFinite(n))return false;
  const m=expr.match(/^\s*(>=|<=|>|<|=)?\s*(-?\d+(?:\.\d+)?)\s*%?\s*$/);
  if(!m)return String(n).includes(expr);
  const op=m[1]||'=',x=Number(m[2]);
  if(op==='>=')return n>=x;if(op==='<=')return n<=x;if(op==='>')return n>x;if(op==='<')return n<x;return Math.abs(n-x)<0.0001;
}
function clTableValue(r,k){
  if(['L1','L2','L3','L4','L5'].includes(k))return r[k+'_completion_pct'];
  if(k==='overall')return r.overall_completion_pct;
  return r[k];
}
function clRenderTable(){
  const s=checklistState;
  if(!s.tableSort)s.tableSort={k:'asset_name',dir:1};
  if(!s.tableFilters)s.tableFilters={};
  const cols=[
    {k:'asset_name',t:'ELI',kind:'text',ph:'filter ELI'},
    {k:'equipment_type',t:'Equipment Type',kind:'text',ph:'filter type'},
    {k:'tranche',t:'Tranche',kind:'text',ph:'filter tranche'},
    {k:'discipline',t:'Discipline',kind:'text',ph:'filter discipline'},
    {k:'systems',t:'System',kind:'text',ph:'filter system'},
    {k:'equipment_supplier',t:'Equipment Supplier',kind:'text',ph:'filter supplier'},
    {k:'L1',t:'L1',kind:'num',ph:'e.g. >=50'},
    {k:'L2',t:'L2',kind:'num',ph:'e.g. >=50'},
    {k:'L3',t:'L3',kind:'num',ph:'e.g. >=50'},
    {k:'L4',t:'L4',kind:'num',ph:'e.g. >=50'},
    {k:'L5',t:'L5',kind:'num',ph:'e.g. >=50'},
    {k:'overall',t:'Overall',kind:'num',ph:'e.g. >=50'}
  ];
  const source=s.filtered.slice();
  let rows=source.filter(r=>cols.every(c=>{
    const f=String(s.tableFilters[c.k]||'').trim();if(!f)return true;
    const v=clTableValue(r,c.k);
    return c.kind==='num'?clTableNumericMatch(v,f):txtValue(v).toLowerCase().includes(f.toLowerCase());
  }));
  const sort=s.tableSort,col=cols.find(c=>c.k===sort.k)||cols[0];
  rows.sort((a,b)=>{
    const av=clTableValue(a,col.k),bv=clTableValue(b,col.k);
    if(col.kind==='num'){
      const an=(av===null||av===undefined||String(av).trim()===''||!Number.isFinite(Number(av)))?null:Number(av);
      const bn=(bv===null||bv===undefined||String(bv).trim()===''||!Number.isFinite(Number(bv)))?null:Number(bv);
      if(an===null&&bn===null)return 0;if(an===null)return 1;if(bn===null)return -1;return (an-bn)*sort.dir;
    }
    return txtValue(av).localeCompare(txtValue(bv),undefined,{numeric:true,sensitivity:'base'})*sort.dir;
  });
  const pages=Math.max(1,Math.ceil(rows.length/s.pageSize));if(s.page>=pages)s.page=pages-1;const slice=rows.slice(s.page*s.pageSize,(s.page+1)*s.pageSize);
  const sortMark=k=>sort.k===k?(sort.dir>0?' ▲':' ▼'):'';
  let h='<thead><tr>'+cols.map(c=>'<th class="'+(c.kind==='num'?'num':'')+'" data-clsort="'+c.k+'" title="Click to sort">'+c.t+sortMark(c.k)+(c.k==='L1'||c.k==='L2'||c.k==='L3'?'<div style="font-size:9px;font-weight:400;text-transform:none">Current · last week · Δ</div>':'')+'</th>').join('')+'</tr>'+
    '<tr>'+cols.map(c=>'<th class="nosort '+(c.kind==='num'?'num':'')+'"><input data-clfilter="'+c.k+'" value="'+esc(s.tableFilters[c.k]||'')+'" placeholder="'+c.ph+'" style="width:100%;min-width:'+(c.kind==='num'?'86':'105')+'px;font-size:10.5px;padding:3px 5px"></th>').join('')+'</tr></thead><tbody>';
  if(!slice.length)h+='<tr><td colspan="12" class="empty">No equipment matches the current table filters.</td></tr>';
  slice.forEach((r,i)=>{
    h+='<tr><td><button type="button" class="cl-eli-link cl-eq-history" data-row="'+i+'">'+esc(r.asset_name)+'</button></td><td>'+esc(r.equipment_type)+'</td><td>'+esc(r.tranche)+'</td><td>'+esc(r.discipline)+'</td><td>'+esc(r.systems)+'</td><td>'+esc(r.equipment_supplier)+'</td>'+clProgressCompareCell(r,'L1')+clProgressCompareCell(r,'L2')+clProgressCompareCell(r,'L3')+'<td class="num">'+clPctCell(r.L4_completion_pct)+'</td><td class="num">'+clPctCell(r.L5_completion_pct)+'</td><td class="num"><b>'+clPctCell(r.overall_completion_pct)+'</b></td></tr>';
  });
  const tbl=document.getElementById('clTable');tbl.innerHTML=h+'</tbody>';
  const wk=clWeekInfo();
  document.getElementById('clTableMeta').textContent=fmtInt(rows.length)+' shown of '+fmtInt(source.length)+' equipment in scope · L1–L3 compare current vs last completed week'+(wk.previous?' ('+wk.previous+')':'')+' · click an ELI for daily history';
  document.getElementById('clPageInfo').textContent='Page '+(s.page+1)+' of '+pages;document.getElementById('clPrev').disabled=s.page<=0;document.getElementById('clNext').disabled=s.page>=pages-1;
  tbl.querySelectorAll('th[data-clsort]').forEach(th=>th.onclick=()=>{const k=th.dataset.clsort;s.tableSort={k,dir:s.tableSort.k===k?-s.tableSort.dir:1};s.page=0;clRenderTable();});
  tbl.querySelectorAll('input[data-clfilter]').forEach(inp=>{
    inp.addEventListener('click',e=>e.stopPropagation());
    inp.oninput=debounce(e=>{s.tableFilters[e.target.dataset.clfilter]=e.target.value;s.page=0;clRenderTable();},250);
  });
  document.querySelectorAll('.cl-eq-history').forEach(btn=>btn.onclick=()=>clShowEquipmentHistory(slice[Number(btn.dataset.row)]));
}
'''

html = html[:start] + new_block + html[end:]

reset_old = "checklistState.trendLevel='Overall';document.getElementById('clTrendLevel').value='Overall';clRefresh();"
reset_new = "checklistState.trendLevel='Overall';checklistState.tableFilters={};checklistState.tableSort={k:'asset_name',dir:1};document.getElementById('clTrendLevel').value='Overall';clRefresh();"
if reset_old in html:
    html = html.replace(reset_old, reset_new, 1)
else:
    print('Warning: reset hook not found; table filters will persist until reload')

path.write_text(html, encoding='utf-8')
print('Completion by equipment is now sortable and filterable')
