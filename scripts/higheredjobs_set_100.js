async page => {
  await page.locator('select[name="NumJobs"]').selectOption('100');
  await page.waitForLoadState('domcontentloaded');
  await page.waitForTimeout(1500);
}
