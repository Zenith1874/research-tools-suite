(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const initialQuery = Object.fromEntries(new URLSearchParams(window.location.search).entries());
  const state = { offset: 0, limit: 20, query: { scope: 'business', ...initialQuery } };
  const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const known = (value, fallback = 'Unknown') => value == null || value === '' || value === 'unknown' ? fallback : String(value);
  const number = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '—';
  const pct = (value) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : 'Unknown';
  const dateText = (value) => value ? String(value).slice(0, 10) : 'Unknown';
  const api = async (url, options) => {
    const response = await fetch(url, options);
    let payload = {};
    try { payload = await response.json(); } catch (error) { payload = {}; }
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  };
  const badge = (value, tone = '') => value && value !== 'unknown' ? `<span class="fc-badge ${tone}">${esc(value)}</span>` : '';

  function setNote(message, tone = 'info') {
    const node = $('fc-boundary');
    if (node) { node.className = `fc-note ${tone}`; node.textContent = message; }
  }

  function buildQuery() {
    const params = new URLSearchParams();
    Object.keys(state.query).forEach((key) => { if (state.query[key]) params.set(key, state.query[key]); });
    params.set('limit', state.limit);
    params.set('offset', state.offset);
    return params.toString();
  }

  function scopedEndpoint(path) {
    const params = new URLSearchParams();
    Object.entries(state.query).forEach(([key, value]) => {
      if (!value || ['offset', 'limit', 'sort'].includes(key)) return;
      params.set(key, value);
    });
    if (!params.has('scope')) params.set('scope', 'business');
    return `${path}?${params.toString()}`;
  }

  function scopeLabel(scope) {
    return ({
      business: 'Business school / business discipline',
      business_school: 'Explicit business-school evidence',
      all: 'All observed postings (audit)',
    })[scope] || 'Business view';
  }

  function renderSummary(payload) {
    const summary = payload.summary || {};
    const coverage = summary.coverage || {};
    const currentScope = summary.scope || state.query.scope;
    const auditView = currentScope === 'all';
    const cards = [
      [auditView ? 'Active observed' : 'Active jobs', number(summary.active_jobs), 'Observed active or likely-open postings'],
      ['New · 7 days', number(summary.new_7d), 'First observed in the local snapshot'],
      ['Closing · 14 days', number(summary.closing_next_14d), 'Fixed deadlines parsed from sources'],
      ['United States', number((summary.by_region || []).find((x) => x.label === 'United States')?.count), 'Source-reported or fallback location'],
      ['Canada', number((summary.by_region || []).find((x) => x.label === 'Canada')?.count), 'Canada public board coverage'],
      ['Europe', number((summary.by_region || []).find((x) => x.label === 'Europe')?.count), 'Europe public source coverage'],
    ];
    $('fc-summary').innerHTML = cards.map((card) => `<div class="fc-kpi"><div class="fc-kpi-value">${esc(card[1])}</div><div class="fc-kpi-label">${esc(card[0])}</div><div class="fc-kpi-note">${esc(card[2])}</div></div>`).join('');
    $('fc-last-updated').textContent = `Snapshot read ${new Date().toLocaleString()}`;
    $('fc-private-state').textContent = scopeLabel(currentScope);
    $('fc-jobs-title').textContent = auditView ? 'Observed source catalogue (audit)' : 'Open and recently observed business jobs';
    const recordLabel = auditView ? 'observed source records, including excluded roles' : 'role-eligible observed jobs';
    $('fc-boundary').textContent = `Scope: ${scopeLabel(currentScope)} · ${number(coverage.jobs)} ${recordLabel} · official application URL ${pct(coverage.official_url_percent)} · fixed/rolling deadline ${pct(coverage.deadline_percent)} · salary evidence ${pct(coverage.salary_percent)} · possible duplicates ${number(coverage.possible_duplicates)}.`;
    $('fc-job-count').textContent = `${number(coverage.jobs)} filtered records; the page below may be paginated.`;
    updateExportLink();
  }

  function optionValues(selectId, values, label) {
    const select = $(selectId);
    if (!select) return;
    const first = select.options[0];
    select.innerHTML = '';
    select.appendChild(first);
    (values || []).filter(Boolean).forEach((value) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = label ? label(value) : value;
      select.appendChild(option);
    });
  }

  async function loadFilters() {
    const payload = await api(scopedEndpoint('/api/faculty-jobs/filters'));
    const filters = payload.filters || {};
    optionValues('fc-discipline', filters.disciplines);
    optionValues('fc-rank', filters.ranks);
    optionValues('fc-track', filters.tracks);
    optionValues('fc-country', filters.countries);
    optionValues('fc-state', filters.states_provinces);
    optionValues('fc-career-stage', filters.career_stages);
    optionValues('fc-status', filters.statuses);
    optionValues('fc-school-tier', filters.school_tiers);
    optionValues('fc-university-level', filters.university_levels);
    const countryLabels = Object.fromEntries((filters.country_options || []).map((item) => [String(item.code || '').toUpperCase(), item.label]));
    Object.entries(state.query).forEach(([key, value]) => {
      const field = $('fc-filter-form').elements.namedItem(key);
      const formValue = key === 'country' ? (countryLabels[String(value).toUpperCase()] || value) : value;
      if (field && formValue) field.value = formValue;
    });
    const regions = [''].concat(filters.regions || []);
    $('fc-regions').innerHTML = regions.map((region) => `<button type="button" class="fc-chip ${(state.query.region || '') === region ? 'is-active' : ''}" data-region="${esc(region)}">${esc(region || 'All regions')}</button>`).join('');
    $('fc-regions').querySelectorAll('[data-region]').forEach((button) => button.addEventListener('click', () => {
      state.query.region = button.dataset.region || ''; state.offset = 0;
      $('fc-regions').querySelectorAll('.fc-chip').forEach((item) => item.classList.toggle('is-active', item === button));
      syncUrl(); loadSummary(); loadJobs();
    }));
  }

  function renderSources(payload) {
    const sources = payload.sources || [];
    if (!sources.length) { $('fc-sources').innerHTML = '<div class="fc-empty">No source catalog yet.</div>'; return; }
    $('fc-sources').innerHTML = sources.map((source) => {
      const active = number(source.active_jobs);
      const business = number(source.business_scope_jobs);
      const tone = source.last_status === 'ok' && source.support_status !== 'opt_in' ? 'green' : ['manual', 'opt_in'].includes(source.support_status) ? 'amber' : source.last_status === 'error' ? 'red' : '';
      const reason = source.support_reason || (source.last_status === 'ok' ? 'Last run succeeded.' : 'Not refreshed yet.');
      const fields = source.field_coverage || {};
      const field = (key, label) => `${label} ${pct(fields[key]?.percent)}`;
      return `<div class="fc-stat-row"><span title="${esc(reason)}">${esc(source.name)}</span><span class="fc-stat-bar"><span style="width:${Math.min(100, Number(source.active_jobs || 0) / 2)}%"></span></span><span class="fc-stat-count">${active}</span></div><div class="fc-small">Raw active records: ${active} · business-scope records: ${business} · explicit school: ${number(source.explicit_school_jobs)} · field coverage: ${field('deadline_or_rolling', 'deadline')} · ${field('salary', 'salary')} · ${field('official_url', 'official URL')} · ${field('posted_date', 'posted')}<br>${badge(source.support_status || source.last_status, tone)} ${esc(reason)}</div>`;
    }).join('');
  }

  function jobCard(job) {
    const title = known(job.title_raw, 'Untitled academic job');
    const institution = known(job.institution_name || job.institution_raw, 'Unknown institution');
    const location = [job.city, job.state_province, job.country].filter(Boolean).join(', ') || 'Unknown location';
    const deadline = job.deadline_date ? `Deadline ${dateText(job.deadline_date)}` : known(job.deadline_mode, 'Deadline unknown');
    const sourceCount = Array.isArray(job.sources) ? new Set(job.sources.map((item) => item.name)).size : 0;
    const official = job.official_url ? `<a class="fc-link" href="${esc(job.official_url)}" target="_blank" rel="noopener">Official posting ↗</a>` : '<span>Official link unknown</span>';
    const school = job.business_research_tier || job.school_tier || 'Unclassified';
    const scope = job.business_scope || 'unknown';
    const scopeText = ({
      business_school: 'Business school evidence',
      business_discipline: 'Business discipline · school unverified',
      non_business: 'Excluded: non-business',
      non_academic: 'Excluded: non-academic',
    })[scope] || 'Business scope unknown';
    const scopeTone = scope === 'business_school' ? 'blue' : scope === 'business_discipline' ? 'green' : 'amber';
    const detail = `<button class="fc-button secondary fc-detail-button" type="button" data-job-id="${esc(job.id)}">Details</button>`;
    return `<article class="fc-job-card"><h3><a href="#job-${esc(job.id)}" class="fc-detail-link" data-job-id="${esc(job.id)}">${esc(title)}</a></h3><div class="fc-job-institution">${esc(institution)}</div><div class="fc-job-meta"><span>⌖ ${esc(location)}</span><span>Observed ${esc(dateText(job.first_seen_at))}</span><span>${esc(deadline)}</span></div><div class="fc-badges">${badge(scopeText, scopeTone)}${badge(job.faculty_market_role || 'faculty role', 'blue')}${badge(job.rank_normalized || job.career_stage, 'blue')}${badge(job.discipline_primary, 'purple')}${badge(job.track_type, 'green')}${badge(school, school === 'Unclassified' ? 'amber' : 'blue')}${badge(job.status, job.status === 'closed' ? 'red' : 'green')}</div><div class="fc-job-foot"><span>${number(sourceCount)} source${sourceCount === 1 ? '' : 's'} · ${esc(known(job.country, 'Country unknown'))} · ${esc(known(job.school_evidence_label, 'School evidence unknown'))}</span><span class="fc-inline-actions">${official}${detail}</span></div></article>`;
  }

  function renderJobs(payload) {
    const jobs = payload.jobs || [];
    $('fc-jobs').innerHTML = jobs.length ? jobs.map(jobCard).join('') : '<div class="fc-empty"><strong>No jobs match these filters</strong>Try a wider region or remove a discipline/rank filter.</div>';
    $('fc-pager').innerHTML = '';
    const page = payload.pagination || { total: 0, offset: 0, limit: state.limit, has_more: false };
    const label = document.createElement('span');
    label.textContent = `${number(page.total)} results · ${page.total ? `${page.offset + 1}–${Math.min(page.total, page.offset + jobs.length)}` : '0'}`;
    const actions = document.createElement('div'); actions.className = 'fc-pager-actions';
    const previous = document.createElement('button'); previous.className = 'fc-button'; previous.textContent = 'Previous'; previous.disabled = state.offset <= 0;
    const next = document.createElement('button'); next.className = 'fc-button'; next.textContent = 'Next'; next.disabled = !page.has_more;
    previous.addEventListener('click', () => { state.offset = Math.max(0, state.offset - state.limit); loadJobs(); });
    next.addEventListener('click', () => { state.offset += state.limit; loadJobs(); });
    actions.append(previous, next); $('fc-pager').append(label, actions);
    document.querySelectorAll('[data-job-id]').forEach((node) => node.addEventListener('click', (event) => { event.preventDefault(); loadDetail(node.dataset.jobId); }));
    updateExportLink();
  }

  async function loadJobs() {
    $('fc-jobs').innerHTML = '<div class="fc-loading">Loading public job snapshot…</div>';
    try { renderJobs(await api(`/api/faculty-jobs?${buildQuery()}`)); }
    catch (error) { $('fc-jobs').innerHTML = `<div class="fc-note error">Could not load jobs: ${esc(error.message)}</div>`; }
  }

  function detailField(label, value) { return `<div class="fc-detail-field"><div class="fc-detail-label">${esc(label)}</div><div class="fc-detail-value">${esc(known(value))}</div></div>`; }

  async function loadDetail(id) {
    const dialog = $('fc-detail-dialog'); const body = $('fc-detail-body');
    $('fc-detail-title').textContent = 'Job detail'; body.innerHTML = '<div class="fc-loading">Loading source-backed detail…</div>';
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', 'open');
    try {
      const payload = await api(`/api/faculty-jobs/${encodeURIComponent(id)}`); const job = payload.job || {};
      $('fc-detail-title').textContent = known(job.title_raw, 'Job detail');
      const sourceLinks = (job.sources || []).map((source) => `<li><a class="fc-link" href="${esc(source.source_url)}" target="_blank" rel="noopener">${esc(source.name)} listing</a> · ${esc(source.active ? 'active' : 'inactive')}${source.official_url ? ` · <a class="fc-link" href="${esc(source.official_url)}" target="_blank" rel="noopener">official application</a>` : ' · official application URL unknown'}</li>`).join('');
      const manage = document.body.dataset.accessMode === 'manage';
      const action = manage ? `<button class="fc-button success" id="fc-save-job" type="button">Save to My Applications</button><button class="fc-button secondary" id="fc-include-scope" type="button">Include in business view</button><button class="fc-button danger" id="fc-exclude-scope" type="button">Exclude from business view</button>` : '';
      const overrideText = job.scope_override ? `${job.scope_override.action}: ${job.scope_override.reason || 'reason not provided'}` : 'None';
      body.innerHTML = `<div class="fc-inline-actions">${job.official_url ? `<a class="fc-button primary" href="${esc(job.official_url)}" target="_blank" rel="noopener">Open official application ↗</a>` : ''}${action}</div><div class="fc-detail-grid">${detailField('Original title', job.original_title || job.title_raw)}${detailField('Institution', job.institution_name)}${detailField('Business school', job.business_school_name || 'No posting-level school extracted')}${detailField('Faculty-market role', job.faculty_market_role)}${detailField('Role eligibility evidence', job.faculty_market_reason)}${detailField('Business scope', job.business_scope)}${detailField('Business-scope evidence', job.business_scope_reason)}${detailField('School evidence context', job.school_evidence_context)}${detailField('Manual scope override', overrideText)}${detailField('School evidence', job.school_evidence_label)}${detailField('Department', job.department)}${detailField('Location', [job.city, job.state_province, job.country].filter(Boolean).join(', '))}${detailField('Rank mapping', job.rank_normalized)}${detailField('Career stage', job.career_stage)}${detailField('Discipline', job.discipline_primary)}${detailField('Research areas', (job.research_areas || []).join(', '))}${detailField('Teaching areas', (job.teaching_areas || []).join(', '))}${detailField('Track / contract', job.track_type)}${detailField('Start term / year', [job.start_term, job.start_year].filter(Boolean).join(' / '))}${detailField('Deadline', job.deadline_date || job.deadline_mode)}${detailField('Deadline evidence', job.deadline_evidence)}${detailField('Salary evidence', job.salary_raw)}${detailField('PhD evidence', job.phd_required === 1 ? 'Required' : job.phd_required === 0 ? 'Not required' : 'Unknown')}${detailField('Visa evidence', job.visa_status)}${detailField('Language', job.language_requirements)}${detailField('University level', job.university_level)}${detailField('Business tier', job.school_tier)}${detailField('First seen', job.first_seen_at)}${detailField('Last checked', job.last_seen_at)}${detailField('Extraction confidence', [job.business_scope_confidence, job.rank_mapping_confidence, job.location_evidence].filter(Boolean).join(' · '))}</div><h3>Source excerpt</h3><div class="fc-pre">${esc(job.description_excerpt || 'No excerpt captured from the public listing.')}</div><h3>Status history</h3><ul class="fc-small">${(job.status_history || []).map((item) => `<li>${esc(item.observed_at)} · ${esc(item.status)} · ${esc(item.change_reason || '')}</li>`).join('') || '<li>Unknown</li>'}</ul><h3>Source links</h3><ul class="fc-small">${sourceLinks || '<li>Source link unavailable.</li>'}</ul><p class="fc-small">Rank explanation: ${esc(job.rank_mapping_explanation || 'Unknown')} Classification: ${esc(job.classification_reason || 'Unknown')} Deadline parsing: ${esc(job.deadline_parse_reason || 'Unknown')}.</p>`;
      const save = $('fc-save-job'); if (save) save.addEventListener('click', async () => {
        try { await api('/api/my-applications', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: Number(id), state: 'Saved' }) }); save.textContent = 'Saved locally'; save.disabled = true; }
        catch (error) { setNote(`Could not save locally: ${error.message}`, 'error'); }
      });
      const saveScope = async (scopeAction) => {
        const reason = window.prompt(`Reason for ${scopeAction}ing this posting in the business view:`);
        if (!reason) return;
        const sourceUrl = window.prompt('Optional evidence URL (leave blank if this is a local review):') || '';
        try { await api(`/api/faculty-jobs/${encodeURIComponent(id)}/scope-override`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: scopeAction, reason, source_url: sourceUrl }) }); dialog.close(); await loadDetail(id); setNote('Local scope override saved and audited.', 'success'); }
        catch (error) { setNote(`Could not save scope override: ${error.message}`, 'error'); }
      };
      const include = $('fc-include-scope'); if (include) include.addEventListener('click', () => saveScope('include'));
      const exclude = $('fc-exclude-scope'); if (exclude) exclude.addEventListener('click', () => saveScope('exclude'));
    } catch (error) { body.innerHTML = `<div class="fc-note error">Could not load detail: ${esc(error.message)}</div>`; }
  }

  async function updateSources() {
    const button = $('fc-update'); button.disabled = true; button.textContent = 'Update started…';
    try { const result = await api('/api/faculty-jobs/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ max_pages: 1 }) }); setNote(result.message || 'Update started in the background. The previous snapshot remains available.', 'success'); setTimeout(loadAll, 2500); }
    catch (error) { setNote(`Update could not start: ${error.message}`, 'error'); }
    finally { button.disabled = false; button.textContent = 'Update public sources'; }
  }

  async function saveCurrentSearch() {
    const name = window.prompt('Name for this local saved search:');
    if (!name || !name.trim()) return;
    const button = $('fc-save-search');
    if (button) button.disabled = true;
    try {
      const result = await api('/api/faculty-jobs/saved-searches', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), query: { ...state.query } }),
      });
      const count = result.saved_search?.new_alert_count ?? 0;
      setNote(`Saved locally. ${count} new matching alert${Number(count) === 1 ? '' : 's'} are in My Applications.`, 'success');
    } catch (error) {
      setNote(`Saved search was not saved: ${error.message}`, 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function bind() {
    $('fc-filter-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); const nextQuery = Object.fromEntries(form.entries()); state.query = { ...nextQuery, region: state.query.region || '' }; state.offset = 0; syncUrl(); await loadFilters(); await loadSummary(); loadJobs(); });
    $('fc-reset').addEventListener('click', () => { $('fc-filter-form').reset(); state.query = { scope: 'business', region: '' }; state.offset = 0; syncUrl(); loadFilters().then(loadSummary).then(loadJobs); });
    $('fc-update').addEventListener('click', updateSources);
    const saveSearch = $('fc-save-search'); if (saveSearch) saveSearch.addEventListener('click', saveCurrentSearch);
    $('fc-detail-close').addEventListener('click', () => $('fc-detail-dialog').close());
    $('fc-detail-dialog').addEventListener('click', (event) => { if (event.target === $('fc-detail-dialog')) $('fc-detail-dialog').close(); });
  }

  async function loadSummary() {
    try { renderSummary(await api(scopedEndpoint('/api/faculty-jobs/summary'))); } catch (error) { setNote(`Summary unavailable: ${error.message}`, 'error'); }
  }

  async function loadAll() {
    await loadSummary();
    try { await loadFilters(); } catch (error) { setNote(`Filters unavailable: ${error.message}`, 'error'); }
    try { renderSources(await api('/api/faculty-jobs/sources')); } catch (error) { $('fc-sources').innerHTML = `<div class="fc-note error">Source health unavailable: ${esc(error.message)}</div>`; }
    await loadJobs();
  }

  function syncUrl() {
    const params = new URLSearchParams();
    Object.entries(state.query).forEach(([key, value]) => { if (value) params.set(key, value); });
    params.set('offset', state.offset);
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`);
    updateExportLink();
  }

  function updateExportLink() {
    const link = $('fc-export');
    if (!link) return;
    const params = new URLSearchParams();
    Object.entries(state.query).forEach(([key, value]) => { if (value) params.set(key, value); });
    link.href = `/api/faculty-jobs/export.csv?${params.toString()}`;
  }

  document.addEventListener('DOMContentLoaded', () => {
    bind();
    loadAll();
    const jobId = new URLSearchParams(window.location.search).get('job_id');
    if (jobId) setTimeout(() => loadDetail(jobId), 250);
  });
})();
