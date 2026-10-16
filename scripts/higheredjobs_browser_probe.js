async page => {
  const result = await page.locator('div.row.record').evaluateAll(cards => ({
    cards: cards.length,
    codes: cards.map(card => {
      const anchor = card.querySelector('a[href*="details.cfm?JobCode="]');
      return anchor ? new URL(anchor.href, location.href).searchParams.get('JobCode') : null;
    }).filter(Boolean),
    selects: Array.from(document.querySelectorAll('select')).map(select => ({
      name: select.name,
      id: select.id,
      value: select.value,
      options: Array.from(select.options).map(option => ({
        text: option.textContent.trim(),
        value: option.value,
      })),
    })),
    samples: cards.slice(0, 2).map(card => ({
      leftText: card.querySelector('.col-sm-7')?.innerText || '',
      rightText: card.querySelector('.col-sm-5')?.innerText || '',
      salaryText: card.querySelector('.job-salary')?.textContent?.trim() || null,
    })),
  }));
  const downloadPromise = page.waitForEvent('download');
  await page.evaluate(payload => {
    const link = document.createElement('a');
    link.href = `data:application/json;charset=utf-8,${encodeURIComponent(JSON.stringify(payload, null, 2))}`;
    link.download = 'higheredjobs_browser_probe.json';
    link.click();
  }, result);
  const download = await downloadPromise;
  await download.saveAs('outputs/higheredjobs_browser_probe.json');
}
