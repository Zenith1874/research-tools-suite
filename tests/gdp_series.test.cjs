const test = require('node:test');
const assert = require('node:assert/strict');
const {realGrowthRows, enrichProvenance, comparisonPointRadii, annualComparisonYears} = require('../static/gdp-series.js');
const level = (year, value, unit = 'chained 2017 USD') => ({region_code:'01',period:String(year),value,unit,indicator_code:'real_gdp'});

test('direct official real growth has priority over division of levels', () => {
  const rows = realGrowthRows([level(2024,100),level(2025,110),{...level(2025,5.3,'%'),indicator_code:'real_growth',data_status:'official_preliminary'}]);
  assert.equal(rows.length,1); assert.equal(rows[0].value,5.3); assert.equal(rows[0].data_status,'official_preliminary');
});
test('derived real growth requires adjacent years and matching price units', () => {
  assert.deepEqual(realGrowthRows([level(2022,100),level(2024,120)]),[]);
  assert.deepEqual(realGrowthRows([level(2024,100),level(2025,120,'chained 2022 USD')]),[]);
  const rows=realGrowthRows([level(2024,100),level(2025,110)]);
  assert.ok(Math.abs(rows[0].value-10)<1e-10); assert.equal(rows[0].data_status,'derived');
});
test('nominal amounts never become real growth and null is not zero', () => {
  assert.deepEqual(realGrowthRows([{...level(2025,100),indicator_code:'nominal_gdp'},level(2024,null)]),[]);
});
test('provenance fallback requires exact period, code, indicator, value and unit', () => {
  const row={region_code:'110000',period:'2025',indicator_code:'nominal_gdp',value:52073.4,unit:'亿元'};
  const source={...row,source_url:'https://tjj.beijing.gov.cn/a.html',data_status:'official_preliminary'};
  assert.equal(enrichProvenance([row],{rows:[source]})[0].source_url,source.source_url);
  for(const change of [{value:52073},{period:'2024'},{unit:'万元'},{region_code:'110100'},{indicator_code:'real_gdp'}])
    assert.equal(enrichProvenance([{...row,...change}],{rows:[source]})[0].source_url,undefined);
});
test('live source metadata is never overwritten by a reviewed historical fallback', () => {
  const row={region_code:'110000',period:'2025',indicator_code:'nominal_gdp',value:52073.4,unit:'亿元',source_url:'https://tjj.beijing.gov.cn/new.html'};
  assert.equal(enrichProvenance([row],{rows:[{...row,source_url:'https://tjj.beijing.gov.cn/old.html'}]})[0].source_url,row.source_url);
});

test('isolated observations remain visible when four or more regions are selected', () => {
  assert.deepEqual(comparisonPointRadii([null,100],4),[0,4]);
  assert.deepEqual(comparisonPointRadii([null,0,null,-2,null],6),[0,4,0,4,0]);
  assert.deepEqual(comparisonPointRadii([NaN,Infinity,null],4),[0,0,0]);
});

test('dense comparison hides only non-isolated markers, never gap-separated observations', () => {
  assert.deepEqual(comparisonPointRadii([100,101,102],4),[0,0,0]);
  assert.deepEqual(comparisonPointRadii([100,101,102],3),[2,2,2]);
  assert.deepEqual(comparisonPointRadii([100,null,102],4),[4,0,4]);
});

test('annual comparison axes retain globally missing years without filling values', () => {
  assert.deepEqual(annualComparisonYears(['2023','2025','2025'],'2023','2025'),['2023','2024','2025']);
  assert.deepEqual(annualComparisonYears(['2020','2023','2025'],'2022','2024'),['2023']);
  assert.deepEqual(annualComparisonYears(['2025-06','missing'],'2020','2030'),[]);
});

test('coverage extent is independent of raw and appended derived row order', () => {
  const years=annualComparisonYears(['2023','2025','2018','2020','2024']);
  assert.equal(years[0],'2018');assert.equal(years.at(-1),'2025');
  assert.deepEqual(annualComparisonYears(['2025','2023','2024']),['2023','2024','2025']);
});
