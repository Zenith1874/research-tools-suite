async (page) => {
  const receipt={mode:'live_production',url:page.url(),checked_at:new Date().toISOString(),checks:{},errors:[]};
  const stamp=new Date().toISOString().replace(/[^0-9]/g,'');
  page.on('pageerror',error=>receipt.errors.push(error.message));
  const check=(name,condition,detail)=>{
    receipt.checks[name]={pass:Boolean(condition),detail};
    if(!condition)throw new Error(name+': '+JSON.stringify(detail));
  };
  await page.reload();await page.locator('.tabs').waitFor({timeout:60000});
  await page.setViewportSize({width:1440,height:1050});
  await page.locator('.tabs').getByRole('button',{name:'外资与跨境资金',exact:true}).click();
  await page.getByRole('button',{name:'全部',exact:true}).click();
  const payload=await (await page.request.get('http://127.0.0.1:5001/api/china-macro/data')).json();
  const annual=payload.series.CN_MOFCOM_FDI_USD_ANNUAL;
  const firms=payload.series.CN_MOFCOM_FDI_NEW_FIRMS_ANNUAL;
  check('annual_raw_values',annual.length===43&&annual[0].period==='1983'&&annual.at(-1).period==='2025'&&
    annual.at(-1).value===1046.6&&firms.length===43&&firms.at(-1).value===70392&&
    annual.every(row=>row.frequency==='annual'),{n:annual.length,start:annual[0].period,end:annual.at(-1)});
  check('annual_not_spliced_into_old_monthly',annual.find(row=>row.period==='2021').value===1809.6&&
    payload.series.CN_MOFCOM_FDI_USD_YTD.find(row=>row.period==='2021-12').value===1734.8,
    '2021 annual all-sector 1809.6 versus old nonfinancial monthly 1734.8 retained separately.');
  const money=page.locator('.chart-grid .chart').filter({has:page.locator('.chart-title').filter({hasText:'实际使用外资长期历史（公报年度，美元）'})});
  const company=page.locator('.chart-grid .chart').filter({has:page.locator('.chart-title').filter({hasText:'新设外商投资企业长期历史（公报年度）'})});
  const paths=await money.locator('.series-segment[data-series="CN_MOFCOM_FDI_USD_ANNUAL"]').evaluateAll(items=>
    items.map(item=>({start:item.dataset.start,end:item.dataset.end,d:item.getAttribute('d')})));
  check('annual_full_history_visible',paths.length===1&&paths[0].start==='1983'&&paths[0].end==='2025'&&paths[0].d.length>100,
    paths.map(({d,...item})=>item));
  const ticks=await money.locator('svg text').allTextContents();
  check('gross_amount_axis_not_negative',!ticks.some(text=>/^\s*-\d/.test(text)),ticks);
  await money.screenshot({path:`output/playwright/fdi-${stamp}-annual-money.png`});
  await company.screenshot({path:`output/playwright/fdi-${stamp}-annual-firms.png`});
  check('corrected_reporting_years',payload.series.CN_MOFCOM_FDI_CNY_YTD.find(row=>row.period==='2022-12').value===12326.8&&
    payload.series.CN_MOFCOM_FDI_CNY_YTD.find(row=>row.period==='2023-12').value===11339.1,
    '2022/2023 CNY year-end observations match their original releases.');
  await page.getByRole('button',{name:'美元',exact:true}).click();
  check('annual_unit_stays_usd',await money.locator('.chart-head > .chart-sub').innerText()==='单位：亿美元',await money.locator('.chart-head > .chart-sub').innerText());
  const monthly=page.locator('.chart-grid .chart').filter({has:page.locator('.chart-title').filter({hasText:/^实际使用外资与非金融类对外投资累计$/})});
  check('may2022_scope_marker',await monthly.locator('.method-break[data-period="2022-05"]').count()===1,'Original money scope change.');
  const monthlyPaths=await monthly.locator('.series-segment[data-series="CN_MOFCOM_FDI_USD_YTD"]').evaluateAll(items=>
    items.map(item=>({start:item.dataset.start,end:item.dataset.end})));
  check('fdi_not_bridged_over_scope_change',monthlyPaths.every(item=>!(item.start<'2022-05'&&item.end>='2022-05')),monthlyPaths);
  await page.getByRole('button',{name:'3年',exact:true}).click();
  const shortStart=await money.locator('.series-segment').getAttribute('data-start');
  check('annual_period_control',shortStart>'1983',shortStart);
  await page.getByRole('button',{name:'全部',exact:true}).click();
  const downloadEvent=page.waitForEvent('download');
  await page.getByRole('button',{name:'导出当前板块 CSV',exact:true}).click();
  const download=await downloadEvent;
  receipt.csv=`output/playwright/fdi-${stamp}-capital-usd.csv`;
  await download.saveAs(receipt.csv);
  await page.setViewportSize({width:430,height:950});
  await page.waitForFunction(()=>{
    const chart=[...document.querySelectorAll('.chart-grid .chart')].find(item=>item.querySelector('.chart-title')?.textContent.includes('实际使用外资长期历史（公报年度，美元）'));
    const svg=chart?.querySelector('svg');
    return svg&&Math.abs(svg.getBoundingClientRect().width-svg.viewBox.baseVal.width)<4;
  });
  await money.screenshot({path:`output/playwright/fdi-${stamp}-annual-narrow.png`});
  const fontSize=await money.locator('svg').evaluate(svg=>{
    const rect=svg.getBoundingClientRect(),box=svg.viewBox.baseVal;
    return Math.min(...[...svg.querySelectorAll('text')].map(text=>parseFloat(getComputedStyle(text).fontSize)*Math.min(rect.width/box.width,rect.height/box.height)));
  });
  check('narrow_axis_labels_readable',fontSize>=11,{effective_minimum_px:fontSize});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2);
  check('narrow_layout_without_page_overflow',!overflow,{viewport:430,overflow});
  check('no_page_errors',receipt.errors.length===0,receipt.errors);
  receipt.screenshots=[`output/playwright/fdi-${stamp}-annual-money.png`,
    `output/playwright/fdi-${stamp}-annual-firms.png`,`output/playwright/fdi-${stamp}-annual-narrow.png`];
  receipt.status='passed';return receipt;
}
