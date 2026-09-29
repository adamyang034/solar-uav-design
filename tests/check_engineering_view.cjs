const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const sharp = require('sharp');

async function main() {
  const [url, out] = process.argv.slice(2);
  assert(url && out, 'Usage: node check_engineering_view.cjs URL OUTPUT_DIR');
  await fs.mkdir(out, {recursive:true});
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  const report = {cases:[],exports:[],viewports:[],errors:[]};
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    page.on('pageerror',e=>report.errors.push(e.message));
    page.on('response',r=>{if(r.status()>=400)report.errors.push(`${r.status()} ${r.url()}`);});
    await page.goto(url);
    await page.waitForSelector('#cad canvas');
    const cases=await page.evaluate(()=>META.comboOrder);
    assert.deepEqual(cases,['pi_tail__gold_v1','split__gold_v1','conventional__gold_v1','conventional_rectangular__gold_v1','conventional_rectangular_solar__gold_v1']);
    assert.equal(await page.locator('.snapshot-label').innerText(),'5 configurations');
    assert.equal(await page.locator('.nav-count').innerText(),'5');
    assert.equal(await page.locator('[data-battery="6s_36ah"]').count(),0);
    async function nav(view) {
      await page.locator(`[data-nav="${view}"]`).click();
      await page.waitForFunction(v=>window.currentView===v,view);
    }
    async function noOverflow() {
      const dimensions=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,width:innerWidth}));
      assert(dimensions.scroll<=dimensions.width+1,JSON.stringify(dimensions));
    }
    async function canvasCheck(tag, orbit=false) {
      const canvas=page.locator('#cad canvas');
      await canvas.scrollIntoViewIfNeeded();
      await page.waitForTimeout(180);
      const image=await canvas.screenshot();
      const {data,info}=await sharp(image).removeAlpha().raw().toBuffer({resolveWithObject:true});
      let solar=0;
      for(let i=0;i<data.length;i+=info.channels)if(data[i+2]>data[i]+15&&data[i+2]>data[i+1]+5)solar++;
      assert(solar>100,`${tag}: missing solar-colored CAD pixels (${solar})`);
      if(orbit){
        const b=await canvas.boundingBox();
        await page.mouse.move(b.x+b.width*.55,b.y+b.height*.55);
        await page.mouse.down();await page.mouse.move(b.x+b.width*.55+65,b.y+b.height*.55+25,{steps:8});await page.mouse.up();
        await page.waitForTimeout(180);
        assert(!image.equals(await canvas.screenshot()),`${tag}: orbit did not change image`);
      }
      return solar;
    }
    async function checkCharts() {
      const results=await page.evaluate(()=>Object.values(Chart.instances).map(ch=>({
        id:ch.canvas.id,points:ch.getDatasetMeta(0).data.map(p=>[p.x,p.y]),
      })));
      for(const c of results){assert(c.points.length>0,c.id);assert(c.points.every(p=>p.every(Number.isFinite)),`${c.id}: nonfinite chart pixels`);}
    }
    for(const id of cases){
      const [layout,battery]=id.split('__');
      await page.locator('#config-select').selectOption(layout);
      await page.locator(`[data-battery="${battery}"]`).click();
      await page.waitForFunction(id=>currentCfg===id,id);
      const d=await page.evaluate(()=>({energy:DATA.energy,study:DATA.study,dims:DATA.dims,review:DATA.review}));
      assert.equal(d.energy.plot_duration_h,89);assert.equal(d.energy.hours.at(-1),89);
      assert.equal(d.energy.hours.length,d.energy.soc.length);assert(d.energy.soc.every(Number.isFinite));
      assert.equal(d.review.checks.filter(c=>c.status==='fail').length,0);
      assert.equal(d.review.checks.find(c=>c.id==='structure').status,'not_evaluated');
      const roll=d.review.checks.find(c=>c.id==='roll');
      assert.equal(roll.limit,20);assert.equal(roll.status,'pass');
      assert.equal(d.review.inputs.ROLL_RATE_MIN_DEG_S,20);
      const minimumChord=d.review.checks.find(c=>c.id==='minimum_chord');
      if(layout==='conventional_rectangular_solar'){
        assert.equal(minimumChord.limit,310);assert.equal(minimumChord.status,'pass');
        assert(d.dims.chord_m>=.310-1e-9);
        assert.equal(d.review.inputs.RECTANGULAR_MIN_CHORD_M,.310);
      }else{assert.equal(minimumChord,undefined);}
      assert.equal(d.review.provenance.source_sha256.length,64);
      const setback=d.review.checks.find(c=>c.id==='solar_setback');
      assert.equal(setback.limit,40);
      assert.equal(setback.status,'pass');
      assert(setback.actual>=40);
      assert.equal(d.review.inputs.WING_SOLAR_LE_SETBACK_M,.04);
      const packing=await page.evaluate(()=>({cells:DATA.cells,n:DATA.metrics.n_cells}));
      assert.equal(packing.cells.length,packing.n);
      assert(packing.cells.filter(c=>c.bay.startsWith('wing_')).every(c=>c.x0>=.04));
      if(layout==='conventional'||layout==='conventional_rectangular'){
        assert.equal(d.review.inputs.SOLAR_ALLOW_AILERON_OVERLAP,false);
        assert.equal(d.dims.cells_on_aileron,false);
        const gate=d.review.checks.find(c=>c.id==='solar_aileron');
        assert.equal(gate.actual,0);assert.equal(gate.limit,0);assert.equal(gate.status,'pass');
        const chord=y=>y<=d.dims.y_taper_m?d.dims.chord_m:d.dims.chord_m+(d.dims.tip_chord_m-d.dims.chord_m)*(y-d.dims.y_taper_m)/(d.dims.span_m/2-d.dims.y_taper_m);
        for(const c of packing.cells.filter(c=>c.bay.startsWith('wing_'))){
          for(const y of [Math.abs(c.y0),Math.abs(c.y1)]){
            if(y>=d.dims.aileron_y_inner_m-1e-9)assert(c.x1<=chord(y)*(1-d.dims.aileron_chord_frac)+1e-9,`${id}: cell overlaps aileron`);
          }
        }
      }
      assert(Math.abs(d.study.morning_soc_difference_pp)<1e-6);
      if(layout.startsWith('conventional_rectangular')){assert.equal(d.dims.taper_ratio,1);assert.equal(d.dims.washout_tip_deg,0);assert.equal(d.dims.tip_chord_m,d.dims.chord_m);const allowed=layout.endsWith('_solar');assert.equal(d.review.inputs.SOLAR_ALLOW_AILERON_OVERLAP,allowed);assert.equal(d.dims.cells_on_aileron,allowed);}
      await nav('overview');const solarPixels=await canvasCheck(id,true);
      const hw=await page.evaluate(()=>({packs:DATA.metrics.n_packs,ah:DATA.metrics.n_packs*DATA.combo.pack_ah,wh:DATA.metrics.pack_wh,cells:DATA.metrics.n_cells}));
      assert((await page.locator('[data-overview="packs"]').innerText()).startsWith(hw.packs+' ×'));
      assert.equal(await page.locator('[data-overview="capacity"]').innerText(),hw.ah.toFixed(2)+' Ah');
      assert.equal(await page.locator('[data-overview="energy"]').innerText(),hw.wh.toLocaleString('en-US',{maximumFractionDigits:0})+' Wh');
      assert.equal(await page.locator('[data-overview="solar"]').innerText(),hw.cells+' cells');
      await page.screenshot({path:path.join(out,id+'.png'),fullPage:true});
      for(const view of ['geometry','mass','energy','requirements','sources','compare']){
        await nav(view);await checkCharts();await noOverflow();
        if(view==='geometry')await canvasCheck(id+' geometry');
        if(view==='energy'){
          const pie=await page.evaluate(()=>({type:Chart.getChart('drag-chart').config.type,values:Chart.getChart('drag-chart').data.datasets[0].data,total:DATA.drag.drag_total_n,cells:DATA.metrics.n_cells}));
          assert.equal(pie.type,'doughnut');
          assert.equal(pie.values.length,8);
          assert(Math.abs(pie.values.reduce((a,b)=>a+b,0)-pie.total)<1e-9);
          assert.equal(await page.locator('#drag-parts tbody tr').count(),9);
          if(layout==='conventional_rectangular_solar'){
            assert.equal(pie.cells,88);
            await page.locator('#drag-chart').locator('xpath=ancestor::div[contains(@class,"section-band")]').screenshot({path:path.join(out,'drag-buildup.png')});
          }
        }
      }
      report.cases.push({id,solarPixels,morning_soc:d.energy.objective_soc,passed:d.study.passed});
    }
    await page.getByRole('button',{name:'All 5',exact:true}).click();
    assert.equal(await page.locator('[data-compare-case]:checked').count(),5);
    await page.locator('#baseline-select').selectOption('conventional__gold_v1');
    await page.getByRole('button',{name:'Deltas',exact:true}).click();
    const socRow=page.locator('.compare-table tr').filter({has:page.locator('td:first-child',{hasText:/^Morning SOC$/})});
    const expectedDelta=await page.evaluate(()=>100*(CONFIGS.conventional_rectangular__gold_v1.payload.energy.objective_soc-CONFIGS.conventional__gold_v1.payload.energy.objective_soc));
    const rectangularColumn=cases.indexOf('conventional_rectangular__gold_v1')+2;
    const renderedDelta=Number.parseFloat(await socRow.locator('td').nth(rectangularColumn).innerText());
    assert(Math.abs(renderedDelta-expectedDelta)<.0051);
    await page.getByRole('button',{name:'Both',exact:true}).click();
    await page.screenshot({path:path.join(out,'comparison-desktop.png'),fullPage:true});
    await nav('requirements');
    await page.getByRole('button',{name:'Not evaluated',exact:true}).click();
    assert.equal(await page.locator('.check-table tbody tr').count(),1);
    await page.getByRole('button',{name:'Fail',exact:true}).click();
    assert(await page.getByText('No checks in this category.').isVisible());
    await page.getByRole('button',{name:'All checks',exact:true}).click();
    await page.screenshot({path:path.join(out,'requirements-desktop.png'),fullPage:true});
    await nav('sources');
    await page.getByRole('searchbox').fill('PACK_MASS');
    assert.equal(await page.locator('#inputs-body tr').count(),1);
    await page.getByRole('searchbox').fill('');
    for(const kind of ['json','csv','stl']){
      await page.locator('#export-toggle').click();
      const [download]=await Promise.all([page.waitForEvent('download'),page.locator(`[data-export="${kind}"]`).click()]);
      const file=path.join(out,download.suggestedFilename());await download.saveAs(file);
      const bytes=await fs.readFile(file);assert(bytes.length>100);
      if(kind==='json'){const obj=JSON.parse(bytes);assert(obj.result.review.provenance.source_sha256);assert.equal(obj.configuration,'conventional_rectangular_solar__gold_v1');}
      if(kind==='csv'){assert(bytes.toString().includes('Source SHA-256'));assert(bytes.toString().includes('Morning SOC'));}
      report.exports.push({kind,bytes:bytes.length});
    }
    await nav('overview');await page.locator('#theme-toggle').click();
    await canvasCheck('dark');await page.screenshot({path:path.join(out,'overview-dark.png'),fullPage:true});
    await page.locator('#theme-toggle').click();
    for(const width of [1920,1024,768,390]){
      await page.setViewportSize({width,height:width===390?844:1080});
      for(const view of ['overview','compare','geometry','mass','energy','requirements','sources']){
        await nav(view);await noOverflow();await checkCharts();
        if(view==='overview'||view==='geometry')await canvasCheck(`${width} ${view}`);
        if(width===390||view==='overview')await page.screenshot({path:path.join(out,`${view}-${width}.png`),fullPage:true});
      }
      report.viewports.push(width);
    }
    await page.setViewportSize({width:1440,height:1050});
    await nav('overview');
    await page.locator('[data-camera="top"]').click();
    await page.screenshot({path:path.join(out,'cad-top.png'),fullPage:true});
    await page.locator('[data-settings]').click();
    await page.locator('[data-layer="cells"]').uncheck();
    assert.equal(await page.locator('[data-layer="cells"]').isChecked(),false);
    await page.locator('[data-layer="cells"]').check();
    await page.reload();await page.waitForSelector('#cad canvas');
    assert.equal(await page.evaluate(()=>currentCfg),'conventional_rectangular_solar__gold_v1');
    assert.deepEqual(report.errors,[]);
    console.log(JSON.stringify(report,null,2));
  } finally {await fs.writeFile(path.join(out,'browser-checks.json'),JSON.stringify(report,null,2));await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
