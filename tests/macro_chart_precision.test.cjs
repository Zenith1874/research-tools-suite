const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'china_macro.html'), 'utf8');
const start = html.indexOf('function fmt(');
const end = html.indexOf('function periodIndex(');
assert(start >= 0 && end > start, 'The chart formatting helpers must exist.');
const context = {};
vm.runInNewContext(html.slice(start, end), context);
const segmentEnd=html.indexOf('const STATUS_LABELS=');
vm.runInNewContext(html.slice(end,segmentEnd),context);
const bankStart=html.indexOf('function bankingGroup(');
const bankEnd=html.indexOf('function LineChart(');
vm.runInNewContext(html.slice(bankStart,bankEnd),context);
const usHtml=fs.readFileSync(path.join(__dirname,'..','static','us_macro.html'),'utf8');
const selectorStart=usHtml.indexOf('function selectYieldSnapshot(');
const selectorEnd=usHtml.indexOf('function YieldSnapshot(');
vm.runInNewContext(usHtml.slice(selectorStart,selectorEnd),context);

test('same-day yield curve prefers complete real observations without carrying values', () => {
  const tenors=[['A','short'],['B','long']];
  const rows=[{period:'2026-10-07',values:{A:4.1,B:5.1}},
              {period:'2026-10-08',values:{B:5.2}}];
  const result=context.selectYieldSnapshot(rows,tenors);
  assert.equal(result.period,'2026-10-07');
  assert.equal(result.latest_available,'2026-10-08');
  assert.equal(result.complete,true);
  assert.equal(rows[1].values.A,undefined);
  assert.equal(context.selectYieldSnapshot([],tenors),null);
});

test('bank charts expose all fields during and after a backend version transition', () => {
  const payload={series:{CN_BANK_NPL_RATIO:[{period:'2024-03'},{period:'2026-06'}]}};
  const oldGroup={code:'banking',charts:[{code:'bank_npl'}]};
  const upgraded=context.bankingGroup(oldGroup,payload);
  assert.equal(upgraded.charts.length,5);
  assert(upgraded.description.includes('2024-03—2026-06'));
  assert.equal(context.bankingGroup(upgraded,payload).charts.length,5);
  assert.equal(oldGroup.charts.length,1);
});

test('bank capital series explicitly break at the 2024 rules transition', () => {
  const group={code:'banking',charts:[{code:'bank_capital',series:['CN_BANK_CAPITAL_ADEQUACY']}]};
  const payload={series:{CN_BANK_NPL_RATIO:[{period:'2023-03'},{period:'2026-06'}]}};
  const result=context.bankingGroup(group,payload);
  assert.equal(result.charts[0].breaks[0],'2024-03');
  assert(result.description.includes('2023-03—2026-06'));
  assert.equal(group.charts[0].breaks,undefined);
});

test('annual FDI charts are added independently without a monthly or CNY substitute', () => {
  const group={code:'capital',charts:[{code:'fdi_odi',series:['CN_MOFCOM_FDI_{currency}_YTD']}]};
  const payload={series:{CN_MOFCOM_FDI_USD_ANNUAL:[{period:'2025',value:1046.6}],
                         CN_MOFCOM_FDI_NEW_FIRMS_ANNUAL:[{period:'2025',value:70392}]}};
  const result=context.capitalGroup(group,payload);
  assert.equal(result.charts.length,3);
  const annual=result.charts.find(chart=>chart.code==='fdi_annual_usd');
  assert.equal(annual.unit,'亿美元');
  assert.equal(annual.series[0],'CN_MOFCOM_FDI_USD_ANNUAL');
  assert.equal(context.capitalGroup(result,payload).charts.length,3);
  assert.equal(group.charts.length,1);
});

test('the May 2022 FDI scope break is not applied to the ODI series', () => {
  const result=context.capitalGroup({code:'capital',charts:[{code:'fdi_odi'}]},{series:{}});
  const chart=result.charts[0];
  assert.equal(chart.series_breaks.CN_MOFCOM_FDI_USD_YTD[0],'2022-05');
  assert.equal(chart.series_breaks.CN_MOFCOM_ODI_NONFIN_USD_YTD,undefined);
  assert.equal(chart.breaks,undefined);
});

