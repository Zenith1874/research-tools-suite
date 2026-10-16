async page => {
  // Verify actual production values and rendered survey discontinuities, never mocked data.
  const prefix = 'output/playwright/livelihood-live-' + new Date().toISOString().replace(/[^0-9]/g, '');
  const audit = {mode: 'live_production', checked_at: new Date().toISOString(), checks: [], errors: [], screenshots: [], exports: []};
  const check = (name, pass, detail) => {audit.checks.push({name, pass: Boolean(pass), detail}); if (!pass) throw new Error(name + ': ' + JSON.stringify(detail));};
  const chart = title => page.locator('.chart').filter({has: page.locator('.chart-title').filter({hasText: title})});
  const setRange = async (start, end) => {const months = page.locator('input[type=month]'); await months.nth(0).fill(start); await months.nth(1).fill(end);};
  const ready = async () => page.waitForFunction(() => [...document.querySelectorAll('.chart:has(.chart-svg)')].every(element => Math.abs(element.querySelector('svg').viewBox.baseVal.width - (element.clientWidth-24)) <= 2));
  const saveJson = async () => {
    const pending = page.waitForEvent('download');
    await page.evaluate(({name, text}) => {const link = document.createElement('a'); link.download = name; link.href = URL.createObjectURL(new Blob([text], {type: 'application/json'})); link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 1000);},
      {name: 'livelihood-acceptance.json', text: JSON.stringify(audit, null, 2) + '\n'});
    await (await pending).saveAs(prefix + '-audit.json');
  };
  const parseCsv = text => {
    const lines = []; let row = [], field = '', quoted = false;
    for (let i=0; i<text.length; i++) {const char=text[i]; if(char==='"'){if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted;}
      else if(char===','&&!quoted){row.push(field);field='';}else if(char==='\n'&&!quoted){row.push(field.replace(/\r$/,''));lines.push(row);row=[];field='';}else field+=char;}
    if(field||row.length){row.push(field.replace(/\r$/,''));lines.push(row);}
    lines[0][0]=lines[0][0].replace(/^\uFEFF/,'');return lines.slice(1).map(values=>Object.fromEntries(lines[0].map((name,index)=>[name,values[index]])));
  };
  page.on('pageerror', error => audit.errors.push(error.message));
  try {
    await page.setViewportSize({width:1440,height:1000});
    await page.goto('http://127.0.0.1:5001/china-macro'); await page.locator('.tabs').waitFor({timeout:45000});
    const response = await page.request.get('http://127.0.0.1:5001/api/china-macro/data');
    check('actual_api_200',response.status()===200,response.status());
    const payload=await response.json();
    const byYear={
      '2013':{CN_URBANIZATION_RATE:53.73},
      '2014':{CN_DEATHS:977,CN_URBAN_NEW_JOBS:1322,CN_CONSUMPTION_PC:14491,CN_INCOME_URBAN:28844,CN_INCOME_RURAL:10489,CN_MIGRANT_WORKERS:27395,CN_WORKING_AGE_POP:91583,CN_POP_60_PLUS:21242,CN_POP_65_PLUS:13755,CN_INCOME_REAL_YOY:8,CN_CONSUMPTION_REAL_YOY:7.5,CN_URBANIZATION_RATE:54.77,CN_DISPOSABLE_INCOME_MEDIAN:17570,CN_MIGRANT_MONTHLY_INCOME:2864},
      '2015':{CN_DEATHS:975,CN_URBAN_NEW_JOBS:1312,CN_CONSUMPTION_PC:15712,CN_DISPOSABLE_INCOME_MEDIAN:19281,CN_INCOME_URBAN:31195,CN_INCOME_RURAL:11422,CN_MIGRANT_WORKERS:27747,CN_MIGRANT_MONTHLY_INCOME:3072,CN_WORKING_AGE_POP:91096,CN_POP_60_PLUS:22200,CN_POP_65_PLUS:14386,CN_INCOME_REAL_YOY:7.4,CN_CONSUMPTION_REAL_YOY:6.9,CN_URBANIZATION_RATE:56.10}
    };
    const inspected=[];
    for(const [period,values] of Object.entries(byYear)) for(const [code,value] of Object.entries(values)) {
      const row=payload.series[code].find(row=>row.period===period);
      const yearend=period==='2014'&&['CN_DISPOSABLE_INCOME_MEDIAN','CN_MIGRANT_MONTHLY_INCOME'].includes(code);
      const released=yearend?'2015-01-20':{'2013':'2014-02-24','2014':'2015-02-26','2015':'2016-02-29'}[period];
      const id=yearend?'1898674':{'2013':'1898455','2014':'1898704','2015':'1899041'}[period];
      inspected.push({code,period,value:row?.value,pass:row?.value===value&&row.frequency==='annual'&&row.data_status==='official_preliminary'&&row.release_date===released&&row.source_url.endsWith(id+'.html')});
    }
    check('all_29_annual_values_and_provenance',inspected.length===29&&inspected.every(row=>row.pass),inspected);
    const legacy=payload.series.CN_INCOME_URBAN.find(row=>row.period==='2013');
    check('old_2013_urban_value_preserved',legacy.value===26955&&legacy.source_url.endsWith('1768637.html'),legacy);
    check('revised_national_income_not_replaced',['2013','2014','2015'].every(period=>{const row=payload.series.CN_DISPOSABLE_INCOME.find(row=>row.period===period);return row.data_status==='official_revised'&&row.source_url.includes('C06-16.jpg');}),['2013','2014','2015']);
    await page.getByRole('button',{name:'就业与收入',exact:true}).click();
    await setRange('2013-01','2015-12'); await ready();
    const income=chart('居民平均收入、中位数与城乡收入');
    const urbanParts=await income.locator('path[data-series="CN_INCOME_URBAN"]').evaluateAll(paths=>paths.map(path=>[path.dataset.start,path.dataset.end]));
    check('urban_survey_break_2014',JSON.stringify(urbanParts)===JSON.stringify([['2013','2013'],['2014','2015']])&&await income.locator('.method-break[data-period="2014"]').count()===1,urbanParts);
    check('survey_scope_note_visible',(await income.innerText()).includes('旧城镇住户调查口径')&&(await income.innerText()).includes('城乡一体化调查'),await income.locator('.chart-sub').allTextContents());
    const coordinates=await income.evaluate((element,series)=>{
      const ticks=[...element.querySelectorAll('.axis-tick')].map(t=>({value:Number(t.dataset.value),y:Number(t.querySelector('line').getAttribute('y1'))}));const [a,b]=[ticks[0],ticks.at(-1)];const points=[];
      for(const path of element.querySelectorAll('path.series-segment')) {const values=path.getAttribute('d').match(/-?\d+(?:\.\d+)?/g).map(Number);const rows=series[path.dataset.series].filter(row=>row.period>=path.dataset.start&&row.period<=path.dataset.end);
        rows.forEach((row,index)=>points.push({code:path.dataset.series,period:row.period,actual:values[index*2+1],expected:a.y+(row.value-a.value)*(b.y-a.y)/(b.value-a.value)}));}
      return points;
    },payload.series);
    check('all_ten_income_point_coordinates',coordinates.length===10&&coordinates.every(row=>Math.abs(row.actual-row.expected)<0.15),coordinates);
    const legend=income.locator('.legend button').filter({hasText:'城镇居民人均可支配收入'});await legend.click();
    check('urban_legend_hides_only_urban',await income.locator('path[data-series="CN_INCOME_URBAN"]').count()===0&&await income.locator('path[data-series="CN_DISPOSABLE_INCOME"]').count()===1,true);await legend.click();
    await income.screenshot({path:prefix+'-income.png'});audit.screenshots.push(prefix+'-income.png');
    await setRange('2014-01','2014-12');
    const downloadPending=page.waitForEvent('download');await page.getByRole('button',{name:'导出当前板块 CSV',exact:true}).click();
    const download=await downloadPending;await download.saveAs(prefix+'-2014.csv');audit.exports.push(prefix+'-2014.csv');
    const bytes=[];for await(const chunk of await download.createReadStream())for(const byte of chunk)bytes.push(byte);
    const csv=parseCsv(await page.evaluate(values=>new TextDecoder().decode(new Uint8Array(values)),bytes));
    const csvUrban=csv.find(row=>row.indicator_code==='CN_INCOME_URBAN');const csvMedian=csv.find(row=>row.indicator_code==='CN_DISPOSABLE_INCOME_MEDIAN');
    check('csv_original_values_and_survey_caveat',csv.every(row=>row.period==='2014')&&Number(csvUrban.value)===28844&&csvUrban.series_comparability_note.includes('旧城镇住户调查')&&Number(csvMedian.value)===17570&&csvMedian.source_url.endsWith('1898674.html'),{urban:csvUrban,median:csvMedian});
    await page.getByRole('button',{name:'消费与投资',exact:true}).click();await setRange('2014-01','2015-12');await ready();
    const consumption=chart('全国居民人均消费支出（年度）');
    const dimensions=await consumption.evaluate(element=>({client:element.clientWidth,viewbox:element.querySelector('svg').viewBox.baseVal.width}));
    check('single_to_history_reconnects_resize_measurement',Math.abs(dimensions.viewbox-(dimensions.client-24))<=2,dimensions);
    check('consumption_history_now_starts_2014',await consumption.locator('path[data-series="CN_CONSUMPTION_PC"]').getAttribute('data-start')==='2014'&&await consumption.locator('path[data-series="CN_CONSUMPTION_PC"]').getAttribute('data-end')==='2015',payload.data_quality.indicators.CN_CONSUMPTION_PC);
    await consumption.screenshot({path:prefix+'-consumption.png'});audit.screenshots.push(prefix+'-consumption.png');
    await page.getByRole('button',{name:'人口与家庭',exact:true}).click();
    await page.waitForFunction(()=>[...document.querySelectorAll('input[type=month]')].every(input=>input.value===''));
    await setRange('2013-01','2015-12');await ready();
    const urbanization=chart('常住人口城镇化率');
    const points=await urbanization.locator('path.series-segment').getAttribute('d');
    check('urbanization_three_original_annual_points',points.match(/[ML]/g).length===3,payload.series.CN_URBANIZATION_RATE.filter(row=>row.period<='2015'));
    const middle=await urbanization.evaluate(element=>{const svg=element.querySelector('svg'),rect=svg.getBoundingClientRect(),v=element.querySelector('path').getAttribute('d').match(/-?\d+(?:\.\d+)?/g).map(Number);return{x:v[2]/svg.viewBox.baseVal.width*rect.width,y:v[3]/svg.viewBox.baseVal.height*rect.height};});
    await urbanization.locator('svg').hover({position:middle});const tooltip=await urbanization.locator('.tip').innerText();
    check('urbanization_tooltip_preserves_54_77',tooltip.includes('2014')&&tooltip.includes('54.77'),tooltip);
    await urbanization.screenshot({path:prefix+'-urbanization.png'});audit.screenshots.push(prefix+'-urbanization.png');
    await page.getByRole('button',{name:'就业与收入',exact:true}).click();await setRange('2013-01','2015-12');await page.setViewportSize({width:430,height:932});await ready();
    const width=await page.evaluate(()=>({viewport:innerWidth,content:document.documentElement.scrollWidth}));
    check('mobile_no_page_overflow',width.content<=width.viewport+1,width);
    await income.screenshot({path:prefix+'-mobile.png'});audit.screenshots.push(prefix+'-mobile.png');
    check('no_uncaught_javascript_errors',audit.errors.length===0,audit.errors);audit.status='passed';
  } catch(error){audit.status='failed';audit.failure=error.message;}
  await saveJson();return {status:audit.status,checks:audit.checks.length,passed:audit.checks.filter(row=>row.pass).length,failure:audit.failure,receipt:prefix+'-audit.json',screenshots:audit.screenshots,exports:audit.exports};
}
