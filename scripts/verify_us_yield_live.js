async (page) => {
  // Verify the actual loaded service, never an intercepted or mocked API.
  const receipt={mode:'live_production',url:page.url(),checked_at:new Date().toISOString(),checks:{},errors:[]};
  const prefix='us-yield-live-'+new Date().toISOString().replace(/[^0-9]/g,'');
  page.on('pageerror',error=>receipt.errors.push(error.message));
  const check=(name,condition,detail)=>{
    receipt.checks[name]={pass:Boolean(condition),detail};
    if(!condition)throw new Error(name+': '+JSON.stringify(detail));
  };
  await page.reload();
  await page.locator('.section').first().waitFor({timeout:60000});
  await page.setViewportSize({width:1440,height:1000});
  const payload=await (await page.request.get('http://127.0.0.1:5001/api/us-macro/data')).json();
  check('loaded_68_series',payload.data_quality.registered_series===68,payload.data_quality.registered_series);
  check('eleven_tenors',payload.yield_curve_tenors.length===11,payload.yield_curve_tenors);
  const snapshot=page.locator('.chart').filter({has:page.locator('.chart-title').filter({hasText:'最近完整同日名义国债收益率曲线'})});
  const lastFull=payload.yield_curve_snapshots.filter(row=>Object.keys(row.values).length===11).at(-1);
  const content=await snapshot.innerText();
  check('complete_real_same_day',content.includes(lastFull.period)&&content.includes('11/11'),{period:lastFull.period,text:content});
  const labels=await snapshot.locator('svg text').allTextContents();
  check('maturity_axis',payload.yield_curve_tenors.every(({label})=>labels.includes(label)),labels);
  await snapshot.scrollIntoViewIfNeeded();
  await snapshot.screenshot({path:`output/playwright/${prefix}.png`});
  await page.getByRole('textbox',{name:'截止月份'}).fill('2026-08');
  check('selected_period_bounds_snapshot',!(await snapshot.innerText()).includes(lastFull.period),'End month 2026-08 excludes the October observation');
  check('no_page_errors',receipt.errors.length===0,receipt.errors);
  receipt.screenshot=`output/playwright/${prefix}.png`;receipt.status='passed';
  return receipt;
}
