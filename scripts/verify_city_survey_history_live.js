async page => {
  // This audit uses the actual running API and page; no request interception.
  const prefix = 'output/playwright/city-survey-live-' + new Date().toISOString().replace(/[^0-9]/g, '');
  const audit = {mode: 'live_production', checked_at: new Date().toISOString(), checks: [], errors: [], screenshots: []};
  const check = (name, pass, detail) => {
    audit.checks.push({name, pass: Boolean(pass), detail});
    if (!pass) throw new Error(name + ': ' + JSON.stringify(detail));
  };
  const save = async (name, text) => {
    const pending = page.waitForEvent('download');
    await page.evaluate(({name, text}) => {
      const link = document.createElement('a'); link.download = name;
      link.href = URL.createObjectURL(new Blob([text], {type: 'application/json'})); link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    }, {name, text});
    await (await pending).saveAs(name);
  };
  const chart = () => page.locator('.chart').filter({has: page.locator('.chart-title').filter({hasText: '31个大城市调查失业率'})});
  page.on('pageerror', error => audit.errors.push(error.message));
  try {
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto('http://127.0.0.1:5001/china-macro');
    await page.locator('.tabs').waitFor({timeout: 45000});
    const response = await page.request.get('http://127.0.0.1:5001/api/china-macro/data');
    check('actual_api_200', response.status() === 200, response.status());
    const payload = await response.json(), city = payload.series.CN_UNEMP_31_CITIES;
    const quality = payload.data_quality.indicators.CN_UNEMP_31_CITIES;
    check('city_96_actual_months_since_january2018', city.length === 96 && city[0].period === '2018-01' && city.at(-1).period === '2026-08', quality);
    check('eight_unfilled_january_gaps', quality.internal_gap_count === 8 && quality.missing_periods.every(period => period.endsWith('-01')), quality.missing_periods);
    const expected = {'2018-01': 4.9, '2018-02': 4.8, '2018-03': 4.9, '2018-09': 4.7, '2018-11': 4.7,
      '2018-12': 4.7, '2019-02': 5.0, '2020-03': 5.7, '2021-10': 5.1, '2022-04': 6.7, '2023-03': 5.5};
    for (const [period, value] of Object.entries(expected)) {
      const row = city.find(row => row.period === period);
      check('verified_city_' + period, row?.value === value && row.data_status === 'official' && row.source_url.startsWith('https://www.stats.gov.cn/') && row.release_date, row);
    }
    check('national_104_not_replaced_by_city_rates', payload.series.CN_UNEMP_SURVEY.length === 104 && payload.series.CN_UNEMP_SURVEY.find(row => row.period === '2018-01').value === 5.0, payload.data_quality.indicators.CN_UNEMP_SURVEY);
    await page.getByRole('button', {name: '就业与收入', exact: true}).click();
    await page.getByRole('button', {name: '全部', exact: true}).click();
    await page.waitForFunction(() => [...document.querySelectorAll('.chart:has(.chart-svg)')].every(element => Math.abs(element.querySelector('svg').viewBox.baseVal.width - (element.clientWidth - 24)) <= 2));
    const segments = await chart().locator('path.series-segment').evaluateAll(paths => paths.map(path => ({start: path.dataset.start, end: path.dataset.end, n: path.getAttribute('d').match(/[ML]/g).length})));
    check('full_history_breaks_at_real_missing_months', segments.length === 9 && segments[0].start === '2018-01' && segments[0].end === '2018-12' && segments.reduce((total, row) => total + row.n, 0) === 96, segments);
    const coordinates = await chart().evaluate((element, rows) => {
      const ticks = [...element.querySelectorAll('.axis-tick')].map(tick => ({value: Number(tick.dataset.value), y: Number(tick.querySelector('line').getAttribute('y1'))}));
      const [first, last] = [ticks[0], ticks.at(-1)];
      const points = [];
      for (const path of element.querySelectorAll('path.series-segment')) {
        const values = path.getAttribute('d').match(/-?\d+(?:\.\d+)?/g).map(Number);
        const subset = rows.filter(row => row.period >= path.dataset.start && row.period <= path.dataset.end);
        for (let index = 0; index < subset.length; index++) {
          const expectedY = first.y + (subset[index].value - first.value) * (last.y - first.y) / (last.value - first.value);
          points.push({period: subset[index].period, actual: values[index * 2 + 1], expected: expectedY});
        }
      }
      return points;
    }, city);
    check('all_96_point_values_match_axis_scale', coordinates.length === 96 && coordinates.every(point => Math.abs(point.actual - point.expected) < 0.15), {points: coordinates.length, max_error: Math.max(...coordinates.map(point => Math.abs(point.actual-point.expected)))});
    await chart().screenshot({path: prefix + '-history.png'});
    audit.screenshots.push(prefix + '-history.png');
    const months = page.locator('input[type=month]');
    await months.nth(0).fill('2019-01'); await months.nth(1).fill('2019-01');
    check('missing_january_is_not_forward_filled', await chart().locator('path.series-segment').count() === 0 && (await chart().innerText()).includes('没有可用数据'), await chart().innerText());
    await months.nth(0).fill('2022-02'); await months.nth(1).fill('2022-05');
    const svg = chart().locator('svg');
    const hoverPoint = await chart().evaluate(element => {
      const svg = element.querySelector('svg'), values = element.querySelector('path.series-segment').getAttribute('d').match(/-?\d+(?:\.\d+)?/g).map(Number), rect = svg.getBoundingClientRect();
      return {x: values[4] / svg.viewBox.baseVal.width * rect.width, y: values[5] / svg.viewBox.baseVal.height * rect.height};
    });
    await svg.hover({position: hoverPoint});
    const tooltip = await chart().locator('.tip').innerText();
    check('correct_april2022_tooltip', tooltip.includes('2022-04') && tooltip.includes('6.7'), tooltip);
    await months.nth(0).fill('2022-04'); await months.nth(1).fill('2022-04');
    check('one_month_is_not_fake_trend', await chart().locator('path.series-segment').count() === 0 && (await chart().innerText()).includes('少于 2 期'), await chart().innerText());
    const pending = page.waitForEvent('download');
    await page.getByRole('button', {name: '导出当前板块 CSV', exact: true}).click();
    const download = await pending; await download.saveAs(prefix + '-april2022.csv');
    const bytes = []; for await (const chunk of await download.createReadStream()) for (const byte of chunk) bytes.push(byte);
    const csv = await page.evaluate(values => new TextDecoder().decode(new Uint8Array(values)), bytes);
    const line = csv.split(/\r?\n/).find(line => line.startsWith('"CN_UNEMP_31_CITIES"'));
    check('csv_repaired_city_value_and_true_2022_source', line && line.includes('"2022-04","6.7"') && line.includes('t20230203_1901460.html') && !line.includes('1900718.html'), line);
    await page.getByRole('button', {name: '全部', exact: true}).click();
    await page.setViewportSize({width: 430, height: 932});
    await page.waitForFunction(() => [...document.querySelectorAll('.chart:has(.chart-svg)')].every(element => Math.abs(element.querySelector('svg').viewBox.baseVal.width - (element.clientWidth - 24)) <= 2));
    const width = await page.evaluate(() => ({viewport: innerWidth, content: document.documentElement.scrollWidth}));
    check('mobile_no_whole_page_overflow', width.content <= width.viewport + 1, width);
    await chart().screenshot({path: prefix + '-mobile.png'}); audit.screenshots.push(prefix + '-mobile.png');
    check('no_uncaught_page_errors', audit.errors.length === 0, audit.errors);
    audit.status = 'passed';
  } catch (error) {audit.status = 'failed'; audit.failure = error.message;}
  await save(prefix + '-audit.json', JSON.stringify(audit, null, 2) + '\n');
  return {status: audit.status, checks: audit.checks.length, passed: audit.checks.filter(row => row.pass).length,
    failure: audit.failure, receipt: prefix + '-audit.json', screenshots: audit.screenshots};
}
