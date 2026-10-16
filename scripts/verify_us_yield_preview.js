async (page) => {
  // This is an isolated new-code rendering test, not live deployment evidence.
  const receipt={mode:'offline_newcode_preview_not_production',checked_at:new Date().toISOString(),checks:{},errors:[]};
  page.on('pageerror',error=>receipt.errors.push(error.message));
  await page.route('**/api/us-macro/data',route=>route.fulfill({
    path:'outputs/macro_refresh_20261010/checkpoint-20261010-195741-965024/us_payload_newcode.json',
    contentType:'application/json'}));
  await page.reload();
  await page.locator('.section').first().waitFor({timeout:60000});
  await page.setViewportSize({width:1440,height:1000});
  const snapshot=page.locator('.chart').filter({has:page.locator('.chart-title').filter({hasText:'最近完整同日名义国债收益率曲线'})});
  await snapshot.waitFor();
  const text=await snapshot.innerText();
  receipt.checks.full_same_date=text.includes('2026-10-08')&&text.includes('11/11');
  if(!receipt.checks.full_same_date)throw new Error('The reviewed source payload did not render a complete same-date curve.');
  await snapshot.scrollIntoViewIfNeeded();
  const prefix='us-yield-preview-'+new Date().toISOString().replace(/[^0-9]/g,'');
  await page.screenshot({path:`output/playwright/${prefix}.png`,scale:'css'});
  await page.getByRole('textbox',{name:'截止月份'}).fill('2026-08');
  const changed=await snapshot.innerText();
  receipt.checks.period_window=!changed.includes('2026-10-08');
  if(!receipt.checks.period_window)throw new Error('A curve date outside the selected end month was displayed.');
  receipt.checks.no_page_errors=receipt.errors.length===0;
  receipt.screenshot=`${prefix}.png`;
  receipt.status=Object.values(receipt.checks).every(Boolean)?'passed':'failed';
  await page.unroute('**/api/us-macro/data');
  return receipt;
}
