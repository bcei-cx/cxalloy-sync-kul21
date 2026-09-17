from pathlib import Path

path = Path('index.html')
html = path.read_text(encoding='utf-8')
start = html.find('function clRenderTable(){')
end = html.find('\nfunction clEnsureEquipmentHistoryModal(){', start)
if start < 0 or end < 0:
    raise SystemExit('Completion by equipment table block not found')

replacement = r'''function clTableValue(r,k){
  if(k==='asset_name'||k==='equipment_type'||k==='tranche'||k==='discipline'||k==='systems'||k==='equipment_supplier')return txtValue(r[k]);
  if(/^L[1-5]$/.test(k)){const v=r[k+'_completion_pct'];return v===null||v===undefined||String(v).trim()===''?null:Number(v);}
  if(k==='overall'){const v=r.overall_completion_pct;return v===null||v===undefined||String(v).trim()===''?null:Number(v);}
  return '';
}
function clTableNumericMatch(value,query){
  const q=String(query||'').trim();if(!q)return true;if(value===null||!Number.isFinite(Number(value)))return false;
  const v=Number(value),m=q.match(/^\s*(>=|<=|>|<|=)?\s*(-?\d+(?:\.\d+)?)\s*%?\s*$/);
  if(!m)return String(v).includes(q);
  const op=m[1]||'=',n=Number(m[2]);
  return op==='>='?v>=n:op==='<='?v<=n:op==='>'?v>n:op==='<'?v<n:Math.abs(v-n)<0.0001;
}
function clRenderTable(){
  const s=checklistState;
  s.tableFilters=s.tableFilters||{};
  s.tableSort=s.tableSort||{k:'asset_name',dir:1};
  const numeric=new Set(['L1','L2','L3','L4','L5','overall']);
  const cols=[
    {k:'asset_name',t:'ELI'},{k:'equipment_type',t:'Equipment Type'},{k:'tranche',t:'Tranche'},
    {k:'discipline',t:'Discipline'},{k:'systems',t:'System'},{k:'equipment_supplier',t:'Equipment Supplier'},
    {k:'L1',t:'L1',sub:'Current · last week · Δ'},{k:'L2',t:'L2',sub:'Current · last week · Δ'},
    {k:'L3',t:'L3',sub:'Current · last week · Δ'},{k:'L4',t:'L4'},{k:'L5',t:'L5'},{k:'overall',t:'Overall'}
  ];
  let rows=s.filtered.slice();
  const active=Object.entries(s.tableFilters).filter(([,v])=>String(v||'').trim());
  if(active.length){
    rows=rows.filter(r=>active.every(([k,q])=>{
      const v=clTableValue(r,k);
      return numeric.has(k)?clTableNumericMatch(v,q):txtValue(v).toLowerCase().includes(String(q).trim().toLowerCase());
    }));
  }
  const sort=s.tableSort;
  rows.sort((a,b)=>{
    const va=clTableValue(a,sort.k),vb=clTableValue(b,sort.k);
    if(numeric.has(sort.k)){
      const aa=(va===null||!Number.isFinite(Number(va)))?-Infinity:Number(va),bb=(vb===null||!Number.isFinite(Number(vb)))?-Infinity:Number(vb);
      return (aa-bb)*sort.dir;
    }
    return txtValue(va).localeCompare(txtValue(vb),undefined,{numeric:true,sensitivity:'base'})*sort.dir;
  });
  const pages=Math.max(1,Math.ceil(rows.length/s.pageSize));if(s.page>=pages)s.page=pages-1;if(s.page<0)s.page=0;
  const slice=rows.slice(s.page*s.pageSize,(s.page+1)*s.pageSize);
  const th=c=>'<th data-clsort="'+c.k+'" class="'+(numeric.has(c.k)?'num':'')+'" style="cursor:pointer">'+esc(c.t)+(sort.k===c.k?(sort.dir>0?' ▲':' ▼'):'')+(c.sub?'<div style="font-size:9px;font-weight:400;text-transform:none">'+c.sub+'</div>':'')+'</th>';
  const filter=c=>'<th class="nosort '+(numeric.has(c.k)?'num':'')+'"><input data-clfilter="'+c.k+'" value="'+esc(s.tableFilters[c.k]||'')+'" placeholder="'+(numeric.has(c.k)?'e.g. >=50':'filter')+'" style="width:100%;min-width:'+(numeric.has(c.k)?'76':'92')+'px;font-size:10.5px;padding:3px 5px"></th>';
  let h='<thead><tr>'+cols.map(th).join('')+'</tr><tr>'+cols.map(filter).join('')+'</tr></thead><tbody>';
  if(!slice.length)h+='<tr><td colspan="12" class="empty">No equipment matches the current table filters.</td></tr>';
  slice.forEach((r,i)=>{
    h+='<tr><td><button type="button" class="cl-eli-link cl-eq-history" data-row="'+i+'">'+esc(r.asset_name)+'</button></td><td>'+esc(r.equipment_type)+'</td><td>'+esc(r.tranche)+'</td><td>'+esc(r.discipline)+'</td><td>'+esc(r.systems)+'</td><td>'+esc(r.equipment_supplier)+'</td>'+clProgressCompareCell(r,'L1')+clProgressCompareCell(r,'L2')+clProgressCompareCell(r,'L3')+'<td class="num">'+clPctCell(r.L4_completion_pct)+'</td><td class="num">'+clPctCell(r.L5_completion_pct)+'</td><td class="num"><b>'+clPctCell(r.overall_completion_pct)+'</b></td></tr>';
  });
  const tbl=document.getElementById('clTable');tbl.innerHTML=h+'</tbody>';
  const wk=clWeekInfo(),filteredNote=active.length?' · '+fmtInt(rows.length)+' after table filters':'';
  document.getElementById('clTableMeta').textContent=fmtInt(s.filtered.length)+' equipment in scope'+filteredNote+' · L1–L3 compare current vs last completed week'+(wk.previous?' ('+wk.previous+')':'')+' · click an ELI for daily history';
  document.getElementById('clPageInfo').textContent='Page '+(s.page+1)+' of '+pages;document.getElementById('clPrev').disabled=s.page<=0;document.getElementById('clNext').disabled=s.page>=pages-1;
  tbl.querySelectorAll('th[data-clsort]').forEach(el=>el.onclick=()=>{const k=el.dataset.clsort;s.tableSort={k,dir:s.tableSort.k===k?-s.tableSort.dir:1};s.page=0;clRenderTable();});
  tbl.querySelectorAll('input[data-clfilter]').forEach(inp=>inp.oninput=debounce(e=>{s.tableFilters[e.target.dataset.clfilter]=e.target.value;s.page=0;clRenderTable();},250));
  document.querySelectorAll('.cl-eq-history').forEach(btn=>btn.onclick=()=>clShowEquipmentHistory(slice[Number(btn.dataset.row)]));
}
'''

html = html[:start] + replacement + html[end:]
path.write_text(html, encoding='utf-8')
print('Added sorting and per-column filtering to Completion by equipment')