test('legacy 2013 urban income stays a point while the unified survey starts a new segment', () => {
  const group={code:'employment',charts:[{code:'income_distribution',series:['CN_INCOME_URBAN','CN_INCOME_RURAL']}]};
  const payload={series:{CN_INCOME_URBAN:[{period:'2013',value:26955,source_url:'https://www.stats.gov.cn/xxgk/sjfb/tjgb2020/201407/t20140718_1768637.html'}]}};
  const chart=context.employmentGroup(group,payload).charts[0];
  assert.equal(JSON.stringify(chart.series_breaks),JSON.stringify({CN_INCOME_URBAN:['2014']}));
  assert.equal(group.charts[0].series_breaks,undefined);
  const parts=context.segments([{period:'2013',value:26955},{period:'2014',value:28844},{period:'2015',value:31195}],'annual',chart.series_breaks.CN_INCOME_URBAN);
  assert.equal(JSON.stringify(parts.map(part=>part.map(row=>row.period))),JSON.stringify([['2013'],['2014','2015']]));
  assert.equal(context.employmentGroup(context.employmentGroup(group,payload),payload).charts[0].series_breaks.CN_INCOME_URBAN.length,1);
  assert.equal(context.employmentGroup(group,{series:{CN_INCOME_URBAN:[{period:'2013',value:26467}]}}),group);
});

test('census calibration breaks preserve age-subset and export caveats', () => {
  const book='https://www.stats.gov.cn/book/P020240417553133577139.pdf';
  const group={code:'demography',charts:[{code:'aging_population',note:'65岁是60岁的子集，不能相加。'},{code:'urbanization'}]};
  const payload={series:{CN_POP_60_PLUS:[{period:'2020',source_url:book+'#page=32'}],CN_POP_65_PLUS:[{period:'2020',source_url:book+'#page=32'}],CN_URBANIZATION_RATE:[{period:'2020',source_url:'https://www.stats.gov.cn/sj/sjjd/202606/t20260603_1963868.html'}]}};
  const result=context.annualComparabilityGroup(group,payload);
  assert.deepEqual(JSON.parse(JSON.stringify(result.charts[0].series_breaks)),{CN_POP_60_PLUS:['2020'],CN_POP_65_PLUS:['2020']});
  assert(result.charts[0].note.includes('不能相加'));assert.equal(group.charts[0].series_breaks,undefined);
  assert(context.seriesComparabilityNote(result.charts[1],'CN_URBANIZATION_RATE',{}).includes('普查校准'));
  assert.equal(context.annualComparabilityGroup(result,payload).charts[0].note,result.charts[0].note);
});

test('a representative year carries a CSV note without manufacturing intervening observations', () => {
  const note=context.seriesComparabilityNote({},'CN_CONSUMPTION_PC',{period:'2000',source_url:'https://www.stats.gov.cn/book/P020240417553133577139.pdf#page=98'});
  assert(note.includes('2001—2012未列'));assert(note.includes('不插值'));
  const pieces=context.segments([{period:'2000',value:2914},{period:'2013',value:13220},{period:'2014',value:14491}],'annual');
  assert.deepEqual(JSON.parse(JSON.stringify(pieces.map(part=>part.map(row=>row.period)))),[['2000'],['2013','2014']]);
});

test('small percentage changes retain distinct axis tick labels', () => {
  const ticks = [1.5092, 1.515, 1.5208];
  const digits = context.axisDigits(ticks[2] - ticks[0]);
  const labels = ticks.map(value => context.fmt(value, digits));
  assert.equal(new Set(labels).size, ticks.length);
});

test('tick coordinates use their displayed numeric labels, not rounded domain endpoints', () => {
  for(const bounds of [[1.4652,1.8248],[1.5092,1.5208],[-.1784,.3892]]){
    const digits=context.axisDigits(bounds[1]-bounds[0]);
    const ticks=context.axisTickValues(bounds[0],bounds[1],digits);
    assert(ticks.length>=2);
    for(const value of ticks){
      assert(value>=bounds[0]&&value<=bounds[1]);
      assert.equal(Number(context.fmt(value,digits).replaceAll(',','')),value);
    }
  }
});

