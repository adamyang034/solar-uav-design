const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {chromium}=require('playwright');
const sharp=require('sharp');

async function main(){
  const [url,out]=process.argv.slice(2);await fs.mkdir(out,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'chrome'});
  const report={cases:[],errors:[]};
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1050}});
    page.on('pageerror',e=>report.errors.push(e.message));
    page.on('response',r=>{if(r.status()>=400)report.errors.push(`${r.status()} ${r.url()}`);});
    await page.goto(url);await page.waitForSelector('#mass-total-chart');
    const ids=await page.evaluate(()=>META.comboOrder);
    for(const id of ids){
      const [layout,battery]=id.split('__');
      await page.locator('#config-select').selectOption(layout);
      await page.locator(`[data-battery="${battery}"]`).click();
      await page.waitForFunction(id=>currentCfg===id,id);
      const stats=await page.evaluate(()=>({
        allocation:DATA.mass.allocation,
        charts:Object.values(Chart.instances).map(c=>({id:c.canvas.id,type:c.config.type,total:c.data.datasets[0].data.reduce((a,b)=>a+b,0),points:c.getDatasetMeta(0).data.map(p=>[p.x,p.y,p.outerRadius])})),
      }));
      assert.equal(stats.charts.length,stats.allocation.groups.length+1);
      assert(stats.charts.every(c=>c.type==='doughnut'&&c.points.every(p=>p.every(Number.isFinite))));
      assert(Math.abs(stats.charts.find(c=>c.id==='mass-total-chart').total-stats.allocation.total_kg)<1e-9);
      for(const g of stats.allocation.groups)assert(Math.abs(stats.charts.find(c=>c.id==='mass-pie-'+g.id).total-g.mass_kg)<1e-9);
      await page.locator('[data-mass-unit="g"]').click();
      assert.equal(await page.locator('[data-mass-unit="g"]').getAttribute('aria-pressed'),'true');
      const expected=(stats.allocation.total_kg*1000).toLocaleString('en-US',{minimumFractionDigits:1,maximumFractionDigits:1});
      assert((await page.locator('.mass-metrics .metric-value').first().innerText()).includes(expected));
      assert.equal(await page.evaluate(()=>Object.keys(Chart.instances).length),stats.allocation.groups.length+1);
      assert.equal(stats.allocation.groups.length,9);
      for(const id of ['wing','hstab','vstab','booms','fuselage'])assert(stats.allocation.groups.some(g=>g.id===id));
      for(const id of ['hstab','vstab']){
        const g=stats.allocation.groups.find(g=>g.id===id);
        assert(g.children.some(n=>n.label.includes('structure')));
        assert(g.children.some(n=>n.label.includes('interface')));
        assert(g.children.some(n=>n.id===id+'_servos'));
        assert(Math.abs(g.quantity*g.per_item_kg-g.mass_kg)<1e-9);
      }
      await page.locator('[data-mass-unit="kg"]').click();
      await page.locator('[data-expand-all="wing"]').click();
      assert(await page.locator('[data-node="wing_cell_material"]').isVisible());
      assert(await page.locator('[data-node="wing_cell_interconnects"]').isVisible());
      await page.locator('[data-mass-unit="g"]').click();
      assert.equal((await page.locator('[data-expand-all="wing"]').innerText()).trim(),'Collapse all');
      assert(await page.locator('[data-node="wing_cell_material"]').isVisible());
      await page.locator('[data-mass-unit="kg"]').click();
      await page.locator('[data-expand-all="wing"]').click();
      assert.equal((await page.locator('[data-expand-all="wing"]').innerText()).trim(),'Expand all');
      assert.equal(await page.locator('[data-node="wing_cell_material"]').count(),0);
      await page.locator('[data-jump="hstab"]').first().click();
      await page.waitForTimeout(500);
      assert.equal(await page.evaluate(()=>document.activeElement.closest('section').id),'mass-section-hstab');
      await page.screenshot({path:path.join(out,id+'.png'),fullPage:true});
      report.cases.push({id,total:stats.allocation.total_kg,groups:stats.allocation.groups.length});
    }
    await page.locator('#config-select').selectOption('conventional');
    await page.locator('[data-battery="gold_v1"]').click();
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:path.join(out,'mass-desktop-top.png')});
    await page.locator('#mass-section-hstab').screenshot({path:path.join(out,'hstab-detail.png')});
    await page.locator('#mass-section-vstab').screenshot({path:path.join(out,'vstab-detail.png')});
    const png=await page.locator('#mass-total-chart').screenshot();
    const channels=(await sharp(png).stats()).channels;
    assert(channels.some(c=>c.stdev>20),'blank pie');
    const point=await page.evaluate(()=>Chart.getChart('mass-total-chart').getDatasetMeta(0).data[0].getCenterPoint());
    await page.locator('#mass-total-chart').click({position:point});
    await page.waitForTimeout(500);
    assert((await page.evaluate(()=>document.activeElement.closest('section').id)).startsWith('mass-section-'));
    await page.locator('#theme-toggle').click();
    await page.evaluate(()=>scrollTo(0,0));
    await page.screenshot({path:path.join(out,'mass-dark.png')});
    await page.locator('#theme-toggle').click();
    for(const width of [1024,768,390]){
      await page.setViewportSize({width,height:844});
      await page.evaluate(()=>scrollTo(0,0));
      await page.waitForTimeout(150);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
      await page.screenshot({path:path.join(out,`mass-${width}.png`),fullPage:true});
      await page.locator('[data-expand="wing/wing_solar"]').click();
      await page.locator('#mass-section-wing').screenshot({path:path.join(out,`detail-${width}.png`)});
      await page.locator('[data-expand="wing/wing_solar"]').click();
    }
    await page.locator('[data-nav="overview"]').click();
    await page.waitForSelector('#cad canvas');
    assert.equal(await page.evaluate(()=>Object.keys(Chart.instances).length),1);
    await page.locator('[data-nav="mass"]').click();
    await page.reload();await page.waitForSelector('#mass-total-chart');
    assert.equal(await page.evaluate(()=>currentView),'mass');
    assert.deepEqual(report.errors,[]);
    console.log(JSON.stringify(report,null,2));
  }finally{await fs.writeFile(path.join(out,'mass-checks.json'),JSON.stringify(report,null,2));await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
