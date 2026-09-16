import { createCAD } from './review-cad.js';
import { renderMass } from './review-mass.js';

const {META,CONFIGS}=window;
const IDS=META.comboOrder;
const NAV=[['overview','Overview','layout-dashboard'],['compare','Compare','columns-3'],['geometry','Geometry','box'],['mass','Mass breakdown','chart-pie'],['energy','Energy','chart-no-axes-combined'],['requirements','Requirements','list-checks'],['sources','Model & sources','file-clock']];
const NAMES={pi_tail:'Single empennage',split:'Split empennage',conventional:'Conventional',conventional_rectangular:'Conventional · rectangular'};
const SHORT={pi_tail:'Single emp.',split:'Split emp.',conventional:'Conventional',conventional_rectangular:'Rectangular'};
const PALETTE=['#377fb3','#459575','#c38532','#a66890','#5c66b8','#68853c','#b95e53','#508b97'];
const query=new URLSearchParams(location.search);
let current=IDS.includes(query.get('cfg'))?query.get('cfg'):IDS.includes(sessionStorage.getItem('av-cfg'))?sessionStorage.getItem('av-cfg'):'conventional__gold_v1';
let view=NAV.some(n=>n[0]===query.get('view'))?query.get('view'):'overview';
let selected=new Set(IDS.filter(id=>CONFIGS[id].battery_id===CONFIGS[current].battery_id));
let baseline=current,comparisonMode='both',checkFilter='all',duration=89;
let cad,charts=[],toastTimer;
const root=document.getElementById('content');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finite=v=>typeof v==='number'&&Number.isFinite(v);
const fmt=(v,d=2)=>finite(v)?(Math.abs(v)<.5*10**-d?0:v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
const signed=(v,d=2)=>finite(v)?(Math.abs(v)<.5*10**-d?'':v>0?'+':'')+fmt(v,d):'—';
const pct=(v,d=2)=>finite(v)?fmt(v*100,d)+'%':'—';
const icon=(name)=>`<i data-lucide="${name}"></i>`;
const button=(label,id,kind='button')=>`<button id="${id}" class="${kind}">${label}</button>`;
const data=()=>CONFIGS[current].payload;
const label=id=>`${SHORT[CONFIGS[id].layout_id]} · ${CONFIGS[id].payload.combo.battery_label}`;
function statusBadge(status,label){return `<span class="badge ${status}">${icon(status==='pass'?'check':status==='fail'?'x':'minus')}${label||({pass:'Pass',fail:'Fail',not_evaluated:'Not evaluated',open:'Open item'}[status])}</span>`;}
function icons(){lucide.createIcons({attrs:{'aria-hidden':'true'}});}
function notify(message){const el=document.getElementById('notification');el.textContent=message;el.classList.add('on');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('on'),2500);}
function syncURL(replace=false){const q=new URLSearchParams({cfg:current,view});history[replace?'replaceState':'pushState']({},'',`${location.pathname}?${q}`);}
function choose(id){if(!IDS.includes(id))return;current=id;sessionStorage.setItem('av-cfg',id);syncURL();render();}
function navigate(next){view=next;syncURL();render();window.scrollTo({top:0});}
function cleanup(){cad?.dispose();cad=null;charts.forEach(c=>c.destroy());charts=[];}
function heading(title,subtitle,action=''){return `<div class="page-heading"><div><div class="eyebrow">${esc(NAMES[CONFIGS[current].layout_id])} / ${esc(data().combo.battery_label)}</div><h1>${title}</h1><p>${subtitle}</p></div>${action}</div>`;}
function metric(name,value,unit,detail,cls=''){return `<div class="metric"><span class="metric-label">${name}</span><div class="metric-value ${cls}">${value}<span class="unit">${unit}</span></div><span class="metric-sub">${detail}</span></div>`;}
function kv(rows){return rows.map(([k,v])=>`<div class="kv"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');}
function section(title,rows){return `<section class="kv-section"><h2>${title}</h2>${kv(rows)}</section>`;}
function sectionHead(title,sub='',action=''){return `<div class="section-head"><h2>${title}</h2>${action||`<small>${sub}</small>`}</div>`;}
function mountCAD(){cad=createCAD(document.getElementById('cad'),CONFIGS[current]);icons();}
function colors(){const s=getComputedStyle(document.documentElement);return Object.fromEntries(['ink','muted','line','blue','green','red','graph2','bg'].map(k=>[k,s.getPropertyValue('--'+k).trim()]));}
function chart(id,type,datasets,{xLabel='',yLabel='',min,max,xMin=0,xMax,labels,indexAxis,legend=true,stacked=false}={}){
  const c=colors();
  const ch=new Chart(document.getElementById(id),{
    type,data:{labels,datasets},
    options:{
      responsive:true,maintainAspectRatio:false,animation:false,indexAxis:indexAxis||'x',
      interaction:{mode:'index',intersect:false},
      plugins:{
        legend:{display:legend,position:'bottom',labels:{color:c.muted,boxWidth:8,boxHeight:8,usePointStyle:true,font:{size:10},padding:14}},
        tooltip:{backgroundColor:c.ink,titleColor:c.bg,bodyColor:c.bg,displayColors:true,padding:10},
      },
      scales:{
        x:{type:labels?'category':'linear',min:labels?undefined:xMin,max:xMax,stacked,
          title:{display:!!xLabel,text:xLabel,color:c.muted,font:{size:10}},
          grid:{display:false},ticks:{color:c.muted,maxRotation:0,maxTicksLimit:7,font:{size:10}}},
        y:{min,max,stacked,title:{display:!!yLabel,text:yLabel,color:c.muted,font:{size:10}},
          grid:{color:c.line},ticks:{color:c.muted,maxTicksLimit:6,font:{size:10}}},
      },
    },
  });
  charts.push(ch);return ch;
}
function line(label,x,y,color,extra={}){return {label,data:x.map((v,i)=>({x:v,y:y[i]})),borderColor:color,backgroundColor:color,pointRadius:0,borderWidth:1.8,tension:0,...extra};}
function socChart(id,ids=[current],max=89){const c=colors();const datasets=ids.map((key,i)=>{const e=CONFIGS[key].payload.energy;return line(ids.length>1?label(key):'Battery SOC',e.hours,e.soc.map(v=>100*v),ids.length>1?PALETTE[IDS.indexOf(key)]:c.blue);});datasets.push(line('Reserve floor',[0,89],[20,20],c.red,{borderDash:[4,4],borderWidth:1}));return chart(id,'line',datasets,{yLabel:'State of charge (%)',xLabel:'Elapsed hours · 08:00 start',min:0,max:100,xMax:max});}
function threshold(check){if(check.direction==='none')return 'Separate analysis';if(check.direction==='boolean')return 'Required';const op=check.direction==='min'?(check.strict?'>':'≥'):(check.strict?'<':'≤');return `${op} ${fmt(check.limit,check.id==='mass'||check.id==='span'?2:check.id==='recovery'?0:1)} ${esc(check.unit)}`;}
function actual(check){if(check.direction==='none')return '—';if(check.direction==='boolean')return check.actual?'Satisfied':'Not satisfied';if(check.id==='recovery'&&Math.abs(check.actual)<1e-6)return `${check.actual===0?'0':check.actual.toExponential(2)} pp`;return `${fmt(check.actual,check.id==='mass'?3:2)} ${esc(check.unit)}`;}
function headroom(check){if(!finite(check.headroom))return '—';const unit=check.unit==='%'||check.unit==='% MAC'?'pp':check.unit;if(check.id==='recovery'&&Math.abs(check.headroom)<1e-6)return check.headroom===0?'0 pp':`${check.headroom.toExponential(2)} pp`;return `${signed(check.headroom,check.id==='mass'?3:2)} ${esc(unit)}`;}

function overview(){
  const p=data(),e=p.energy,d=p.dims,m=p.metrics,review=p.review;
  const ranking=IDS.filter(id=>CONFIGS[id].battery_id===CONFIGS[current].battery_id).sort((a,b)=>CONFIGS[b].payload.energy.objective_soc-CONFIGS[a].payload.energy.objective_soc);
  const checks=['recovery','reserve','mass','span','climb'].map(id=>review.checks.find(c=>c.id===id));
  root.innerHTML=heading('Design overview','Best evaluated candidate · clear-sky design day',button(`Compare designs ${icon('arrow-up-right')}`,'go-compare'))+
    `<div class="metric-band">
      ${metric('MORNING SOC',fmt(e.objective_soc*100,2),'%',`${fmt(100*(e.objective_soc-e.soc_floor),2)} pp above reserve`,e.objective_soc>=e.soc_floor?'good':'bad')}
      ${metric('ENERGY RESERVE',fmt(e.reserve_wh,1),'Wh','Above the 20% floor',e.reserve_wh>=0?'good':'bad')}
      ${metric('TAKEOFF MASS',fmt(d.mass_kg,3),'kg',`${fmt(review.inputs.MTOW_MAX_KG-d.mass_kg,3)} kg headroom`)}
      ${metric('NIGHT BUS POWER',fmt(e.p_night_w,1),'W',`${fmt(e.v_night_ms,2)} m/s cruise`)}
      ${metric('LIFT / DRAG',fmt(p.drag.ld,1),'',`Night operating point`)}
      ${metric('BATTERY ENERGY',fmt(m.pack_wh,0),'Wh',`${m.n_packs} packs · ${fmt(m.pack_wh_each,0)} Wh each`)}
    </div>
    <div class="overview-primary"><section>${sectionHead('Aircraft configuration','SI geometry',`<button class="text-button" id="go-geometry">Geometry ${icon('arrow-up-right')}</button>`)}<div id="cad" class="cad-host"></div>
      <div class="geometry-strip"><span>Wingspan<b>${fmt(d.span_m,3)} m</b></span><span>Wing area<b>${fmt(d.wing_area_m2,3)} m²</b></span><span>Solar array<b>${m.n_cells} cells · ${d.n_strings} MPPTs</b></span><span>Propulsion<b>${m.n_motors} × ${esc(m.prop)}</b></span></div></section>
      <section>${sectionHead('Critical requirements','',`<button class="text-button" id="go-requirements">All checks ${icon('arrow-up-right')}</button>`)}
      <table class="compact"><thead><tr><th>Requirement</th><th class="num">Actual / limit</th><th class="num">Status</th></tr></thead><tbody>${checks.map(c=>`<tr><td>${c.label}</td><td class="num">${actual(c)}<small>${threshold(c)}</small></td><td>${statusBadge(c.status)}</td></tr>`).join('')}</tbody></table>
      <div class="review-note">${icon('shield-alert')}<span>Structures & aeroelasticity remain unverified. Feasibility applies to the current model only.</span></div>
      <button class="text-button" id="go-sources">${review.warnings.length} model notes & assumptions ${icon('arrow-up-right')}</button></section></div>
    <div class="overview-secondary"><section>${sectionHead('Battery state of charge','89-hour visualization')}<div class="chart-box"><canvas id="overview-soc"></canvas></div><p class="plot-note">Starts at 100% SOC. Acceptance uses the separate morning-to-morning cycle.</p></section>
      <section>${sectionHead('Configuration trade study',p.combo.battery_label)}<div class="ranking">${ranking.map(id=>{const q=CONFIGS[id].payload;return `<button class="rank-row ${id===current?'current':''}" data-case="${id}"><span>${SHORT[CONFIGS[id].layout_id]}</span><span class="rank-track"><i style="width:${q.energy.objective_soc/0.5*100}%"></i></span><span class="rank-score">${pct(q.energy.objective_soc,2)}</span></button>`;}).join('')}</div><p class="plot-note">Morning SOC · higher is better · same battery option</p><div class="callout">${icon('circle-check')}<span>Source and recomputed morning SOC agree within ${Math.abs(p.study.morning_soc_difference_pp)<1e-6?'0.000001':fmt(Math.abs(p.study.morning_soc_difference_pp),6)} percentage points.</span></div></section></div>`;
  ['compare','geometry','requirements','sources'].forEach(v=>document.getElementById('go-'+v).onclick=()=>navigate(v));
  root.querySelectorAll('[data-case]').forEach(b=>b.onclick=()=>choose(b.dataset.case));mountCAD();socChart('overview-soc');
}

const METRICS=[
  {section:'Mission & energy'},
  {name:'Morning SOC',unit:'%',get:p=>p.energy.objective_soc*100,d:2,better:'high',deltaUnit:'pp'},
  {name:'Minimum scored SOC',unit:'%',get:p=>p.energy.soc_min*100,d:2,better:'high',deltaUnit:'pp'},
  {name:'Energy reserve',unit:'Wh',get:p=>p.energy.reserve_wh,d:1,better:'high'},
  {name:'Night bus power',unit:'W',get:p=>p.energy.p_night_w,d:1,better:'low'},
  {name:'Day bus power',unit:'W',get:p=>p.energy.p_day_w,d:1,better:'low'},
  {name:'Solar energy / scored day',unit:'Wh',get:p=>p.energy.solar_wh,d:1},
  {name:'Spilled energy / scored day',unit:'Wh',get:p=>p.energy.spilled_wh,d:1},
  {name:'Climb rate',unit:'m/s',get:p=>p.energy.climb_ms,d:2,better:'high'},
  {section:'Mass & geometry'},
  {name:'Takeoff mass',unit:'kg',get:p=>p.dims.mass_kg,d:3,better:'low'},
  {name:'Wingspan',unit:'m',get:p=>p.dims.span_m,d:3},
  {name:'Root chord',unit:'m',get:p=>p.dims.chord_m,d:3},
  {name:'Tip chord',unit:'m',get:p=>p.dims.tip_chord_m,d:3},
  {name:'Wing area',unit:'m²',get:p=>p.dims.wing_area_m2,d:3},
  {name:'Aspect ratio',unit:'—',get:p=>p.dims.aspect_ratio,d:2},
  {name:'Taper ratio',unit:'—',get:p=>p.dims.taper_ratio,d:3},
  {name:'Tip washout',unit:'deg',get:p=>p.dims.washout_tip_deg,d:2},
  {name:'Horizontal tail arm',unit:'m',get:p=>p.dims.tail_arm_m,d:3},
  {name:'Vertical tail arm',unit:'m',get:p=>p.dims.vstab_arm_m,d:3},
  {section:'Aerodynamics & control'},
  {name:'Night airspeed',unit:'m/s',get:p=>p.energy.v_night_ms,d:2},
  {name:'Stall airspeed',unit:'m/s',get:p=>p.dims.v_stall_ms,d:2,better:'low'},
  {name:'Night lift / drag',unit:'—',get:p=>p.drag.ld,d:2,better:'high'},
  {name:'Static margin',unit:'% MAC',get:p=>p.dims.static_margin*100,d:2,deltaUnit:'pp'},
  {name:'Roll rate',unit:'deg/s',get:p=>p.dims.roll_rate_deg_s,d:2,better:'high'},
  {section:'Hardware'},
  {name:'Battery packs',unit:'count',get:p=>p.metrics.n_packs,d:0},
  {name:'Nominal battery energy',unit:'Wh',get:p=>p.metrics.pack_wh,d:1},
  {name:'Solar cells',unit:'count',get:p=>p.metrics.n_cells,d:0},
  {name:'MPPTs / strings',unit:'count',get:p=>p.dims.n_strings,d:0},
  {name:'String plan',unit:'cells',get:p=>p.metrics.string_plan,text:true},
  {name:'Motors',unit:'count',get:p=>p.metrics.n_motors,d:0},
  {name:'Propeller',unit:'SKU',get:p=>p.metrics.prop,text:true},
  {name:'Model feasibility',unit:'—',get:p=>p.study.passed?'Pass':'Fail',text:true},
];
function comparisonIds(){return IDS.filter(id=>selected.has(id));}
function diffClass(delta,better){if(!finite(delta)||Math.abs(delta)<1e-8||!better)return 'neutral';return (better==='high'?delta>0:delta<0)?'good':'bad';}
function compare(){
  const ids=comparisonIds();if(!selected.has(baseline))baseline=ids[0];
  root.innerHTML=heading('Compare configurations','Selected results, common design-day assumptions and model gates.')+
    `<div class="compare-controls"><div class="controls-row"><button id="select-current-battery" class="button">This battery</button><button id="select-all" class="button">All eight</button><span class="muted">${ids.length} selected</span></div>
    <div class="controls-row"><label>Baseline<select id="baseline-select" class="control" aria-label="Comparison baseline">${ids.map(id=>`<option value="${id}" ${id===baseline?'selected':''}>${esc(label(id))}</option>`).join('')}</select></label>
    <div class="segmented" aria-label="Comparison values">${[['absolute','Values'],['delta','Deltas'],['both','Both']].map(([id,name])=>`<button data-mode="${id}" aria-pressed="${comparisonMode===id}">${name}</button>`).join('')}</div></div></div>
    <div class="case-options">${IDS.map(id=>`<label><input type="checkbox" data-compare-case="${id}" ${selected.has(id)?'checked':''}>${esc(label(id))}</label>`).join('')}</div>
    <div class="comparison-scroll"><table class="compare-table"><thead><tr><th>Metric</th><th class="unit-cell">Unit</th>${ids.map(id=>`<th class="${id===baseline?'baseline':''}"><b>${SHORT[CONFIGS[id].layout_id]}</b><small>${CONFIGS[id].payload.combo.battery_label}${id===baseline?' · Baseline':''}</small></th>`).join('')}</tr></thead><tbody>
    ${METRICS.map(m=>m.section?`<tr class="group"><td>${m.section}</td><td colspan="${ids.length+1}"></td></tr>`:`<tr><td>${m.name}</td><td class="unit-cell">${m.unit}</td>${ids.map(id=>{const value=m.get(CONFIGS[id].payload),b=m.get(CONFIGS[baseline].payload),delta=value-b;const abs=m.text?esc(value):fmt(value,m.d);if(m.text||id===baseline||comparisonMode==='absolute')return `<td>${abs}</td>`;return `<td>${comparisonMode==='both'?abs:''}<span class="delta ${comparisonMode==='delta'?'only':''} ${diffClass(delta,m.better)}">${signed(delta,m.d)}${m.deltaUnit?' '+m.deltaUnit:''}</span></td>`;}).join('')}</tr>`).join('')}
    </tbody></table></div><p class="plot-note">Deltas = candidate minus baseline, in row units. Green / red applies only to metrics with a clear benefit direction; other differences are neutral.</p>
    <div class="section-band two-columns"><section>${sectionHead('SOC overlay','89-hour display, not the scored cycle')}<div class="chart-box tall"><canvas id="compare-soc"></canvas></div></section><section>${sectionHead('Mass versus morning SOC','Lower mass / higher SOC')}<div class="chart-box tall"><canvas id="compare-trade"></canvas></div></section></div>`;
  document.getElementById('select-current-battery').onclick=()=>{selected=new Set(IDS.filter(id=>CONFIGS[id].battery_id===CONFIGS[current].battery_id));rerenderView();};
  document.getElementById('select-all').onclick=()=>{selected=new Set(IDS);rerenderView();};
  root.querySelectorAll('[data-compare-case]').forEach(c=>c.onchange=()=>{if(!c.checked&&selected.size===1){c.checked=true;notify('Keep at least one configuration selected.');return;}c.checked?selected.add(c.dataset.compareCase):selected.delete(c.dataset.compareCase);rerenderView();});
  document.getElementById('baseline-select').onchange=e=>{baseline=e.target.value;rerenderView();};
  root.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{comparisonMode=b.dataset.mode;rerenderView();});
  socChart('compare-soc',ids);
  chart('compare-trade','scatter',ids.map(id=>({label:label(id),data:[{x:CONFIGS[id].payload.dims.mass_kg,y:100*CONFIGS[id].payload.energy.objective_soc}],backgroundColor:PALETTE[IDS.indexOf(id)],pointRadius:id===baseline?7:5,pointStyle:id===baseline?'rectRot':'circle'})),{xLabel:'Takeoff mass (kg)',yLabel:'Morning SOC (%)',xMin:Math.floor(Math.min(...ids.map(id=>CONFIGS[id].payload.dims.mass_kg))-.2),xMax:Math.ceil(Math.max(...ids.map(id=>CONFIGS[id].payload.dims.mass_kg))+.2)});
}

function geometry(){
  const p=data(),d=p.dims,m=p.mass;
  const components=Object.entries(m.components).sort((a,b)=>b[1].mass-a[1].mass);
  root.innerHTML=heading('Geometry & mass','Read-only optimized geometry and modeled component allocation.')+
    `<div id="cad" class="cad-host large"></div><div class="section-band three-columns">`+
    section('Wing', [['Span',fmt(d.span_m,3)+' m'],['Root / tip chord',fmt(d.chord_m,3)+' / '+fmt(d.tip_chord_m,3)+' m'],['Area',fmt(d.wing_area_m2,3)+' m²'],['Aspect ratio',fmt(d.aspect_ratio,2)],['Airfoil',d.wing_airfoil],['Taper ratio',fmt(d.taper_ratio,3)],['Tip washout',fmt(d.washout_tip_deg,2)+' deg'],['Whole-wing incidence',fmt(d.incidence_wing_deg,2)+' deg']])+
    section('Tail & control surfaces',[['Horizontal tail span',fmt(d.hstab_span_m,3)+' m'],['Horizontal tail chord',fmt(d.hstab_chord_m,3)+' m'],['Horizontal tail arm',fmt(d.tail_arm_m,3)+' m'],['Vertical tail height',fmt(d.vstab_height_m,3)+' m'],['Vertical tail chord',fmt(d.vstab_chord_m,3)+' m'],['Vertical tail arm',fmt(d.vstab_arm_m,3)+' m'],['Aileron span / side',fmt(d.aileron_span_each_m,3)+' m'],['Yaw control',p.metrics.n_motors===1?'Rudder':'Differential thrust'],...(p.metrics.n_motors===1?[['Rudder chord · installed / required',`${fmt(d.rudder_installed_chord_m*1000,1)} / ${fmt(d.rudder_required_chord_m*1000,1)} mm`],['Rudder moment · available / required',`${fmt(d.rudder_available_moment_nm,2)} / ${fmt(d.rudder_required_moment_nm,2)} N·m`]]:[])])+
    section('Installation',[['Motors',p.metrics.n_motors+' × '+p.metrics.motor],['Propeller',p.metrics.prop],['Propeller diameter',fmt(d.prop_diameter_in,1)+' in'],['Boom length',fmt(d.boom_length_m,3)+' m'],['Boom OD',fmt(p.metrics.boom_od_mm,2)+' mm'],['Fuselage length',fmt(d.fuselage_length_m,3)+' m'],['Solar cells',p.metrics.n_cells],['String plan',p.metrics.string_plan]])+`</div>
    <div class="section-band two-columns"><section>${sectionHead('Mass ledger','Modeled mass, not measured')}<div class="table-scroll"><table><thead><tr><th>Component</th><th class="num">Mass · kg</th><th class="num">Share</th><th></th></tr></thead><tbody>${components.map(([name,c])=>`<tr><td>${esc(name)}</td><td class="num">${fmt(c.mass,3)}</td><td class="num">${pct(c.mass/d.mass_kg,1)}</td><td><div class="mass-bar"><i style="width:${c.mass/d.mass_kg*100}%"></i></div></td></tr>`).join('')}<tr><td><b>Total</b></td><td class="num"><b>${fmt(d.mass_kg,3)}</b></td><td class="num">100%</td><td></td></tr></tbody></table></div></section>
    <section>${sectionHead('Mass distribution','Illustrative component positions')}<div class="chart-box"><canvas id="mass-chart"></canvas></div><div class="callout warn">${icon('triangle-alert')}<span>Component CG and inertia are illustrative. Stability calculations use an assumed quarter-chord CG, not these CAD positions.</span></div>${kv([['CAD lump CG · x',fmt(m.total.x_cg,3)+' m'],['CAD lump CG · y',fmt(m.total.y_cg,3)+' m'],['CAD lump CG · z',fmt(m.total.z_cg,3)+' m'],['Ixx / Iyy / Izz',`${fmt(m.total.Ixx,3)} / ${fmt(m.total.Iyy,3)} / ${fmt(m.total.Izz,3)} kg·m²`]])}</section></div>
    <div class="section-band">${sectionHead('Airfoil sections','Normalized coordinates')}<div class="foil-grid">${(p.airfoils||[]).map(f=>{const path=f.coords.map((xy,i)=>`${i?'L':'M'}${20+xy[0]*460},${65-xy[1]*460}`).join(' ');return `<section><h3>${esc(f.surface)} · ${esc(f.name)}</h3><svg class="foil" viewBox="0 0 500 130" role="img" aria-label="${esc(f.name)} airfoil"><path d="${path} Z" fill="none" stroke="var(--blue)" stroke-width="1.7"/><line x1="20" x2="480" y1="65" y2="65" stroke="var(--line)" stroke-dasharray="4 4"/></svg></section>`;}).join('')}</div></div>`;
  mountCAD();
  const byCategory={};for(const [name,c]of components){const category=m.positions[name].category;byCategory[category]=(byCategory[category]||0)+c.mass;}
  const entries=Object.entries(byCategory);
  chart('mass-chart','bar',[{label:'Mass',data:entries.map(x=>x[1]),backgroundColor:entries.map((_,i)=>PALETTE[i]),borderRadius:2,maxBarThickness:42}],{labels:entries.map(x=>x[0][0].toUpperCase()+x[0].slice(1)),yLabel:'Mass (kg)',min:0,legend:false});
}

function energy(){const p=data(),e=p.energy,m=p.metrics;
  root.innerHTML=heading('Energy & mission','Scored daily recovery and the separate extended visualization.')+
  `<div class="metric-band">${metric('CURRENT MORNING',fmt(e.morning_soc*100,2),'%',e.start_clock+' · net charging begins')}${metric('NEXT MORNING',fmt(e.next_morning_soc*100,2),'%','Same morning transition')}${metric('RESERVE',fmt(e.reserve_wh,1),'Wh','Above 20% SOC','good')}${metric('SOLAR / DAY',fmt(e.solar_wh,0),'Wh','Modeled solar supply')}${metric('PROPULSION / DAY',fmt(e.propulsion_wh,0),'Wh','Scored interval')}${metric('SPILL / DAY',fmt(e.spilled_wh,0),'Wh','Cannot offset overnight demand')}</div>
  <div class="section-head"><h2>Mission time histories</h2><div class="segmented" aria-label="Plot duration">${[24,48,89].map(n=>`<button data-duration="${n}" aria-pressed="${duration===n}">${n} h</button>`).join('')}</div></div>
  <div class="two-columns"><section><div class="chart-box tall"><canvas id="energy-soc"></canvas></div></section><section><div class="chart-box tall"><canvas id="energy-power"></canvas></div></section></div>
  <div class="callout">${icon('info')}<span>${p.review.display_basis}</span></div>
  <div class="section-band three-columns">${section('Battery bank',[['Pack count',m.n_packs],['Energy per pack',fmt(m.pack_wh_each,2)+' Wh'],['Capacity per pack',fmt(p.combo.pack_ah,2)+' Ah'],['Nominal bank energy',fmt(m.pack_wh,2)+' Wh'],['Usable energy (80%)',fmt(e.usable_wh,2)+' Wh'],['Charge current limit',fmt(p.review.inputs.PACK_CHARGE_MAX_A,1)+' A / pack'],['Modeled DCIR',fmt(p.review.inputs.PACK_R_INTERNAL_OHM*1000,1)+' mΩ / pack']])}
  ${section('Solar & power conversion',[['Solar cells',m.n_cells],['Strings / MPPTs',p.dims.n_strings],['Cells per string',m.string_plan],['MPPT topology','Proposed buck/boost'],['MPPT mass',fmt(p.review.inputs.MPPT_MASS_KG*1000,0)+' g each'],['MPPT efficiency',pct(p.review.inputs.MPPT_EFFICIENCY,0)],['Max input current',fmt(p.review.inputs.MPPT_MAX_INPUT_A,1)+' A']])}
  ${section('Operating point',[['Night airspeed',fmt(e.v_night_ms,2)+' m/s'],['Night bus power',fmt(e.p_night_w,2)+' W'],['Day bus power',fmt(e.p_day_w,2)+' W'],['Night interval',fmt(e.battery_night_h,2)+' h'],['Avionics / day',fmt(e.avionics_wh,1)+' Wh'],['Unserved demand',fmt(e.unmet_wh,3)+' Wh'],['Recovery ΔSOC',e.morning_soc_change.toExponential(3)+' SOC']])}</div>
  <div class="section-band two-columns"><section>${sectionHead('Night drag budget','At evaluated cruise speed')}<div class="chart-box tall"><canvas id="drag-chart"></canvas></div></section>${section('Aerodynamic state',[['Air density',fmt(p.drag.rho,4)+' kg/m³'],['Dynamic pressure',fmt(p.drag.q_pa,2)+' Pa'],['Net lift coefficient',fmt(p.drag.cl_net,3)],['Wing-reference drag coefficient',fmt(p.drag.cd_wingref,4)],['Total drag',fmt(p.drag.drag_total_n,3)+' N'],['Aerodynamic power',fmt(p.drag.power_aero_w,2)+' W'],['Wing Reynolds number',fmt(p.drag.re_wing,0)]])}</div>`;
  root.querySelectorAll('[data-duration]').forEach(b=>b.onclick=()=>{duration=Number(b.dataset.duration);rerenderView();});socChart('energy-soc',[current],duration);
  const c=colors();chart('energy-power','line',[line('Solar to bus',e.hours,e.p_solar,c.green),line('Bus load',e.hours,e.p_load,c.graph2)],{yLabel:'Power (W)',xLabel:'Elapsed hours · 08:00 start',min:0,xMax:duration});
  const parts=Object.entries(p.drag.parts_n);chart('drag-chart','bar',[{label:'Drag',data:parts.map(x=>x[1]),backgroundColor:c.blue,maxBarThickness:32}],{labels:parts.map(x=>x[0].replaceAll('_',' ')),yLabel:'Drag (N)',min:0,legend:false});
}

function requirements(){const p=data(),checks=p.review.checks;const pass=checks.filter(c=>c.status==='pass').length,fail=checks.filter(c=>c.status==='fail').length;
  const shown=checks.filter(c=>checkFilter==='all'||(checkFilter==='open'?c.status==='not_evaluated':c.status===checkFilter));
  root.innerHTML=heading('Requirements & margins',`${pass} modeled checks pass · ${fail} fail · structural assessment remains open`)+
    `<div class="controls-row status-filters"><div class="segmented" aria-label="Requirement status">${[['all','All checks'],['pass','Pass'],['fail','Fail'],['open','Not evaluated']].map(([id,title])=>`<button data-filter="${id}" aria-pressed="${id===checkFilter}">${title}</button>`).join('')}</div></div>
    <div class="table-scroll"><table class="check-table"><thead><tr><th>Requirement</th><th class="num">Limit</th><th class="num">Calculated</th><th class="num">Headroom</th><th class="num">Status</th></tr></thead><tbody>${shown.map(c=>`<tr><td>${c.label}${c.note?`<details><summary>Basis</summary><p>${esc(c.note)}${c.tolerance?` Tolerance: ${c.tolerance} ${c.unit}.`:''}</p></details>`:''}</td><td class="num">${threshold(c)}</td><td class="num">${actual(c)}</td><td class="num ${c.status==='fail'?'bad':c.headroom>0?'good':'neutral'}">${headroom(c)}</td><td class="num">${statusBadge(c.status)}</td></tr>`).join('')}</tbody></table>${shown.length?'':'<div class="empty">No checks in this category.</div>'}</div>
    <div class="callout">${icon('info')}<span>Headroom is calculated minus minimum, or maximum minus calculated, in the stated units. It is not a structural factor-of-safety margin. Negative recovery within numerical tolerance is displayed explicitly.</span></div>
    <div class="section-band two-columns">${section('Mission acceptance',[['Morning condition','Next morning ≥ current morning'],['Reserve condition','Minimum scored SOC ≥ 20%'],['Objective','Maximize lower of both morning SOCs'],['Visualization','89 h, separate from scored cycle']])}
      ${section('Review scope',[['Active yaw authority',p.metrics.n_motors===1?'Conventional rudder':'Differential thrust'],['Passive yaw thresholds',p.review.inputs.REQUIRE_YAW_STABILITY?'Enabled':'Disabled'],['Structural strength','Not evaluated'],['Buckling & aeroelasticity','Not evaluated'],['Flight approval','Not established by this study']])}</div>`;
  root.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{checkFilter=b.dataset.filter;rerenderView();});
}

const INPUT_UNITS={LATITUDE_DEG:'deg',LONGITUDE_DEG:'deg',SITE_ALTITUDE_M:'m MSL',CRUISE_ALT_AGL_M:'m AGL',MTOW_MAX_KG:'kg',WINGSPAN_MAX_M:'m',CLIMB_RATE_REQ_MS:'m/s',ROLL_RATE_MIN_DEG_S:'deg/s',YAW_RATE_MIN_DEG_S:'deg/s',PACK_ENERGY_WH:'Wh',PACK_CAPACITY_AH:'Ah',PACK_MASS_KG:'kg',PACK_CHARGE_MAX_A:'A',PACK_R_INTERNAL_OHM:'ohm',MPPT_MASS_KG:'kg',MPPT_MAX_INPUT_A:'A',MPPT_MAX_PV_VOC_V:'V',MPPT_MAX_PV_ABS_V:'V',MPPT_MAX_PANEL_W:'W',CELL_MASS_KG:'kg'};
function sources(){const p=data(),r=p.review,v=r.provenance;
  root.innerHTML=heading('Model & sources','Result lineage, assumptions and unresolved engineering risks.')+
    `<div class="two-columns"><section>${sectionHead('Result provenance',statusBadge('pass','Recomputed'))}${kv([['Search method',v.method==='surrogate'?'AeroSandbox / IPOPT surrogate':v.method],['Run completed',v.run_completed_utc?new Date(v.run_completed_utc).toLocaleString():'Unrecorded'],['Search seed',v.seed??'Unrecorded'],['Retained / passing candidates',`${v.candidates??'—'} / ${v.passing??'—'}`],['Exact evaluations',v.exact_evaluations??'Unrecorded'],['Search morning SOC',pct(v.search_soc,6)],['Recomputed morning SOC',pct(v.recomputed_soc,6)],['Difference',finite(v.difference_pp)?v.difference_pp.toExponential(3)+' pp':'Unrecorded']])}
      <div class="source-list"><div class="source-item"><h3>Source candidates</h3><div class="source-path">${esc(v.source_csv)}</div></div><div class="source-item"><h3>Candidate file · SHA-256</h3><div class="source-path">${esc(v.source_sha256)}</div></div><div class="source-item"><h3>Recomputed model source · SHA-256</h3><div class="source-path">${esc(v.model_sha256)}</div></div><div class="source-item"><h3>Run manifest</h3><div class="source-path">${esc(v.manifest_path)}</div></div></div></section>
    <section>${sectionHead('Assumptions & open items',`${r.warnings.length} items`)}<ul class="warning-list">${r.warnings.map(w=>`<li>${icon('triangle-alert')}<span>${esc(w)}</span></li>`).join('')}</ul><div class="callout">${icon('lock-keyhole')}<span>Read-only snapshot. Configuration selection does not rerun the optimizer. No local CAD edits are used as calculated results.</span></div></section></div>
    <div class="section-band">${sectionHead('Model inputs','',`<input id="input-search" type="search" class="search-input" placeholder="Filter model inputs" aria-label="Filter model inputs">`)}<div class="table-scroll"><table class="assumption-table"><thead><tr><th>Parameter</th><th class="num">Input value</th><th>Unit / type</th></tr></thead><tbody id="inputs-body"></tbody></table><div id="no-inputs" class="empty" hidden>No matching inputs.</div></div></div>
    <div class="section-band">${sectionHead('Search geometry bounds','Manifest snapshot')}<div class="table-scroll"><table class="assumption-table"><thead><tr><th>Variable</th><th class="num">Lower</th><th class="num">Upper</th><th class="num">Start</th><th>State</th></tr></thead><tbody>${Object.entries(v.bounds).map(([k,b])=>`<tr><td>${esc(k)}</td><td class="num">${fmt(b[0],4)}</td><td class="num">${fmt(b[1],4)}</td><td class="num">${fmt(b[2],4)}</td><td>${b[0]===b[1]?'Fixed':v.active_geometry.includes(k)?'Optimized':'Not in search vector'}</td></tr>`).join('')}</tbody></table></div></div>`;
  function filter(){const q=document.getElementById('input-search').value.toLowerCase();const inputs=Object.entries(r.inputs).filter(([k])=>k.toLowerCase().includes(q));document.getElementById('inputs-body').innerHTML=inputs.map(([k,value])=>`<tr><td>${esc(k)}</td><td class="num">${esc(typeof value==='number'?String(Number(value.toPrecision(10))):value)}</td><td class="muted">${INPUT_UNITS[k]|| (typeof value==='boolean'?'boolean':typeof value==='number'?'dimensionless':'identifier')}</td></tr>`).join('');document.getElementById('no-inputs').hidden=inputs.length>0;}
  document.getElementById('input-search').oninput=filter;filter();
}

function mass(){charts=renderMass(root,data(),{heading,metric,sectionHead,icon,fmt,pct,esc,colors});}
const renderers={overview,compare,geometry,mass,energy,requirements,sources};
function rerenderView(){const scroll=window.scrollY;cleanup();renderers[view]();icons();window.scrollTo({top:scroll});}
function render(){
  cleanup();const p=data();window.DATA=p;window.MESH=CONFIGS[current];window.currentCfg=current;window.currentView=view;
  document.getElementById('navigation').innerHTML=NAV.map(([id,title,ico])=>`<a href="?cfg=${current}&view=${id}" data-nav="${id}" class="${id===view?'active':''}" ${id===view?'aria-current="page"':''} title="${title}">${icon(ico)}<span class="nav-label">${title}</span>${id==='compare'?'<span class="nav-count">8</span>':''}</a>`).join('');
  document.querySelectorAll('[data-nav]').forEach(a=>a.onclick=e=>{e.preventDefault();navigate(a.dataset.nav);});
  document.getElementById('crumb').textContent=NAV.find(n=>n[0]===view)[1];
  document.getElementById('config-select').innerHTML=META.layouts.map(l=>`<option value="${l.id}" ${CONFIGS[current].layout_id===l.id?'selected':''}>${esc(NAMES[l.id])}</option>`).join('');
  document.getElementById('battery-options').innerHTML=META.batteries.map(b=>`<button data-battery="${b.id}" aria-pressed="${CONFIGS[current].battery_id===b.id}">${b.label}</button>`).join('');
  document.querySelectorAll('[data-battery]').forEach(b=>b.onclick=()=>choose(CONFIGS[current].layout_id+'__'+b.dataset.battery));
  document.getElementById('context-status').innerHTML=statusBadge(p.study.passed?'pass':'fail',p.study.passed?'Model feasible':'Not feasible')+'<small>Structural review outstanding</small>';
  document.getElementById('footer-source').textContent=`Snapshot · ${p.review.provenance.source_name} · ${p.review.provenance.source_sha256?.slice(0,10)||'unrecorded'}`;
  document.getElementById('snapshot-date').textContent=new Date(META.built_utc).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});
  renderers[view]();icons();document.title=`AircraftView · ${NAMES[CONFIGS[current].layout_id]} · ${p.combo.battery_label}`;
}
document.getElementById('config-select').onchange=e=>choose(e.target.value+'__'+CONFIGS[current].battery_id);
document.querySelector('.brand').onclick=e=>{e.preventDefault();navigate('overview');};
document.documentElement.dataset.theme=localStorage.getItem('engineering-view-theme')||'light';
function themeIcon(){document.getElementById('theme-toggle').innerHTML=icon(document.documentElement.dataset.theme==='dark'?'sun':'moon');icons();}
document.getElementById('theme-toggle').onclick=()=>{const next=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=next;localStorage.setItem('engineering-view-theme',next);document.dispatchEvent(new Event('review-theme'));rerenderView();themeIcon();};
const exportButton=document.getElementById('export-toggle'),menu=document.getElementById('export-menu');
exportButton.onclick=()=>{menu.hidden=!menu.hidden;exportButton.setAttribute('aria-expanded',String(!menu.hidden));};
document.addEventListener('click',e=>{if(!e.target.closest('.export-wrap')){menu.hidden=true;exportButton.setAttribute('aria-expanded','false');}});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){menu.hidden=true;exportButton.setAttribute('aria-expanded','false');}});
function download(name,content,type){const url=URL.createObjectURL(content instanceof Blob?content:new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('Export prepared.');}
document.querySelectorAll('[data-export]').forEach(b=>b.onclick=()=>{
  if(b.dataset.export==='json')download(current+'.json',JSON.stringify({configuration:current,built_utc:META.built_utc,schema_version:META.schema_version,result:data()},null,2),'application/json');
  if(b.dataset.export==='stl')download(current+'.stl',new Blob([Uint8Array.from(atob(CONFIGS[current].struct),c=>c.charCodeAt(0))],{type:'model/stl'}));
  if(b.dataset.export==='csv'){
    const ids=comparisonIds();const rows=[['Metric','Unit',...ids.map(label)],...METRICS.filter(m=>!m.section).map(m=>[m.name,m.unit,...ids.map(id=>m.get(CONFIGS[id].payload))])];
    rows.push(['Snapshot built','UTC',...ids.map(()=>META.built_utc)],['Source CSV','path',...ids.map(id=>CONFIGS[id].payload.review.provenance.source_csv)],['Source SHA-256','hash',...ids.map(id=>CONFIGS[id].payload.review.provenance.source_sha256)]);
    download('aircraft-comparison.csv',rows.map(r=>r.map(v=>'"'+String(v??'').replaceAll('"','""')+'"').join(',')).join('\n'),'text/csv');
  }
  menu.hidden=true;exportButton.setAttribute('aria-expanded','false');
});
window.addEventListener('popstate',()=>{const q=new URLSearchParams(location.search);if(IDS.includes(q.get('cfg')))current=q.get('cfg');if(NAV.some(n=>n[0]===q.get('view')))view=q.get('view');render();});
syncURL(true);render();themeIcon();
