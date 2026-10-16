async (page) => {
  // Run with playwright-cli run-code --filename in an isolated named session.
  // This checks presentation only; it never starts an update or writes the DB.
  const receipt = {url: page.url(), checked_at: new Date().toISOString(), checks: {}, errors: []};
  const prefix='macro-ui-'+new Date().toISOString().replace(/[^0-9]/g,'');
  page.on('pageerror', error => receipt.errors.push(error.message));
  const check = (name, condition, detail) => {
    receipt.checks[name] = {pass: Boolean(condition), detail};
    if (!condition) throw new Error(`${name}: ${JSON.stringify(detail)}`);
  };
  await page.setViewportSize({width: 1440, height: 1000});
  if (page.url().includes('/china-macro')) {
    await page.locator('.tabs').waitFor({timeout: 60000});
    const names = ['增长与生产', '企业经营', '银行风险', '消费与投资', '价格与景气',
      '就业与收入', '人口与家庭', '外贸', '外资与跨境资金'];
    const boards = [];
    for (const name of names) {
      await page.locator('.tabs').getByRole('button', {name, exact: true}).click();
      const heading = await page.locator('.section-head h2').innerText();
      const charts = await page.locator('.chart-grid .chart').count();
      boards.push({name, heading, charts});
      check(`board:${name}`, heading === name && charts > 0, boards[boards.length - 1]);
    }
    receipt.boards = boards;
    await page.locator('.tabs').getByRole('button', {name: '银行风险', exact: true}).click();
    const cards = await page.locator('.kpi-value').allTextContents();
    check('bank_latest_precision', cards.some(text => text.includes('1.52')) &&
      cards.some(text => text.includes('1.41')) && cards.some(text => text.includes('202.87')), cards);
    const ticks = await page.locator('.chart-svg').nth(1).locator('text').allTextContents();
    check('bank_distinct_axis_ticks', new Set(ticks.slice(0, 3)).size === 3, ticks);
    const firstChart = page.locator('.chart-grid .chart').first();
    await firstChart.locator('.legend button').first().click();
    check('legend_hide', (await firstChart.innerText()).includes('全部序列已隐藏'), await firstChart.innerText());
    await firstChart.locator('.legend button').first().click();
    check('legend_restore', await firstChart.locator('svg').count() === 1, 'Restored first bank series');
    await page.screenshot({path: `output/playwright/${prefix}-china-banking.png`, scale: 'css'});
    const monthInputs = page.locator('input[type=month]');
    await monthInputs.nth(0).fill('2026-03');
    await monthInputs.nth(1).fill('2026-06');
    check('free_period', await monthInputs.nth(0).inputValue() === '2026-03' &&
      await monthInputs.nth(1).inputValue() === '2026-06', '2026-03 through 2026-06');
    await page.getByRole('button', {name: '从零', exact: true}).click();
    check('zero_axis', (await page.getByRole('button', {name: '从零', exact: true}).getAttribute('class')).includes('active'), 'Zero-axis control selected');
    await page.getByRole('button', {name: '自动', exact: true}).click();
    await page.getByRole('button', {name: '全部', exact: true}).click();
    await page.locator('.tabs').getByRole('button', {name: '价格与景气', exact: true}).click();
    check('pmi_threshold', (await page.locator('.chart-grid').innerText()).includes('荣枯线 50'), 'PMI threshold drawn');
    await page.screenshot({path: `output/playwright/${prefix}-china-prices.png`, scale: 'css'});
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', {name: '导出当前板块 CSV', exact: true}).click();
    const download = await downloadPromise;
    await download.saveAs(`output/playwright/${prefix}-prices.csv`);
    check('csv_export', Boolean(await download.path()), download.suggestedFilename());
    await page.setViewportSize({width: 390, height: 844});
    const sizes = await page.evaluate(() => ({width: innerWidth, body: document.documentElement.scrollWidth}));
    check('narrow_no_page_overflow', sizes.body <= sizes.width + 1, sizes);
    await page.screenshot({path: `output/playwright/${prefix}-china-narrow.png`, scale: 'css'});
    receipt.screenshots = [`${prefix}-china-banking.png`, `${prefix}-china-prices.png`, `${prefix}-china-narrow.png`];
  } else if (page.url().includes('/us-macro')) {
    await page.locator('.section').first().waitFor({timeout: 60000});
    const sections = await page.locator('.section-head h2').allTextContents();
    check('expanded_us_sections', ['住房与建设', '外贸与大宗商品'].every(name => sections.some(title => title.includes(name))) && sections.length >= 9, sections);
    const titles = await page.locator('.chart-title').allTextContents();
    check('new_us_charts', ['住宅许可、开工与新房销售', '实际消费与实际可支配收入同比',
      '商业银行总信贷', 'WTI 与 Brent 原油现货', '持续申领失业救济'].every(name => titles.some(title => title.includes(name))), titles);
    const monthInputs = page.locator('input[type=month]');
    await monthInputs.nth(0).fill('2024-01');
    await monthInputs.nth(1).fill('2026-08');
    check('free_period', await monthInputs.nth(0).inputValue() === '2024-01' &&
      await monthInputs.nth(1).inputValue() === '2026-08', '2024-01 through 2026-08');
    const firstLegend = page.locator('.chart').first().locator('.legend button').first();
    if (await firstLegend.getAttribute('aria-pressed') === 'false') await firstLegend.click();
    await firstLegend.click();
    check('legend_hide', await firstLegend.getAttribute('aria-pressed') === 'false', 'First labor series hidden');
    await firstLegend.click();
    check('legend_restore', await firstLegend.getAttribute('aria-pressed') === 'true', 'First labor series restored');
    await page.screenshot({path: `output/playwright/${prefix}-us-overview.png`, scale: 'css'});
    const housing = page.locator('.section').filter({has: page.getByRole('heading', {name: '住房与建设', exact: true})});
    await housing.scrollIntoViewIfNeeded();
    await page.screenshot({path: `output/playwright/${prefix}-us-housing.png`, scale: 'css'});
    await page.setViewportSize({width: 390, height: 844});
    await page.evaluate(() => window.scrollTo(0, 0));
    const sizes = await page.evaluate(() => ({width: innerWidth, body: document.documentElement.scrollWidth}));
    check('narrow_no_page_overflow', sizes.body <= sizes.width + 1, sizes);
    await page.screenshot({path: `output/playwright/${prefix}-us-narrow.png`, scale: 'css'});
    receipt.screenshots = [`${prefix}-us-overview.png`, `${prefix}-us-housing.png`, `${prefix}-us-narrow.png`];
  } else {
    throw new Error('Open an existing China or US macro page before running acceptance.');
  }
  check('no_page_errors', receipt.errors.length === 0, receipt.errors);
  receipt.status = 'passed';
  return receipt;
}
