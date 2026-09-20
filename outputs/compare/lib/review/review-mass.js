const GROUP_COLORS = {
  wing: '#377fb3', hstab: '#68853c', vstab: '#b95e53', booms: '#508b97',
  fuselage: '#78838a', battery: '#459575', solar_power: '#c38532',
  propulsion: '#a66890', avionics_controls: '#5c66b8', other: '#555b60',
};
const PART_COLORS = ['#377fb3','#459575','#c38532','#a66890','#5c66b8','#68853c','#b95e53','#508b97'];
const state = {unit:'kg', expanded:new Set()};

export function renderMass(root, payload, ui) {
  const {heading,metric,sectionHead,icon,fmt,pct,esc,colors,labelInfo,closeDefinitions} = ui;
  const a = payload.mass.allocation;
  const charts = [];
  if (!a) {
    root.innerHTML = heading('Mass breakdown','Modeled aircraft allocation.') + '<div class="empty">Mass allocation is unavailable for this snapshot.</div>';
    return charts;
  }
  const factor = () => state.unit === 'g' ? 1000 : 1;
  const mass = kg => fmt(kg * factor(), state.unit === 'g' ? 1 : 3);
  const groups = [...a.groups].sort((x,y) => y.mass_kg-x.mass_kg);
  const parts = g => g.children.length===1 && g.children[0].children.length ? g.children[0].children : g.children;
  const battery = a.groups.find(g=>g.id==='battery');
  let draw;

  function pie(canvasId, rows, total, palette, click) {
    const c = colors();
    const chart = new Chart(document.getElementById(canvasId), {
      type:'doughnut',
      data:{labels:rows.map(r=>r.label),datasets:[{
        data:rows.map(r=>r.mass_kg),backgroundColor:palette,
        borderColor:c.bg,borderWidth:3,hoverOffset:4,
      }]},
      options:{responsive:true,maintainAspectRatio:false,animation:false,cutout:'69%',layout:{padding:6},
        onClick:click ? (_, elements)=>{if(elements[0]) click(rows[elements[0].index]);} : undefined,
        onHover:(event,elements)=>{event.native.target.style.cursor=click&&elements.length?'pointer':'default';},
        plugins:{legend:{display:false},tooltip:{backgroundColor:c.ink,titleColor:c.bg,bodyColor:c.bg,padding:11,
          callbacks:{label:ctx=>`${mass(ctx.raw)} ${state.unit} · ${pct(ctx.raw/total,1)} of ${canvasId==='mass-total-chart'?'aircraft':'portion'}`},
        }},
      },
    });
    charts.push(chart);
    return chart;
  }

  function jump(id) {
    const section = document.getElementById('mass-section-'+id);
    section.querySelector('h2').focus({preventScroll:true});
    section.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
  }

  function tableRows(rows, group, depth=0, path='') {
    return rows.map((r,i)=>{
      const key = path+'/'+r.id, expandable=r.children.length>0, expanded=state.expanded.has(key);
      const share = group.mass_kg ? r.mass_kg/group.mass_kg : 0;
      const color=depth===0?PART_COLORS[i%PART_COLORS.length]:'var(--strong)';
      return `<tr class="mass-part-row depth-${depth}" data-node="${esc(r.id)}">
        <td style="--depth:${depth}">${expandable?`<button class="mass-node-toggle" data-expand="${esc(key)}" aria-expanded="${expanded}" aria-label="${expanded?'Collapse':'Expand'} ${esc(r.label)}">${icon(expanded?'chevron-down':'chevron-right')}</button>`:'<span class="mass-node-spacer"></span>'}<span class="swatch" style="background:${color}"></span>${labelInfo(r.label,{text:[r.note,r.source?`Model allocation: ${r.source}`:''].filter(Boolean).join(' ')})}${r.note?`<small class="mass-part-note">${esc(r.note)}</small>`:''}</td>
        <td class="num">${mass(r.mass_kg)}</td><td class="num">${pct(share,1)}</td><td class="num muted">${pct(r.mass_kg/a.total_kg,1)}</td></tr>
        ${expandable&&expanded?tableRows(r.children,group,depth+1,key):''}`;
    }).join('');
  }

  function bindRows(g) {
    closeDefinitions();
    const body=document.getElementById('mass-parts-'+g.id);
    body.innerHTML=tableRows(parts(g),g,0,g.id);
    const all=root.querySelector(`[data-expand-all="${g.id}"]`);
    if(all) all.innerHTML=icon('list-tree')+(expansionKeys(g).every(k=>state.expanded.has(k))?'Collapse all':'Expand all');
    body.querySelectorAll('[data-expand]').forEach(b=>b.onclick=()=>{
      const key=b.dataset.expand;
      state.expanded.has(key)?state.expanded.delete(key):state.expanded.add(key);
      bindRows(g);lucide.createIcons({attrs:{'aria-hidden':'true'}});
      body.querySelector(`[data-expand="${CSS.escape(key)}"]`)?.focus({preventScroll:true});
    });
  }

  function expansionKeys(g) {
    const keys=[];
    function collect(rows,path){for(const r of rows)if(r.children.length){const key=path+'/'+r.id;keys.push(key);collect(r.children,key);}}
    collect(parts(g),g.id);
    return keys;
  }

  draw = () => {
    closeDefinitions();
    charts.forEach(c=>c.destroy());charts.length=0;
    root.innerHTML=heading('Mass breakdown','Provisional RE allocations · installed assemblies',
      `<div class="segmented mass-units" aria-label="Mass units">${['kg','g'].map(u=>`<button data-mass-unit="${u}" aria-pressed="${state.unit===u}">${u}</button>`).join('')}</div>`)+
      `<div class="metric-band mass-metrics">
        ${metric('TOTAL MODELED MASS',mass(a.total_kg),state.unit,'All installed allocations')}
        ${metric('TAKEOFF MASS LIMIT',mass(a.limit_kg),state.unit,'Current design requirement')}
        ${metric('MASS HEADROOM',mass(a.headroom_kg),state.unit,'Unassigned · not distributed to assemblies',a.headroom_kg>=0?'good':'bad')}
        ${metric('BATTERY FRACTION',fmt(battery.mass_kg/a.total_kg*100,1),'%',`${payload.metrics.n_packs} packs · ${mass(battery.mass_kg)} ${state.unit}`)}
      </div>
      <section>${sectionHead('Assembly allocations',`${groups.length} assemblies · modeled mass only`)}
        <div class="mass-overview"><div class="mass-pie-wrap"><canvas id="mass-total-chart" role="img" aria-label="Aircraft mass allocation by portion"></canvas><div class="mass-pie-center"><strong>${mass(a.total_kg)}<small>${state.unit}</small></strong><span>Total aircraft</span></div></div>
        <div><div class="table-scroll"><table class="mass-allocation-table"><thead><tr><th>Assembly</th><th class="num">Qty</th><th class="num">Allocation · ${state.unit}</th><th class="num">Each · ${state.unit}</th><th class="num">${labelInfo('Aircraft share')}</th><th></th></tr></thead><tbody>${groups.map(g=>`<tr data-mass-group="${g.id}"><td><button class="mass-jump" data-jump="${g.id}"><span class="swatch" style="background:${GROUP_COLORS[g.id]}"></span>${esc(g.label)}</button></td><td class="num">${g.quantity}</td><td class="num">${mass(g.mass_kg)}</td><td class="num">${mass(g.per_item_kg)}</td><td class="num">${pct(g.mass_kg/a.total_kg,1)}</td><td><button class="icon-button mass-jump-icon" data-jump="${g.id}" title="${esc(g.label)} detail" aria-label="${esc(g.label)} detail">${icon('arrow-down')}</button></td></tr>`).join('')}</tbody><tfoot><tr><td><strong>Total</strong></td><td></td><td class="num"><strong>${mass(a.total_kg)}</strong></td><td></td><td class="num">100.0%</td><td></td></tr></tfoot></table></div>
        <div class="mass-budget"><div><span>Takeoff mass budget</span><strong>${pct(a.total_kg/a.limit_kg,1)} used</strong></div><div class="mass-budget-track" role="meter" aria-label="Takeoff mass budget used" aria-valuemin="0" aria-valuemax="${a.limit_kg}" aria-valuenow="${Math.min(a.total_kg,a.limit_kg)}" aria-valuetext="${pct(a.total_kg/a.limit_kg,1)} used"><i style="width:${Math.min(100,a.total_kg/a.limit_kg*100)}%;background:${a.headroom_kg<0?'var(--red)':'var(--muted)'}"></i></div><small>${mass(Math.abs(a.headroom_kg))} ${state.unit} ${a.headroom_kg>=0?'remaining':'over limit'}</small></div></div></div>
      </section>
      <div class="callout">${icon('info')}<span>${esc(a.basis)} Solar cells follow their mounting surface; tail interfaces follow the receiving tail. Servo masses are provisional shares of the existing ${mass(a.servo_allocation.total_kg)} ${state.unit} budget, not selected hardware masses.</span></div>
      ${groups.map(g=>`<section class="section-band mass-detail" id="mass-section-${g.id}">
        <div class="mass-detail-heading"><div><h2 tabindex="-1"><span class="swatch" style="background:${GROUP_COLORS[g.id]}"></span>${esc(g.label)}</h2><p>${esc(g.note)}</p></div><div class="mass-detail-total"><strong>${mass(g.mass_kg)} <span>${state.unit}</span></strong><small>${g.quantity} ${g.quantity===1?'assembly':'assemblies'} · ${mass(g.per_item_kg)} ${state.unit} each</small><small>${pct(g.mass_kg/a.total_kg,1)} of aircraft</small></div></div>
        ${g.open_items.length?`<div class="mass-open-items"><strong>Scope to confirm</strong>${g.open_items.map(item=>`<p>${esc(item)}</p>`).join('')}</div>`:''}
        <div class="mass-detail-grid"><div class="mass-pie-wrap detail"><canvas id="mass-pie-${g.id}" role="img" aria-label="${esc(g.label)} component mass distribution"></canvas><div class="mass-pie-center"><strong>${pct(g.mass_kg/a.total_kg,1)}</strong><span>of aircraft</span></div></div>
          <div><div class="mass-table-toolbar"><span>${parts(g).length} allocations</span>${parts(g).some(p=>p.children.length)?`<button class="text-button" data-expand-all="${g.id}">${icon('list-tree')}Expand all</button>`:''}</div>
          <div class="table-scroll"><table class="mass-parts-table"><thead><tr><th>Component</th><th class="num">Mass · ${state.unit}</th><th class="num">${labelInfo('Portion %')}</th><th class="num">${labelInfo('Aircraft %')}</th></tr></thead><tbody id="mass-parts-${g.id}"></tbody><tfoot><tr><td><strong>Portion total</strong></td><td class="num"><strong>${mass(g.mass_kg)}</strong></td><td class="num">100.0%</td><td class="num">${pct(g.mass_kg/a.total_kg,1)}</td></tr></tfoot></table></div></div></div>
      </section>`).join('')}
      <section class="section-band mass-accounting">${sectionHead('Mass reconciliation','Full-precision model check')}<div class="mass-accounting-grid"><span>Allocated portions<strong>${mass(a.total_kg)} ${state.unit}</strong></span><span>Aircraft model<strong>${mass(payload.dims.mass_kg)} ${state.unit}</strong></span><span>Residual<strong class="${Math.abs(a.difference_kg)<1e-8?'good':'bad'}">${mass(a.difference_kg)} ${state.unit}</strong></span><span>Basis<strong>Calculated mass build-up</strong></span></div><p class="plot-note">Areal-mass structural estimates and configured hardware/fixed budgets. No detailed spar, rib, fastener or as-built breakdown is implied where the model has no separate allocation.</p></section>`;
    const top=pie('mass-total-chart',groups,a.total_kg,groups.map(g=>GROUP_COLORS[g.id]),g=>jump(g.id));
    root.querySelectorAll('[data-jump]').forEach(b=>b.onclick=()=>jump(b.dataset.jump));
    root.querySelectorAll('[data-mass-group]').forEach(row=>{
      row.onmouseenter=()=>{top.setActiveElements([{datasetIndex:0,index:groups.findIndex(g=>g.id===row.dataset.massGroup)}]);top.update('none');};
      row.onmouseleave=()=>{top.setActiveElements([]);top.update('none');};
    });
    for(const g of groups){pie('mass-pie-'+g.id,parts(g),g.mass_kg,parts(g).map((_,i)=>PART_COLORS[i%PART_COLORS.length]));bindRows(g);}
    root.querySelectorAll('[data-expand-all]').forEach(b=>b.onclick=()=>{
      const g=groups.find(g=>g.id===b.dataset.expandAll),keys=expansionKeys(g);
      const collapse=keys.every(k=>state.expanded.has(k));
      keys.forEach(k=>collapse?state.expanded.delete(k):state.expanded.add(k));
      bindRows(g);lucide.createIcons({attrs:{'aria-hidden':'true'}});
    });
    root.querySelectorAll('[data-mass-unit]').forEach(b=>b.onclick=()=>{state.unit=b.dataset.massUnit;draw();});
    lucide.createIcons({attrs:{'aria-hidden':'true'}});
  };
  draw();
  return charts;
}
