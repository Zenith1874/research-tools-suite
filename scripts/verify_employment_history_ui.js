async (page) => {
  const receipt={mode:'live_production',url:page.url(),checked_at:new Date().toISOString(),checks:{},errors:[]};
  const prefix='employment-history-'+new Date().toISOString().replace(/[^0-9]/g,'');
  page.on('pageerror',error=>receipt.errors.push(error.message));
  const check=(name,condition,detail)=>{
    receipt.checks[name]={pass:Boolean(condition),detail};
    if(!condition)throw new Error(name+': '+JSON.stringify(detail));
  };
  await page.reload();await page.locator('.tabs').waitFor({timeout:60000});
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('.tabs').getByRole('button',{name:/就业.*收入/}).click();
  await page.getByRole('button',{name:'全部',exact:true}).click();
  const payload=await (await page.request.get('http://127.0.0.1:5001/api/china-macro/data')).json();
  const rows=payload.series.CN_UNEMP_SURVEY;
  check('104_actual_months',rows.length===104&&rows[0].period==='2018-01'&&rows.at(-1).period==='2026-08',
    {n:rows.length,start:rows[0].period,end:rows.at(-1).period});
  const monthIndex=period=>Number(period.slice(0,4))*12+Number(period.slice(-2));
  check('continuous_calendar_without_synthetic_rows',rows.every((row,index)=>Number.isFinite(row.value)&&
    row.source_url&&['official','official_relayed'].includes(row.data_status)&&
    (index===0||monthIndex(row.period)-monthIndex(rows[index-1].period)===1)),
    'Each period has an actual official-source rate; no allocation or interpolation.');
  const chart=page.locator('.chart-grid .chart').filter({has:page.locator('.chart-title')
    .filter({hasText:'全国城镇调查失业率'})});
  const paths=await chart.locator('.series-segment[data-series="CN_UNEMP_SURVEY"]')
    .evaluateAll(items=>items.map(item=>({start:item.dataset.start,end:item.dataset.end,d:item.getAttribute('d')})));
  check('full_history_rendered',paths.length===1&&paths[0].start==='2018-01'&&
    paths[0].end==='2026-08'&&paths[0].d.length>100,{paths:paths.map(({d,...rest})=>rest)});
  await chart.screenshot({path:`output/playwright/${prefix}-national.png`});
  await page.getByRole('button',{name:'3年',exact:true}).click();
  const narrowStart=await chart.locator('.series-segment[data-series="CN_UNEMP_SURVEY"]').getAttribute('data-start');
  check('period_control_still_works',narrowStart>'2018-01',narrowStart);
  check('no_page_errors',receipt.errors.length===0,receipt.errors);
  receipt.screenshot=`output/playwright/${prefix}-national.png`;receipt.status='passed';return receipt;
}
