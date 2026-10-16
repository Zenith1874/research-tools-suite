async (page) => {
  const receipt={mode:'live_production',url:page.url(),checked_at:new Date().toISOString(),checks:{},errors:[]};
  const prefix='bank-history-'+new Date().toISOString().replace(/[^0-9]/g,'');
  page.on('pageerror',error=>receipt.errors.push(error.message));
  const check=(name,condition,detail)=>{
    receipt.checks[name]={pass:Boolean(condition),detail};
    if(!condition)throw new Error(name+': '+JSON.stringify(detail));
  };
  await page.reload();await page.locator('.tabs').waitFor({timeout:60000});
  await page.setViewportSize({width:1440,height:1000});
  await page.locator('.tabs').getByRole('button',{name:'银行风险',exact:true}).click();
  await page.getByRole('button',{name:'全部',exact:true}).click();
  const payload=await (await page.request.get('http://127.0.0.1:5001/api/china-macro/data')).json();
  const npl=payload.series.CN_BANK_NPL_RATIO;
  check('live_history_22_quarters',npl.length===22&&npl[0].period==='2021-03'&&npl.at(-1).period==='2026-06',npl.map(row=>row.period));
  check('undisclosed_nsfr_absent',payload.series.CN_BANK_NSFR.length===10&&payload.series.CN_BANK_NSFR[0].period==='2024-03','No synthesized 2022/2023 NSFR');
  check('dynamic_scope_label',(await page.locator('.section-head').innerText()).includes('2021-03—2026-06'),await page.locator('.section-head').innerText());
  const capital=page.locator('.chart-grid .chart').filter({has:page.locator('.chart-title').filter({hasText:'商业银行资本充足率'})});
  check('new_rules_marker',await capital.locator('.method-break[data-period="2024-03"]').count()===1,'Capital rules transition');
  const paths=await capital.locator('.series-segment').evaluateAll(items=>items.map(item=>({start:item.dataset.start,end:item.dataset.end})));
  check('capital_not_spliced',paths.length===6&&paths.every(row=>!(row.start<'2024-03'&&row.end>='2024-03')),paths);
  await capital.screenshot({path:`output/playwright/${prefix}-capital.png`});
  check('no_page_errors',receipt.errors.length===0,receipt.errors);
  receipt.screenshot=`output/playwright/${prefix}-capital.png`;receipt.status='passed';return receipt;
}
