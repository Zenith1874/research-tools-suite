async page => {
  const baseUrl = 'https://www.higheredjobs.com/faculty/search.cfm?JobCat=232&CatName=Business';
  const outputPath = 'outputs/higheredjobs_business_snapshot_20260828T233300Z.json';
  const pageSize = 100;
  const pageDelayMs = 2000;
  const pages = [];
  const jobs = [];
  let reportedTotal = null;
  let requiredPages = null;

  for (let pageNumber = 1; requiredPages === null || pageNumber <= requiredPages; pageNumber += 1) {
    const pageUrl = `${baseUrl}&NumJobs=${pageSize}&Page=${pageNumber}`;
    await page.goto(pageUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
    const bodyText = await page.locator('body').innerText();
    const lowered = bodyText.toLowerCase();
    if (lowered.includes('pardon our interruption') || lowered.includes('captcha')) {
      throw new Error(`HigherEdJobs browser page ${pageNumber} returned a challenge; no snapshot written`);
    }
    await page.waitForSelector('div.row.record', { timeout: 20000 });

    const extracted = await page.evaluate(() => {
      const text = document.body.innerText.replace(/\s+/g, ' ').trim();
      const rangeMatch = text.match(/\bResults\s+(\d[\d,]*)\s*[-–]\s*(\d[\d,]*)\s+of\s+(\d[\d,]*)\b/i);
      const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
      const cards = Array.from(document.querySelectorAll('div.row.record')).map(card => {
        const anchor = card.querySelector('a[href*="details.cfm?JobCode="]');
        const sourceUrl = anchor ? new URL(anchor.getAttribute('href'), location.href).href : '';
        const sourceJobId = sourceUrl ? new URL(sourceUrl).searchParams.get('JobCode') : '';
        const title = clean(anchor?.textContent);
        const left = card.querySelector('.col-sm-7');
        const salary = clean(left?.querySelector('.job-salary')?.textContent);
        const leftValues = String(left?.innerText || '').split(/\n+/).map(clean).filter(Boolean);
        const remaining = leftValues.filter(value => (
          value.toLowerCase() !== title.toLowerCase()
          && (!salary || value.toLowerCase() !== salary.toLowerCase())
          && value.toLowerCase() !== 'save job'
        ));
        const institution = remaining[0] || '';
        // Some cards insert a department or campus line between institution
        // and location. The final non-salary line is the board's location;
        // keeping the middle lines separately prevents "College of Business"
        // from becoming the city while retaining the source evidence.
        const locationText = remaining.length > 1 ? remaining[remaining.length - 1] : null;
        const middleLines = remaining.length > 2 ? remaining.slice(1, -1) : [];
        const right = card.querySelector('.col-sm-5');
        const category = clean(right?.querySelector('.text-nowrap')?.textContent);
        const rightText = clean(right?.innerText);
        const postedMatch = rightText.match(/\bPosted\s+(?:today|yesterday|\d+\s+(?:hours?|days?|weeks?|months?)\s+ago|[A-Za-z]+\s+\d{1,2},\s+\d{4}|\d{1,2}\/\d{1,2}\/\d{2,4})\b/i);
        const cardText = clean(card.innerText);
        return {
          source_job_id: clean(sourceJobId),
          source_url: sourceUrl,
          title_raw: title,
          institution_raw: institution,
          location_raw: locationText,
          description_excerpt: clean(`${category ? `HigherEdJobs category: ${category}. ` : ''}${cardText}`).slice(0, 2000),
          posted_date_raw: postedMatch ? postedMatch[0] : null,
          salary_raw: salary || null,
          official_url: null,
          extra: {
            source_category: category || null,
            source_priority_listing: Boolean(card.querySelector('.addon-marker')),
            source_middle_lines: middleLines,
          },
        };
      });
      return {
        range: rangeMatch ? rangeMatch.slice(1).map(value => Number(value.replace(/,/g, ''))) : null,
        cards,
      };
    });

    if (!extracted.range) {
      throw new Error(`HigherEdJobs browser page ${pageNumber} exposed no parseable result range`);
    }
    const [start, end, observedTotal] = extracted.range;
    if (reportedTotal === null) {
      reportedTotal = observedTotal;
      requiredPages = Math.ceil(reportedTotal / pageSize);
    } else if (observedTotal !== reportedTotal) {
      throw new Error(
        `HigherEdJobs total changed during capture: ${reportedTotal} -> ${observedTotal}; no snapshot written`,
      );
    }
    const expectedStart = ((pageNumber - 1) * pageSize) + 1;
    const expectedEnd = Math.min(pageNumber * pageSize, reportedTotal);
    if (start !== expectedStart || end !== expectedEnd) {
      throw new Error(
        `HigherEdJobs page ${pageNumber} reported range ${start}-${end}; expected ${expectedStart}-${expectedEnd}`,
      );
    }
    if (extracted.cards.length !== end - start + 1) {
      throw new Error(
        `HigherEdJobs page ${pageNumber} exposed ${extracted.cards.length} cards for range ${start}-${end}`,
      );
    }
    const invalid = extracted.cards.find(job => (
      !job.source_job_id || !job.source_url || !job.title_raw || !job.institution_raw
    ));
    if (invalid) {
      throw new Error(`HigherEdJobs page ${pageNumber} contained an incomplete listing card`);
    }
    const capturedAt = new Date().toISOString();
    extracted.cards.forEach(job => jobs.push({ ...job, captured_at: capturedAt }));
    pages.push({ page: pageNumber, url: pageUrl, start, end, cards: extracted.cards.length, captured_at: capturedAt });
    if (pageNumber < requiredPages) {
      await page.waitForTimeout(pageDelayMs);
    }
  }

  const distinctCodes = new Set(jobs.map(job => job.source_job_id));
  if (jobs.length !== reportedTotal || distinctCodes.size !== reportedTotal) {
    throw new Error(
      `HigherEdJobs reported ${reportedTotal}; captured ${jobs.length} cards / ${distinctCodes.size} unique JobCodes`,
    );
  }

  const snapshot = {
    source: 'higheredjobs',
    source_url: baseUrl,
    capture_method: 'ordinary_visible_browser_pagination',
    captured_at: new Date().toISOString(),
    reported_total: reportedTotal,
    page_size: pageSize,
    pages_fetched: pages.length,
    coverage_complete: true,
    detail_pages_fetched: 0,
    policy_note: 'Public listing pages only; no login, CAPTCHA solving, challenge-token replay, or detail-page crawl.',
    pages,
    jobs,
  };
  const downloadPromise = page.waitForEvent('download');
  await page.evaluate(payload => {
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'higheredjobs_business_snapshot_20260828T233300Z.json';
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }, snapshot);
  const download = await downloadPromise;
  await download.saveAs(outputPath);
}