test('ticks are unique and do not invent labels below bounded resolution', () => {
  assert.equal(JSON.stringify(context.axisTickValues(0,1,1)),JSON.stringify([0,.5,1]));
  assert.equal(JSON.stringify(context.axisTickValues(1.00000001,1.00000002,6)),JSON.stringify([]));
  const values=context.axisTickValues(-.04,.02,2);
  assert.equal(new Set(values).size,values.length);
});

test('nonnegative source values do not get negative axis bounds and zero means zero', () => {
  assert.equal(context.chartDomain([9.2,1046.6,1891.3],null,'auto')[0],0);
  assert.equal(context.chartDomain([100,200],null,'zero')[0],0);
  assert.equal(context.chartDomain([-200,-100],null,'zero')[1],0);
  assert.equal(context.chartDomain([],null,'auto'),null);
  assert.equal(context.chartDomain([null,undefined,true],null,'auto'),null);
  assert.equal(JSON.stringify(context.chartDomain([0,0],null,'auto')),JSON.stringify([0,1]));
  const signed=context.chartDomain([-10,20],null,'auto');
  assert(signed[0]<0&&signed[1]>0);
});

test('bank percentage values keep their two-decimal observation precision', () => {
  assert.equal(context.fmt(1.52, 2), '1.52');
  assert.equal(context.fmt(1.41, 2), '1.41');
  assert.equal(context.fmt(202.87, 2), '202.87');
  assert.equal(context.fmt(null, 2), '—');
});

test('urbanization tooltip retains its published two-decimal percentages', () => {
  assert.equal(context.observationDigits('CN_URBANIZATION_RATE'),2);
  assert.equal(context.fmt(54.77,context.observationDigits('CN_URBANIZATION_RATE')),'54.77');
  assert.equal(context.observationDigits('CN_BANK_NPL_RATIO'),2);
  assert.equal(context.observationDigits('CN_INCOME_REAL_YOY'),1);
});

test('empty, hidden and single-observation chart states retain the measured container', () => {
  for(const state of ['dataSeries','visible','trendVisible']){
    assert(html.includes(`if(!${state}.length)return <div className="chart" ref={chartRef}>`));
  }
});

test('axis precision stays bounded for zero and extremely small spans', () => {
  assert.equal(context.axisDigits(0), 1);
  assert.equal(context.axisDigits(NaN), 1);
  assert.equal(context.axisDigits(0.00000001), 6);
  assert.equal(context.axisDigits(10000), 1);
});

test('quarterly lines do not bridge missing quarters or the SAFE 2017 revision', () => {
  const rows=[{period:'2017-06',value:10},{period:'2017-09',value:11},
              {period:'2017-12',value:20},{period:'2018-03',value:21},
              {period:'2018-09',value:23}];
  const parts=context.segments(rows,'quarterly',['2017-12']);
  assert.equal(JSON.stringify(parts.map(part=>part.map(row=>row.period))),
               JSON.stringify([['2017-06','2017-09'],['2017-12','2018-03'],['2018-09']]));
});

test('annual year-end break applies without manufacturing monthly observations', () => {
  const rows=['2015','2016','2017','2018'].map((period,index)=>({period,value:index}));
  const parts=context.segments(rows,'annual',['2017-12']);
  assert.equal(parts.length,2);
  assert.equal(parts[0][1].period,'2016');
  assert.equal(parts[1][0].period,'2017');
});

test('real zero is retained but null and invalid cells break the line', () => {
  const rows=[{period:'2026-01',value:0},{period:'2026-02',value:null},
              {period:'2026-03',value:1},{period:'2026-04',value:Infinity},
              {period:'2026-05',value:2}];
  const parts=context.segments(rows,'monthly');
  assert.equal(parts.length,3);
  assert.equal(parts[0][0].value,0);
  assert.equal(parts.flat().length,3);
});
