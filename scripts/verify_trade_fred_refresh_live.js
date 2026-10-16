async (page) => {
  // Read the actual running application. Never intercept or substitute its API.
  const stamp = new Date().toISOString().replace(/[^0-9]/g, '');
  const prefix = `output/playwright/trade-fred-live-${stamp}`;
  const receipt = {checked_at: new Date().toISOString(), mode: 'live_production', checks: [], errors: [], screenshots: []};
  const check = (name, pass, detail) => {
    receipt.checks.push({name, pass: Boolean(pass), detail});
    if (!pass) throw new Error(`${name}: ${JSON.stringify(detail)}`);
  };
  const saveJson = async (path, value) => {
    const pending = page.waitForEvent('download', {timeout: 15000});
    await page.evaluate(({name, text}) => {
      const link = document.createElement('a');
      link.download = name;
      link.href = URL.createObjectURL(new Blob([text], {type: 'application/json'}));
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }, {name: 'acceptance.json', text: JSON.stringify(value, null, 2) + '\n'});
    await (await pending).saveAs(path);
  };
  const readDownload = async download => {
    const bytes = [];
    for await (const chunk of await download.createReadStream()) {
      for (const byte of chunk) bytes.push(byte);
      if (bytes.length > 4 * 1024 * 1024) throw new Error('Unexpectedly large bounded UI export.');
    }
    return page.evaluate(values => new TextDecoder().decode(new Uint8Array(values)), bytes);
  };
  const parseCsv = text => {
    const rows = []; let row = [], field = '', quoted = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '"') {
        if (quoted && text[i + 1] === '"') {field += '"'; i++;}
        else quoted = !quoted;
      } else if (ch === ',' && !quoted) {row.push(field); field = '';}
      else if (ch === '\n' && !quoted) {row.push(field.replace(/\r$/, '')); rows.push(row); row = []; field = '';}
      else field += ch;
    }
    if (field || row.length) {row.push(field.replace(/\r$/, '')); rows.push(row);}
    rows[0][0] = rows[0][0].replace(/^\uFEFF/, '');
    return rows.slice(1).map(values => Object.fromEntries(rows[0].map((key, index) => [key, values[index]])));
  };
  const latest = (payload, code) => payload.series[code].at(-1);
  const chart = title => page.locator('.chart').filter({has: page.locator('.chart-title').filter({hasText: title})});
  page.on('pageerror', error => receipt.errors.push(error.message));
  try {
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto('http://127.0.0.1:5001/china-macro');
    await page.locator('.tabs').waitFor({timeout: 45000});
    const response = await page.request.get('http://127.0.0.1:5001/api/china-macro/data');
    check('china_http_200', response.status() === 200, response.status());
    const payload = await response.json();
    const expected = {
      CN_GACC_TRADE_CNY_YTD: 399400, CN_GACC_EXPORT_CNY_YTD: 232000, CN_GACC_IMPORT_CNY_YTD: 167400,
      CN_GACC_TRADE_CNY_YTD_YOY: 18.8, CN_GACC_EXPORT_CNY_YTD_YOY: 16.4, CN_GACC_IMPORT_CNY_YTD_YOY: 22.3,
      CN_GACC_TRADE_CNY_MONTH: 51600, CN_GACC_EXPORT_CNY_MONTH: 30300, CN_GACC_IMPORT_CNY_MONTH: 21300,
      CN_GACC_TRADE_CNY_MONTH_YOY: 27.5, CN_GACC_EXPORT_CNY_MONTH_YOY: 29.6, CN_GACC_IMPORT_CNY_MONTH_YOY: 24.6
    };
    for (const [code, value] of Object.entries(expected)) {
      const row = latest(payload, code);
      check(`source_value_${code}`, row.period === '2026-09' && row.value === value && row.data_status === 'official_relayed' && row.release_date === '2026-10-14' && row.source_url.includes('gxt.hunan.gov.cn'), row);
    }
    const usdCodes = Object.keys(payload.metrics).filter(code => code.startsWith('CN_GACC_') && code.includes('_USD_'));
    check('usd_not_fabricated', usdCodes.length === 14 && usdCodes.every(code => latest(payload, code).period === '2026-08'), usdCodes.map(code => [code, latest(payload, code).period]));
    check('no_synthetic_cny_balance', latest(payload, 'CN_GACC_BALANCE_CNY_MONTH').period === '2026-08', latest(payload, 'CN_GACC_BALANCE_CNY_MONTH'));
    await page.getByRole('button', {name: '外贸', exact: true}).click();
    await page.getByRole('button', {name: '全部', exact: true}).click();
    const months = page.locator('input[type=month]');
    await months.nth(0).fill('2026-07');
    await months.nth(1).fill('2026-09');
    await page.waitForFunction(() => [...document.querySelectorAll('.chart:has(.chart-svg)')].every(element => Math.abs(element.querySelector('svg').viewBox.baseVal.width - (element.clientWidth - 24)) <= 2));
    check('relayed_kpi_badges', await page.locator('.kpi .badge').allTextContents().then(values => values.length === 2 && values.every(value => value === '官方数据转引')), await page.locator('.kpis').innerText());
    const titles = ['进出口当月金额', '进出口累计金额', '进出口当月同比'];
    for (const title of titles) {
      const visual = chart(title);
      const endpoints = await visual.locator('path.series-segment').evaluateAll(paths => paths.map(path => ({code: path.dataset.series, start: path.dataset.start, end: path.dataset.end})));
      check(`cny_chart_${title}`, endpoints.length === 3 && endpoints.every(row => row.end === '2026-09' && row.start >= '2026-07'), endpoints);
      const coordinates = await visual.evaluate((element, values) => {
        const ticks = [...element.querySelectorAll('.axis-tick')].map(tick => ({value: Number(tick.dataset.value), y: Number(tick.querySelector('line').getAttribute('y1'))}));
        const [first, last] = [ticks[0], ticks.at(-1)];
        return [...element.querySelectorAll('path.series-segment')].map(path => {
          const numbers = path.getAttribute('d').match(/-?\d+(?:\.\d+)?/g).map(Number);
          const actualY = numbers.at(-1);
          const expectedY = first.y + (values[path.dataset.series] - first.value) * (last.y - first.y) / (last.value - first.value);
          return {code: path.dataset.series, actualY, expectedY};
        });
      }, expected);
      check(`plotted_values_${title}`, coordinates.every(point => Math.abs(point.actualY - point.expectedY) < 0.15), coordinates);
    }
    const amount = chart(titles[0]);
    const firstLegend = amount.locator('.legend button').first();
    await firstLegend.click();
    check('legend_hides_only_selected_series', await amount.locator('path.series-segment').count() === 2, await amount.locator('.legend').innerText());
    await firstLegend.click();
    check('legend_restores_series', await amount.locator('path.series-segment').count() === 3, 3);
    await page.getByRole('button', {name: '从零', exact: true}).click();
    check('zero_axis_control', (await amount.locator('.axis-tick').first().getAttribute('data-value')) === '0', await amount.locator('.axis-tick').first().getAttribute('data-value'));
    await page.getByRole('button', {name: '自动', exact: true}).click();
    const csvPending = page.waitForEvent('download');
    await page.getByRole('button', {name: '导出当前板块 CSV', exact: true}).click();
    const download = await csvPending;
    await download.saveAs(`${prefix}-cny.csv`);
    const csv = parseCsv(await readDownload(download));
    const latestCsv = csv.filter(row => row.period === '2026-09');
    check('csv_latest_nine_displayed_series', latestCsv.length === 9 && latestCsv.every(row => Number(row.value) === expected[row.indicator_code] && row.data_status === 'official_relayed' && row.evidence_tier === '官方数据转引' && row.release_date === '2026-10-14'), latestCsv);
    check('csv_selected_period_only', csv.every(row => row.period >= '2026-07' && row.period <= '2026-09'), {rows: csv.length});
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: `${prefix}-cny.png`, fullPage: true});
    receipt.screenshots.push(`${prefix}-cny.png`);
    await page.getByRole('button', {name: '美元', exact: true}).click();
    const dollarEndpoints = await page.locator('path.series-segment').evaluateAll(paths => paths.map(path => ({code: path.dataset.series, end: path.dataset.end})));
    check('dollar_chart_stops_in_august', dollarEndpoints.length === 10 && dollarEndpoints.every(row => row.code.includes('_USD_') && row.end === '2026-08'), dollarEndpoints);
    check('dollar_units', (await chart(titles[0]).innerText()).includes('亿美元'), await chart(titles[0]).locator('.chart-sub').allTextContents());
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: `${prefix}-usd.png`, fullPage: true});
    receipt.screenshots.push(`${prefix}-usd.png`);
    await page.getByRole('button', {name: '人民币', exact: true}).click();
    await page.setViewportSize({width: 430, height: 932});
    await page.waitForFunction(() => [...document.querySelectorAll('.chart:has(.chart-svg)')].every(element => Math.abs(element.querySelector('svg').viewBox.baseVal.width - (element.clientWidth - 24)) <= 2));
    const mobile = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
    check('mobile_no_page_overflow', mobile.scroll <= mobile.width + 1, mobile);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: `${prefix}-mobile.png`, fullPage: true});
    receipt.screenshots.push(`${prefix}-mobile.png`);
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto('http://127.0.0.1:5001/us-macro');
    await page.locator('.section').first().waitFor({timeout: 45000});
    const usResponse = await page.request.get('http://127.0.0.1:5001/api/us-macro/data');
    const us = await usResponse.json();
    check('us_raw_68_plus_derived', usResponse.status() === 200 && us.data_quality.registered_series === 68 && us.data_quality.series_with_data === 68, {raw_registered: us.data_quality.registered_series, raw_nonempty: us.data_quality.series_with_data, payload_including_derived: Object.keys(us.series).length});
    const snapshot = us.yield_curve_snapshots.filter(row => Object.keys(row.values).length === 11).at(-1);
    const yieldChart = chart('最近完整同日名义国债收益率曲线');
    const yieldText = await yieldChart.innerText();
    check('eleven_actual_same_day_yields', us.yield_curve_tenors.length === 11 && snapshot.period === '2026-10-13' && yieldText.includes(snapshot.period) && yieldText.includes('11/11'), snapshot);
    check('us_source_lags_not_filled', us.data_quality.indicators.UNRATE.end_period === '2026-09-01' && us.data_quality.indicators.PCEC96.end_period === '2026-08-01' && us.data_quality.indicators.GDPC1.end_period === '2026-04-01', ['UNRATE', 'PCEC96', 'GDPC1'].map(code => ({code, end: us.data_quality.indicators[code].end_period})));
    await yieldChart.screenshot({path: `${prefix}-us-yields.png`});
    receipt.screenshots.push(`${prefix}-us-yields.png`);
    check('no_uncaught_javascript_errors', receipt.errors.length === 0, receipt.errors);
    receipt.status = 'passed';
  } catch (error) {
    receipt.status = 'failed';
    receipt.failure = error.message;
  }
  receipt.finished_at = new Date().toISOString();
  await saveJson(`${prefix}-audit.json`, receipt);
  return {status: receipt.status, checks: receipt.checks.length, passed: receipt.checks.filter(row => row.pass).length, failure: receipt.failure, receipt: `${prefix}-audit.json`, screenshots: receipt.screenshots};
}
