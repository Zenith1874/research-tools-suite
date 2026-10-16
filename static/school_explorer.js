(function () {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const known = (value, fallback = 'Unknown') => value == null || value === '' ? fallback : String(value);
  const number = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '—';
  const state = { query: {}, selected: new Set(), offset: 0, limit: 30, aacsbQuery: {}, aacsbOffset: 0, aacsbLimit: 30 };
  const api = async (url, options) => { const response = await fetch(url, options); let data = {}; try { data = await response.json(); } catch (e) {} if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`); return data; };
  const badge = (value, tone = '') => value == null || value === '' ? '' : `<span class="fc-badge ${tone}">${esc(known(value))}</span>`;

  function queryString() { const params = new URLSearchParams({ limit: state.limit, offset: state.offset }); Object.entries(state.query).forEach(([key, value]) => { if (value) params.set(key, value); }); return params.toString(); }

  function footprintLine(footprint) {
    // Shown as its own observation with its coverage. It is deliberately not
    // folded into the tier badge: the count comes from a partially backfilled
    // corpus, and presenting it as a tier would overstate what was measured.
    if (!footprint) return '';
    const coverage = footprint.coverage_pct === null || footprint.coverage_pct === undefined
      ? 'coverage unknown'
      : `${esc(String(footprint.coverage_pct))}% of corpus`;
    const window = footprint.covered_window ? ` · ${esc(footprint.covered_window)}` : '';
    const tone = footprint.counts_toward_tier ? 'purple' : 'amber';
    return `<div class="fc-badges se-footprint"><span class="fc-badge ${tone}">${esc(footprint.label)} (institution-level floor): ${esc(String(footprint.articles))}</span><span class="fc-small">${coverage}${window} · not an official ranking · ${footprint.counts_toward_tier ? 'counted in tier' : 'not counted in tier'}</span></div>`;
  }

  function schoolCard(school) {
    const id = school.id; const tier = school.business_research_tier || 'Unclassified'; const level = school.university_research_level || 'Unknown';
    const checked = state.selected.has(String(id)) ? ' checked' : '';
    const evidenceLabel = school.evidence_status === 'verified_school_evidence' ? 'Verified school evidence' : school.evidence_status === 'manual_school_override' ? 'Manual override' : 'Linked entity only';
    const evidenceTone = school.evidence_status === 'verified_school_evidence' ? 'green' : 'amber';
    return `<article class="fc-job-card"><div class="fc-inline-actions"><label class="fc-small"><input type="checkbox" data-school-select="${esc(id)}"${checked}> Compare</label>${badge(tier, tier === 'Unclassified' ? 'amber' : 'blue')}${badge(level, level === 'Unknown' ? 'amber' : 'green')}${badge(evidenceLabel, evidenceTone)}</div><h3><a href="#school-${esc(id)}" class="se-detail-link" data-school-id="${esc(id)}">${esc(known(school.official_name, 'Unnamed business school'))}</a></h3><div class="fc-job-institution">${esc(known(school.university_name, 'Unknown university'))}</div><div class="fc-job-meta"><span>⌖ ${esc([school.city, school.country].filter(Boolean).join(', ') || 'Unknown location')}</span><span>${number(school.current_openings)} current opening${Number(school.current_openings) === 1 ? '' : 's'}</span></div><div class="fc-badges">${badge(school.aacsb === 1 ? 'AACSB (current accreditation)' : '', 'green')}${badge(school.equis === 1 ? 'EQUIS (current)' : '', 'green')}${badge(school.amba === 1 ? 'AMBA (current)' : '', 'green')}${badge(school.doctoral_business_program === 1 ? 'Business PhD' : '', 'purple')}</div>${footprintLine(school.astar_footprint)}<div class="fc-job-foot"><span class="fc-small">Evidence: ${esc(school.evidence_status || 'Unknown')} · confidence: ${esc(known(school.business_research_tier_confidence, 'Low'))}</span><button class="fc-button secondary se-detail-button" type="button" data-school-id="${esc(id)}">Details</button></div></article>`;
  }

  function bindCards() {
    document.querySelectorAll('[data-school-select]').forEach((input) => input.addEventListener('change', () => {
      const id = input.dataset.schoolSelect; if (input.checked && state.selected.size >= 5) { input.checked = false; return; }
      if (input.checked) state.selected.add(id); else state.selected.delete(id); updateCompareLabel();
    }));
    document.querySelectorAll('[data-school-id]').forEach((node) => node.addEventListener('click', (event) => { event.preventDefault(); loadDetail(node.dataset.schoolId); }));
  }

  function updateCompareLabel() { $('se-compare').textContent = `Compare selected (${state.selected.size})`; }

  function renderList(payload) {
    const schools = payload.schools || []; const pagination = payload.pagination || {};
    $('se-count').textContent = `${number(pagination.total)} institution records`;
    $('se-list').innerHTML = schools.length ? schools.map(schoolCard).join('') : '<div class="fc-empty"><strong>No institution records</strong>Run a public job-source update first, or broaden the search.</div>';
    const pager = $('se-pager'); pager.innerHTML = ''; const label = document.createElement('span'); label.textContent = `${number(pagination.total)} records`;
    const actions = document.createElement('div'); actions.className = 'fc-pager-actions'; const prev = document.createElement('button'); prev.className = 'fc-button'; prev.textContent = 'Previous'; prev.disabled = state.offset <= 0; const next = document.createElement('button'); next.className = 'fc-button'; next.textContent = 'Next'; next.disabled = state.offset + schools.length >= Number(pagination.total || 0); prev.onclick = () => { state.offset = Math.max(0, state.offset - state.limit); loadList(); }; next.onclick = () => { state.offset += state.limit; loadList(); }; actions.append(prev, next); pager.append(label, actions); bindCards(); updateCompareLabel();
  }

  async function loadList() { $('se-list').innerHTML = '<div class="fc-loading">Loading schools…</div>'; try { renderList(await api(`/api/schools?${queryString()}`)); } catch (error) { $('se-list').innerHTML = `<div class="fc-note error">Could not load schools: ${esc(error.message)}</div>`; } }

  const aacsbStatusLabel = (value) => ({
    jobs_found: 'Public academic jobs found',
    no_current_jobs: 'No explicit current academic jobs parsed',
    no_eligible_business_faculty_jobs: 'Candidates found, none eligible for the business-faculty market',
    not_found: 'No public faculty entry discovered',
    not_checked: 'Not checked', blocked: 'Blocked/access challenge', unknown: 'Unknown/not verified'
  }[value] || known(value));

  function aacsbQueryString() {
    const params = new URLSearchParams({ limit: state.aacsbLimit, offset: state.aacsbOffset });
    Object.entries(state.aacsbQuery).forEach(([key, value]) => { if (value) params.set(key, value); });
    return params.toString();
  }

  function renderAacsbSummary(payload) {
    const summary = payload.summary || {};
    const statusText = (summary.current_rule_statuses || []).map((item) => `${aacsbStatusLabel(item.status)}: ${number(item.count)}`).join(' · ');
    $('se-aacsb-summary').innerHTML = [
      ['Accredited-path roster records', summary.total], ['Named school-unit records', summary.school_unit_records],
      ['Organization-level records', summary.organization_level_records], ['Linked school entities', summary.linked_school_entities],
      ['Directory results reported', summary.directory_results_reported],
      ['Non-accredited member results excluded', summary.non_accredited_results_excluded],
      ['Detail pages parsed', summary.detail_ok],
      ['Official websites exposed', summary.official_website], ['Legacy + current website checks', summary.website_checked],
      ['Checks under current rule version', summary.website_checked_current_rule],
      ['Stale / unchecked websites remaining', summary.stale_or_unchecked_websites],
      ['Legacy + current career pages found', summary.career_page_found], ['Legacy + current schools with postings', summary.jobs_found_schools],
      ['Postings extracted under current rule', summary.jobs_found_current_rule], ['Candidates seen under current rule', summary.candidates_seen_current_rule],
      ['Candidates rejected under current rule', summary.candidates_rejected_current_rule], ['Accepted job records', summary.accepted_job_records],
      ['Quarantined source-linked records', summary.quarantined_source_linked_records]
    ].map(([label, value]) => `<div class="fc-stat-row"><span>${esc(label)}</span><strong>${number(value)}</strong></div>`).join('') + `<div class="fc-small">${esc(summary.method_note || '')}</div><div class="fc-small">Current-rule school outcomes · ${esc(statusText || 'No scan status recorded yet.')}</div>`;
    $('se-aacsb-count').textContent = `${number(summary.total)} accredited-path records`;
    const scanButton = $('se-aacsb-scan');
    if (scanButton) {
      const remaining = Number(summary.stale_or_unchecked_websites || 0);
      scanButton.textContent = remaining > 0
        ? `Continue bounded current-rule scan (${number(remaining)} remaining)`
        : 'Recheck a bounded official-site batch';
    }
  }

  async function loadAacsbSummary() {
    try { renderAacsbSummary(await api('/api/faculty-jobs/aacsb/summary')); }
    catch (error) { $('se-aacsb-summary').innerHTML = `<div class="fc-note error">AACSB coverage unavailable: ${esc(error.message)}</div>`; }
  }

  function renderCountryOptions(payload) {
    const options = payload.country_options || [];
    if (!options.length) return;
    [['se-filter-form', 'All countries'], ['se-aacsb-filter-form', 'All countries']].forEach(([formId, placeholder]) => {
      const select = document.querySelector('#' + formId + ' select[name="country"]');
      if (!select) return;
      const current = select.value;
      select.innerHTML = '<option value="">' + esc(placeholder) + '</option>' + options.map((item) => '<option value="' + esc(String(item.code || '').toUpperCase()) + '">' + esc(known(item.label, item.code)) + '</option>').join('');
      if (Array.from(select.options).some((option) => option.value === current)) select.value = current;
    });
  }

  async function loadAacsbFilters() {
    try { renderCountryOptions(await api('/api/faculty-jobs/aacsb/filters')); }
    catch (error) { /* Keep the bounded static fallback options in the HTML. */ }
  }

  function renderAacsbDirectory(payload) {
    const schools = payload.schools || []; const pagination = payload.pagination || {};
    const currentRule = payload.current_scan_rule_version || '';
    const totalLabel = `${number(pagination.total)} matching roster schools`;
    $('se-aacsb-count').textContent = totalLabel;
    $('se-aacsb-list').innerHTML = schools.length ? schools.map((school) => {
      const website = school.official_website ? `<a class="fc-link" target="_blank" rel="noopener" href="${esc(school.official_website)}">Official site</a>` : 'Unknown';
      const career = school.career_page_url ? `<br><a class="fc-link" target="_blank" rel="noopener" href="${esc(school.career_page_url)}">Employment page</a>` : '';
      const stale = !school.scan_rule_version || school.scan_rule_version !== currentRule;
      const priorStatus = aacsbStatusLabel(school.job_scan_status);
      const status = stale ? `Recheck required · prior result: ${priorStatus}` : priorStatus;
      const tone = stale ? 'amber' : school.job_scan_status === 'jobs_found' ? 'green' : school.job_scan_status === 'not_checked' ? 'amber' : '';
      const rosterName = school.school_name || school.institution_name || 'Unnamed AACSB organization';
      const rosterParent = school.school_name ? known(school.institution_name, 'Unknown parent institution') : 'Organization-level AACSB record (no separate school-unit field in the public result)';
      return `<tr><td><strong>${esc(rosterName)}</strong><br><span class="fc-small">${esc(rosterParent)}</span><br><a class="fc-small fc-link" target="_blank" rel="noopener" href="${esc(school.directory_url)}">AACSB record</a></td><td>${esc([school.city, school.state_province, school.country].filter(Boolean).join(', ') || known(school.location_raw))}</td><td>${website}${career}</td><td>${badge(status, tone)}<br><span class="fc-small">${number(school.jobs_found)} eligible posting${Number(school.jobs_found) === 1 ? '' : 's'} · ${number(school.candidates_rejected)} rejected candidate${Number(school.candidates_rejected) === 1 ? '' : 's'} · ${esc(known(school.job_scan_reason, 'No scan explanation recorded'))}</span></td><td>${esc(known(school.website_checked_at || school.detail_checked_at, 'Not checked'))}</td></tr>`;
    }).join('') : '<tr><td colspan="5" class="fc-empty">No AACSB directory records match this filter.</td></tr>';
    const pager = $('se-aacsb-pager'); pager.innerHTML = '';
    const label = document.createElement('span'); label.textContent = totalLabel;
    const actions = document.createElement('div'); actions.className = 'fc-pager-actions';
    const prev = document.createElement('button'); prev.className = 'fc-button'; prev.textContent = 'Previous'; prev.disabled = state.aacsbOffset <= 0;
    const next = document.createElement('button'); next.className = 'fc-button'; next.textContent = 'Next'; next.disabled = state.aacsbOffset + schools.length >= Number(pagination.total || 0);
    prev.onclick = () => { state.aacsbOffset = Math.max(0, state.aacsbOffset - state.aacsbLimit); loadAacsbDirectory(); };
    next.onclick = () => { state.aacsbOffset += state.aacsbLimit; loadAacsbDirectory(); };
    actions.append(prev, next); pager.append(label, actions);
  }

  async function loadAacsbDirectory() {
    $('se-aacsb-list').innerHTML = '<tr><td colspan="5" class="fc-loading">Loading AACSB schools…</td></tr>';
    try { renderAacsbDirectory(await api(`/api/faculty-jobs/aacsb/directory?${aacsbQueryString()}`)); }
    catch (error) { $('se-aacsb-list').innerHTML = `<tr><td colspan="5" class="fc-note error">Could not load AACSB directory: ${esc(error.message)}</td></tr>`; }
  }

  async function runAacsbScan() {
    const raw = window.prompt('How many schools should the bounded public-site scan check?', '25');
    if (raw === null) return;
    const max_schools = Math.max(1, Math.min(200, Number(raw) || 25));
    try {
      const result = await api('/api/faculty-jobs/aacsb/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scan_existing: true, include_checked: false, max_schools, delay: 0.75, timeout: 20 }) });
      window.alert(`AACSB bounded scan started/completed: ${JSON.stringify(result).slice(0, 800)}`);
      loadAacsbSummary(); loadAacsbDirectory();
    } catch (error) { window.alert(`AACSB scan was not started: ${error.message}`); }
  }

  function detailField(label, value) { return `<div class="fc-detail-field"><div class="fc-detail-label">${esc(label)}</div><div class="fc-detail-value">${esc(known(value))}</div></div>`; }

  async function loadDetail(id) {
    const dialog = $('se-dialog'); const body = $('se-dialog-body'); if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', 'open'); body.innerHTML = '<div class="fc-loading">Loading evidence…</div>';
    try {
      const data = await api(`/api/schools/${encodeURIComponent(id)}`); const school = data.school || {}; const classification = school.classification || {}; const evidence = school.evidence || [];
      $('se-dialog-title').textContent = known(school.official_name, 'School detail');
      const evidenceRows = evidence.length ? `<div class="fc-table-wrap"><table class="fc-table"><thead><tr><th>Type</th><th>Value</th><th>Source</th><th>Confidence</th><th>Lifecycle</th></tr></thead><tbody>${evidence.map((item) => `<tr><td>${esc(item.evidence_type)}</td><td>${esc(item.value)}</td><td><a class="fc-link" target="_blank" rel="noopener" href="${esc(item.source_url)}">${esc(item.source_name || item.source_url)}</a></td><td>${esc(item.confidence || 'Unknown')}</td><td>${item.current || item.is_current === 1 ? 'Current' : `Historical${item.valid_to ? ` · through ${esc(item.valid_to)}` : ''}`}</td></tr>`).join('')}</tbody></table></div>` : '<div class="fc-empty">No verified evidence has been added.</div>';
      const manage = document.body.dataset.careerAccess === 'local' ? `<div class="fc-inline-actions fc-manage-only"><button class="fc-button success" id="se-add-evidence" type="button">Add official evidence</button><button class="fc-button secondary" id="se-override" type="button">Record tier override</button></div>` : '';
      body.innerHTML = `${manage}<div class="fc-detail-grid">${detailField('University', school.university_name)}${detailField('Business school', school.official_name)}${detailField('University research level', school.university_research_level)}${detailField('Country / state / city', [school.country, school.state_province, school.city].filter(Boolean).join(', '))}${detailField('Business tier', classification.tier || school.business_research_tier)}${detailField('Tier confidence', classification.confidence || school.business_research_tier_confidence)}${detailField('Evidence status', school.evidence_status_label)}${detailField('AACSB / EQUIS / AMBA', [school.aacsb === 1 ? 'AACSB (current)' : null, school.equis === 1 ? 'EQUIS (current)' : null, school.amba === 1 ? 'AMBA (current)' : null].filter(Boolean).join(', '))}${detailField('Business PhD', school.doctoral_business_program === 1 ? 'Yes' : school.doctoral_business_program === 0 ? 'No' : 'Unknown')}${detailField('Last verified', school.last_verified_at)}${detailField('Current openings', school.current_openings)}${detailField('Observed A* Publication Footprint (institution-level floor)', school.astar_footprint ? `${school.astar_footprint.articles} article(s)` : 'Not linked to the A* corpus')}</div>${school.astar_footprint ? `<div class="fc-note ${school.astar_footprint.counts_toward_tier ? 'info' : 'warn'}">${esc(school.astar_footprint.explanation)} This is an institution-level observed floor, not a ranking.${school.astar_footprint.source_url ? ` <a class="fc-link" href="${esc(school.astar_footprint.source_url)}" target="_blank" rel="noopener">OpenAlex ↗</a>` : ''}</div>` : ''}<div class="fc-note info">${esc(classification.reason || 'No classification reason.')}</div><h3>Evidence ledger</h3>${evidenceRows}<h3>Observed jobs</h3><div class="fc-table-wrap"><table class="fc-table"><thead><tr><th>Title</th><th>Discipline</th><th>Deadline</th><th>Status</th></tr></thead><tbody>${(school.jobs || []).map((job) => `<tr><td><a class="fc-link" href="/faculty-jobs?job_id=${esc(job.id)}">${esc(job.title_raw)}</a></td><td>${esc(known(job.discipline_primary))}</td><td>${esc(known(job.deadline_date))}</td><td>${esc(known(job.status))}</td></tr>`).join('') || '<tr><td colspan="4">No linked jobs.</td></tr>'}</tbody></table></div>`;
      const add = $('se-add-evidence'); if (add) add.onclick = () => addEvidence(id);
      const override = $('se-override'); if (override) override.onclick = () => saveOverride(id);
    } catch (error) { body.innerHTML = `<div class="fc-note error">Could not load school detail: ${esc(error.message)}</div>`; }
  }

  async function addEvidence(id) {
    const evidence_type = window.prompt('Evidence type (AACSB, EQUIS, AMBA, business_phd_program, official_research_profile, etc.)'); const value = window.prompt('Evidence value'); const source_url = window.prompt('Official source URL'); if (!evidence_type || !value || !source_url) return;
    try { await api(`/api/schools/${id}/enrich`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ evidence_type, value, source_url, confidence: 'medium' }) }); await loadDetail(id); }
    catch (error) { window.alert(`Evidence was not saved: ${error.message}`); }
  }

  async function saveOverride(id) {
    const tier = window.prompt('Tier override: T1, T2, T3, or T4'); const reason = window.prompt('Reason (at least 10 characters)'); const source_url = window.prompt('Official source URL documenting the override'); if (!tier || !reason || !source_url) return;
    try { await api(`/api/schools/${id}/override`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tier, reason, source_url }) }); await loadDetail(id); }
    catch (error) { window.alert(`Override was not saved: ${error.message}`); }
  }

  function renderAliases(payload) {
    const aliases = payload.aliases || [];
    $('se-aliases').innerHTML = aliases.length ? aliases.map((item) => `<div class="fc-stat-row"><span><strong>${esc(known(item.alias_normalized))}</strong> → ${esc(known(item.canonical_name))}<br><span class="fc-small">${esc(known(item.reason))}</span></span><span class="fc-small">${esc(known(item.updated_at))}</span></div>`).join('') : '<div class="fc-empty">No local institution aliases recorded.</div>';
  }

  async function loadAliases() {
    if (!$('se-aliases')) return;
    if (document.body.dataset.careerAccess !== 'local') return;
    try { renderAliases(await api('/api/institution-aliases?limit=200')); }
    catch (error) { $('se-aliases').innerHTML = `<div class="fc-note error">Alias ledger unavailable: ${esc(error.message)}</div>`; }
  }

  async function addAlias() {
    const alias = window.prompt('Source institution spelling / alias:');
    const canonical_name = window.prompt('Canonical institution name:');
    const reason = window.prompt('Reason and evidence boundary (at least 10 characters):');
    if (!alias || !canonical_name || !reason) return;
    const source_url = window.prompt('Optional official source URL:') || '';
    try {
      await api('/api/institution-aliases', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ alias, canonical_name, reason, source_url }) });
      await loadAliases();
    } catch (error) { window.alert(`Alias was not saved: ${error.message}`); }
  }

  async function compare() {
    if (!state.selected.size) { $('se-compare-table').innerHTML = '<div class="fc-empty">Select at least one school.</div>'; return; }
    try { const data = await api(`/api/schools/compare?ids=${encodeURIComponent(Array.from(state.selected).join(','))}`); const schools = (data.schools || []).filter(Boolean).map((school) => ({ ...school, astar_footprint_articles: school.astar_footprint ? `${school.astar_footprint.articles} (${school.astar_footprint.coverage_pct}% of corpus; institution-level floor)` : 'Not linked' })); $('se-compare-table').innerHTML = `<table class="fc-table"><thead><tr><th>Dimension</th>${schools.map((school) => `<th>${esc(school.official_name)}<br><span class="fc-muted">${esc(school.university_name)}</span></th>`).join('')}</tr></thead><tbody>${[['University research level', 'university_research_level'], ['Business tier', 'business_research_tier'], ['Tier confidence', 'business_research_tier_confidence'], ['Evidence status', 'evidence_status_label'], ['AACSB (current)', 'aacsb'], ['EQUIS (current)', 'equis'], ['AMBA (current)', 'amba'], ['Business PhD', 'doctoral_business_program'], ['Observed A* floor (institution-level; not a ranking)', 'astar_footprint_articles'], ['Current openings', 'current_openings'], ['Country / city', 'country'], ['Last verified', 'last_verified_at']].map(([label, key]) => `<tr><th>${esc(label)}</th>${schools.map((school) => `<td>${esc(known(school[key] === 1 ? 'Yes' : school[key] === 0 ? 'No' : school[key]))}</td>`).join('')}</tr>`).join('')}</tbody></table>`; } catch (error) { $('se-compare-table').innerHTML = `<div class="fc-note error">Could not compare: ${esc(error.message)}</div>`; }
  }

  document.addEventListener('DOMContentLoaded', async () => {
    try {
      const access = await api('/api/faculty-jobs/capabilities');
      document.body.dataset.careerAccess = access.personal && access.manage ? 'local' : 'public';
    } catch (_) { document.body.dataset.careerAccess = 'public'; }
    $('se-filter-form').addEventListener('submit', (event) => { event.preventDefault(); state.query = Object.fromEntries(new FormData(event.currentTarget).entries()); state.offset = 0; loadList(); });
    $('se-reset').addEventListener('click', () => { $('se-filter-form').reset(); state.query = {}; state.offset = 0; loadList(); });
    $('se-aacsb-filter-form').addEventListener('submit', (event) => { event.preventDefault(); state.aacsbQuery = Object.fromEntries(new FormData(event.currentTarget).entries()); state.aacsbOffset = 0; loadAacsbDirectory(); });
    $('se-aacsb-reset').addEventListener('click', () => { $('se-aacsb-filter-form').reset(); state.aacsbQuery = {}; state.aacsbOffset = 0; loadAacsbDirectory(); });
    $('se-compare').addEventListener('click', compare); $('se-dialog-close').addEventListener('click', () => $('se-dialog').close());
    const aliasButton = $('se-add-alias'); if (aliasButton) aliasButton.addEventListener('click', addAlias);
    const aacsbScan = $('se-aacsb-scan'); if (aacsbScan) aacsbScan.addEventListener('click', runAacsbScan);
    loadList(); loadAliases(); loadAacsbFilters(); loadAacsbSummary(); loadAacsbDirectory();
  });
})();
