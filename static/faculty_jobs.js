(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const initialQuery = Object.fromEntries(new URLSearchParams(window.location.search).entries());
  const PREFERRED = { scope: 'business_school', country: 'US', career_view: 'r2_teaching', discipline: 'Information Systems / MIS,Management,Organizational Behavior / HR' };
  const hasExplicitFilters = Object.keys(initialQuery).some(key => !['offset', 'limit', 'job_id'].includes(key));
  const state = { offset: Math.max(0, Number(initialQuery.offset) || 0), limit: 20, careerBusy: false, jobRequest: 0, query: { ...(hasExplicitFilters ? { scope: 'business_school', career_view: initialQuery.university_level ? 'all' : 'r2_teaching' } : PREFERRED), ...initialQuery } };
  delete state.query.offset; delete state.query.limit; delete state.query.job_id;
  const POSITIONS = { tt: 'TT / Tenured', teaching: 'Teaching', clinical: 'Clinical', adjunct: 'Adjunct', other: '其他／未确认' };
  const ACTIONS = { new: '新发现', worth_review: '值得看', review_soon: '即将审查', needs_verification: '需要核验' };
  let sourcesLoaded = false;
  const esc = (value) => String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[char]));
  const known = (value, fallback = 'Unknown') => value == null || value === '' || value === 'unknown' ? fallback : String(value);
  const number = (value) => Number.isFinite(Number(value)) ? Number(value).toLocaleString() : '—';
  const pct = (value) => Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)}%` : 'Unknown';
  const dateText = (value) => value ? String(value).includes('T') && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleDateString('zh-CN') : String(value).slice(0, 10) : 'Unknown';
  const timeText = (value) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' }) : '尚未成功核验';
  const api = async (url, options) => {
    const response = await fetch(url, options);
    let payload = {};
    try { payload = await response.json(); } catch (error) { payload = {}; }
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    return payload;
  };
  const badge = (value, tone = '') => value && value !== 'unknown' ? `<span class="fc-badge ${tone}">${esc(value)}</span>` : '';
  const candidateText = (row) => row.field === 'phd_requirement'
    ? ({doctoral_student:'博士在读',abd:'ABD',completed:'博士已完成',unknown:'尚未填写'}[row.candidate_record] || row.candidate_record || '尚未填写')
    : row.field === 'materials' ? '按公告材料清单准备' : row.candidate_record || '尚未填写';

  function setNote(message, tone = 'info') {
    const node = $('fc-boundary');
    if (node) { node.className = `fc-note ${tone}`; node.textContent = message; }
    const alert = $('fc-action-error');
    if (alert) { alert.hidden = tone !== 'error'; alert.textContent = tone === 'error' ? message : ''; }
  }

  function renderActionCenter(summary = {}) {
    const selected = (state.query.position_type || '').split(',').filter(Boolean);
    $('fc-position-types').innerHTML = [['', '全部'], ...Object.entries(POSITIONS)].map(([key, label]) => `<button type="button" class="fc-chip ${key ? selected.includes(key) ? 'is-active' : '' : !selected.length ? 'is-active' : ''}" data-position="${key}" aria-pressed="${key ? selected.includes(key) : !selected.length}">${esc(label)}</button>`).join('');
    $('fc-position-type').value = selected.join(',');
    $('fc-action-view').value = state.query.action_view || 'all';
    const counts = summary.action_counts || {};
    $('fc-actions').innerHTML = Object.entries(ACTIONS).map(([key, label]) => `<button type="button" class="fc-action-card" data-action="${key}" aria-pressed="${state.query.action_view === key}"><span>${esc(label)}</span><strong>${number(counts[key])}</strong><small>${esc(({new:'本地首次发现 · 7 天',worth_review:'符合筛选 · 非 Adjunct',review_soon:'优先审查 / 固定截止',needs_verification:'信息缺项 / 陈旧 / 冲突'})[key])}</small></button>`).join('');
    $('fc-action-all').textContent = `全部当前筛选 · ${number(counts.all)}`;
    $('fc-action-all').setAttribute('aria-pressed', !state.query.action_view || state.query.action_view === 'all');
    const base = summary.action_rules?.[state.query.action_view] || '四个列表可能重叠；“值得看”是公开筛选规则，不是个人匹配分。';
    $('fc-action-rule').textContent = base;
    const school = CAREER_VIEWS.find(([key]) => key === state.query.career_view)?.[1] || '全部学校';
    const extra = Object.entries(state.query).filter(([key, value]) => value && !['scope','country','career_view','discipline','action_view','position_type'].includes(key)).map(([key, value]) => `${key}: ${value}`);
    $('fc-current-selection').textContent = `当前：${state.query.country || '全部国家'} · ${school} · ${state.query.discipline || '全部学科'} · ${scopeLabel(state.query.scope)}${extra.length ? ' · 额外筛选 ' + extra.join('；') : ''}`;
    $('fc-preferred').setAttribute('aria-pressed', state.query.scope === PREFERRED.scope && ['US','United States'].includes(state.query.country) && state.query.career_view === PREFERRED.career_view && state.query.discipline === PREFERRED.discipline);
    $('fc-r1-reference').setAttribute('aria-pressed', state.query.career_view === 'r1');
  }

  async function refreshSelection() {
    state.offset = 0;
    syncUrl();
    renderActionCenter();
    await Promise.all([loadSummary(), loadJobs(), loadR1Comparison(), loadFilters().catch(error => setNote(error.message, 'error'))]);
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
    if (!params.has('scope')) params.set('scope', 'business_school');
    return `${path}?${params.toString()}`;
  }

  function scopeLabel(scope) {
    return ({
      business_school: 'Business school faculty jobs',
      business: 'Business-discipline roles · school unverified',
      all: 'All observed postings (audit)',
    })[scope] || 'Business school faculty jobs';
  }


  // The three scopes side by side. Which one is selected changes which cell is
  // marked current -- it does not change what the reader is allowed to see,
  // because the whole point of the strict default is that a reader can tell
  // how much sits outside it.
  const SCOPE_ORDER = [
    ['business_school', 'Strict', 'Verified business school'],
    ['business', 'Broad', 'Adds discipline roles, school unverified'],
    ['all', 'Audit', 'Every observed record'],
  ];

  function inactiveText(counts) {
    const entries = Object.entries(counts || {});
    if (!entries.length) return 'none';
    // Never collapse these into one word. "Closed" is a status we observed;
    // "unknown" is a status we failed to observe, and reporting the two as one
    // claims knowledge of postings we never resolved.
    return entries.sort((a, b) => b[1] - a[1])
      .map(([status, n]) => `${number(n)} ${status.replace(/_/g, ' ')}`).join(' · ');
  }

  function renderScopeStrip(summary, currentScope) {
    const strip = $('fc-scope-strip');
    if (!strip) return;
    const comparison = summary.scope_comparison || {};
    if (!Object.keys(comparison).length) { strip.innerHTML = ''; return; }
    const cells = SCOPE_ORDER.map(([name, label, note]) => {
      const counts = comparison[name] || {};
      const current = name === currentScope;
      return `<div class="fc-scope-cell${current ? ' current' : ''}"${current ? ' aria-current="true"' : ''}>`
        + `<div class="fc-scope-head">${esc(label)}${current ? ' <span class="fc-scope-now">viewing</span>' : ''}</div>`
        + `<div class="fc-scope-value">${number(counts.active_jobs)}<span class="fc-scope-of"> of ${number(counts.catalogue_records)}</span></div>`
        + `<div class="fc-scope-note">${esc(note)}</div>`
        + `<div class="fc-scope-note">Not active: ${esc(inactiveText(counts.inactive_by_status))}</div>`
        + `</div>`;
    }).join('');
    const matching = number(summary.matching_records);
    strip.innerHTML = cells
      + `<div class="fc-scope-cell filtered"><div class="fc-scope-head">Your filters</div>`
      + `<div class="fc-scope-value">${matching}</div>`
      + `<div class="fc-scope-note">Records this query returned, which the list and the CSV export both match.</div>`
      + `<div class="fc-scope-note">Unknown, blocked and not-read sources are none of these numbers; absence here is not evidence of no vacancy.</div></div>`;
  }


  // Local observation started six days ago, so every record is "new in 7
  // days" -- the count equals the total and tells the reader nothing about
  // the market, however honest the label. Say which it is rather than letting
  // 315 new out of 315 active stand unexplained.
  function observationNote(summary, windowDays) {
    const since = summary.first_observation_at;
    if (!since) return 'First observed in the local snapshot';
    const days = Math.floor((Date.now() - Date.parse(since)) / 86400000);
    if (!Number.isFinite(days) || days >= windowDays) {
      return 'First observed in the local snapshot';
    }
    return `Local observation began ${days} day${days === 1 ? '' : 's'} ago, so every record still counts as new; this is not market turnover`;
  }


  // Four different states, not two. "partial" was rendering as "not read",
  // so the roster scan that reached 397 of 1,053 schools looked like it had
  // never run, and a board measured at 47% of its own reported total looked
  // unmeasurable.
  function completenessText(source) {
    const state = source.completeness_state;
    if (state === 'complete') return 'complete ' + dateText(source.last_complete_scan);
    if (state === 'partial') {
      const pct = source.source_coverage_percent;
      const total = source.source_reported_total;
      if (pct != null && total != null) {
        return `partial — ${pct}% of the ${number(total)} results this board reports`;
      }
      const roster = source.roster_coverage;
      if (roster && roster.complete_observations != null && roster.schools != null) {
        // Name the schools outside the denominator. Without a website there is
        // nothing to scan, but dropping them from the count silently is how a
        // roster shrinks to whatever we happened to resolve.
        const missing = roster.no_website_recorded;
        const aside = missing
          ? `; ${number(missing)} more ${missing === 1 ? 'has' : 'have'} no website recorded and cannot be scanned`
          : '';
        return `partial — ${number(roster.complete_observations)} of ${number(roster.schools)} schools read${aside}`;
      }
      return 'partial';
    }
    if (state === 'unverifiable') return 'read, but this board publishes no total to check against';
    return 'not read';
  }


  // The dialog printed "Visa evidence: unknown" on 99.8% of postings: a field
  // named for evidence, showing its absence. Say what the posting said, quote
  // it, and never let an unread page read as an employer's refusal.
  const VISA_LABELS = {
    sponsorship_explicit_yes: 'Will sponsor a work visa',
    permanent_residency_supported: 'Will support permanent residency',
    international_candidates_welcome: 'Welcomes international applicants (no commitment)',
    unclear: 'Mentions sponsorship without committing',
    sponsorship_explicit_no: 'Will not sponsor',
    citizen_or_pr_required: 'Requires citizenship or permanent residency',
    citizenship_required: 'Requires US citizenship',
    unknown: 'Not stated in the posting',
  };

  const VISA_PATHWAY_LABELS = {
    h1b: 'H-1B', j1: 'J-1', o1: 'O-1', tn: 'TN', e3: 'E-3',
    eb1: 'EB-1', eb2: 'EB-2', perm: 'PERM', green_card: 'Green card',
  };

  function visaDetail(job) {
    const status = job.visa_status || 'unknown';
    const label = VISA_LABELS[status] || status;
    const pathways = String(job.visa_pathways || '').split(',').filter(Boolean)
      .map((name) => VISA_PATHWAY_LABELS[name] || name);
    const parts = [detailField('Work authorization', label)];
    if (job.visa_text) {
      parts.push(detailField('Posting’s own words', '“' + job.visa_text + '”'));
    } else if (status === 'unknown') {
      // The distinction the whole field turns on.
      parts.push(detailField('Work authorization note',
        'The posting did not address sponsorship. That is not the employer declining — ' +
        'it usually means we have not read this posting’s own page.'));
    }
    if (pathways.length) {
      parts.push(detailField('Programmes named in the posting', pathways.join(', ')));
    }
    return parts.join('');
  }

  const CAREER_VIEWS = [
    ['r2_teaching', 'R2 / 教学导向', '当前重点'],
    ['r1', 'R1 研究参照', '保留观察 · 未来准备'],
    ['r2', '仅 R2', '研究分类'],
    ['teaching', '仅教学导向', '学校类型代理'],
    ['all', '全部学校', '含其他及未确认'],
    ['unclassified', '层级未确认', '含非美国学校'],
  ];

  function renderCareerViews(summary) {
    const current = state.query.career_view || 'all';
    const counts = summary.career_view_counts || {};
    $('fc-career-views').innerHTML = CAREER_VIEWS.map(([name, label, note]) =>
      `<button type="button" class="fc-career-view" data-career-view="${name}" aria-pressed="${name === current}"${state.careerBusy ? ' disabled' : ''}><strong>${esc(label)}</strong><span>${number(counts[name])} 条岗位记录 · ${esc(note)}</span></button>`).join('');
    $('fc-career-view').value = current;
    const purpose = current === 'r1'
      ? 'R1 作为未来研究型岗位参照。可对照岗位原文中的研究、教学、PhD 与聘用要求；没有明示的要求保持 Unknown，不计算录用概率。'
      : 'R2 与教学导向可以重叠，合并视图按岗位去重；R1 单列保留。';
    $('fc-career-note').textContent = purpose + ' 学校标签来自 Carnegie 2025；教学导向是学校类型代理，不代表岗位一定偏教学，也不等于 R2。按钮数字保留其他已提交筛选、忽略 university level 筛选，不代表全美空缺总数。';
  }

  async function selectCareerView(view) {
    if (state.careerBusy) return;
    state.careerBusy = true;
    state.query.career_view = view;
    delete state.query.university_level;
    const level = multiControls['fc-university-level'];
    if (level) level.clear();
    state.offset = 0;
    $('fc-career-view').value = view;
    $('fc-jobs').innerHTML = '<div class="fc-loading">Loading selected career view…</div>';
    document.querySelectorAll('[data-career-view]').forEach(node => { node.disabled = true; });
    syncUrl();
    try { await loadFilters(); await loadSummary(); await loadJobs(); }
    catch (error) { setNote(`Career view unavailable: ${error.message}`, 'error'); }
    finally {
      state.careerBusy = false;
      document.querySelectorAll('[data-career-view]').forEach(node => { node.disabled = false; });
    }
  }

  function careerBadges(job) {
    return job.carnegie_unitid
      ? badge(`${job.university_level} · Carnegie ${job.carnegie_year}`, job.university_level === 'R1' ? 'purple' : 'blue') + (job.teaching_proxy ? badge('Teaching-oriented proxy', 'blue') : '')
      : badge('Carnegie 未确认 / 不适用', 'amber');
  }

  function careerDetail(job) {
    const classification = job.carnegie_unitid
      ? `<p>${careerBadges(job)} · UNITID ${esc(job.carnegie_unitid)} · ${esc(job.carnegie_match_method)}</p><p>${esc(job.carnegie_institutional_classification)}</p><a class="fc-link" href="${esc(job.carnegie_source_url)}" target="_blank" rel="noopener">Carnegie 官方分类依据 ↗</a>`
      : '<p>学校尚未可靠对应到 Carnegie 2025，或不在其美国分类范围内。Unknown 不等于低层级。</p>';
    return `<section class="fc-note info"><h3>学校定位与状态依据</h3>${classification}<p>当前显示：${esc(job.status)} · 按 ${esc(job.status_as_of)} 计算；最近来源观察：${esc(job.observed_status)}。${job.status_basis === 'fixed_deadline_elapsed' ? '明确截止日期已过；历史来源状态保留。' : '只有明确的固定截止日期会自动关闭；rolling / open until filled 不按评审日期关闭。'}</p><p>最近看到来源记录：${esc(dateText(job.last_seen_at))} · ${job.freshness === 'stale' ? '超过 14 天，投递前需复核原站' : job.freshness === 'unknown' ? '时间未知' : '14 天内观察到，不保证此刻仍开放'}。学校研究层级、学校教学代理和岗位聘用类型是三个不同维度。</p></section>`;
  }

  function renderSummary(payload) {
    renderCareerViews(payload.summary || {});
    renderActionCenter(payload.summary || {});
    const summary = payload.summary || {};
    const coverage = summary.coverage || {};
    const currentScope = summary.scope || state.query.scope;
    const auditView = currentScope === 'all';
    const cards = [
      [auditView ? 'Active observed' : 'Active jobs', number(summary.active_jobs), 'Observed active or likely-open postings'],
      ['New · 7 days', number(summary.new_7d), observationNote(summary, 7)],
      ['Closing · 14 days', number(summary.closing_next_14d), 'Fixed deadlines parsed from sources'],
      ['United States', number((summary.by_region || []).find((x) => x.label === 'United States')?.count), 'Source-reported or fallback location'],
      ['Canada', number((summary.by_region || []).find((x) => x.label === 'Canada')?.count), 'Canada public board coverage'],
      ['Europe', number((summary.by_region || []).find((x) => x.label === 'Europe')?.count), 'Europe public source coverage'],
    ];
    $('fc-summary').innerHTML = cards.map((card) => `<div class="fc-kpi"><div class="fc-kpi-value">${esc(card[1])}</div><div class="fc-kpi-label">${esc(card[0])}</div><div class="fc-kpi-note">${esc(card[2])}</div></div>`).join('');
    renderScopeStrip(summary, currentScope);
    $('fc-last-updated').textContent = `Snapshot read ${new Date().toLocaleString()}`;
    $('fc-private-state').textContent = scopeLabel(currentScope);
    $('fc-jobs-title').textContent = auditView ? 'Observed source catalogue (audit)' : ACTIONS[state.query.action_view] || '当前目标岗位';
    const recordLabel = auditView ? 'observed source records, including excluded roles' : 'role-eligible observed jobs';
    const preservedSnapshotNote = coverage.jobs_with_disabled_or_opt_in_source_only
      ? ` · ${number(coverage.jobs_with_disabled_or_opt_in_source_only)} only from preserved disabled/opt-in source snapshots`
      : '';
    const noSourceNote = coverage.jobs_with_no_active_source
      ? ` · ${number(coverage.jobs_with_no_active_source)} without an active source link`
      : '';
    $('fc-boundary').textContent = `Scope: ${scopeLabel(currentScope)} · ${number(coverage.jobs)} ${recordLabel} · official application URL ${pct(coverage.official_url_percent)} · fixed/rolling deadline ${pct(coverage.deadline_percent)} · salary evidence ${pct(coverage.salary_percent)} · possible duplicates ${number(coverage.possible_duplicates)}${preservedSnapshotNote}${noSourceNote}.`;
    $('fc-job-count').textContent = `${number(coverage.jobs)} 条符合当前筛选的记录 · 分页显示；不保证此刻仍开放。`;
    updateExportLink();
  }

  const multiControls = {};

  // A vocabulary filter answers "which of these", and more than one can be
  // true at once: Marketing *or* Information Systems, every source *except*
  // the aggregator. The control keeps a hidden input holding the comma-joined
  // value, so the existing FormData submit path needs no special case, and the
  // original <select> stays in the DOM (name removed) as the no-JS fallback.
  function upgradeMulti(selectId) {
    const select = $(selectId);
    if (!select || !select.dataset.multi || select.dataset.upgraded) return null;
    const name = select.name;
    const allLabel = select.options[0] ? select.options[0].textContent : 'All';
    select.dataset.upgraded = '1';
    select.removeAttribute('name');
    select.hidden = true;

    const wrap = document.createElement('div');
    wrap.className = 'fc-multi';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'fc-select fc-multi-toggle';
    toggle.setAttribute('aria-expanded', 'false');
    const panel = document.createElement('div');
    panel.className = 'fc-multi-panel';
    panel.hidden = true;
    const panelId = `${selectId}-panel`;
    panel.id = panelId;
    panel.setAttribute('role', 'group');
    panel.setAttribute('aria-label', allLabel);
    toggle.setAttribute('aria-controls', panelId);
    // A panel that covers the Apply button leaves no way to submit what was
    // just ticked without dismissing it first, so it closes itself.
    const done = document.createElement('button');
    done.type = 'button';
    done.className = 'fc-multi-done';
    done.textContent = 'Done';
    const hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.name = name;
    wrap.append(toggle, panel, hidden);
    select.parentNode.insertBefore(wrap, select.nextSibling);

    function sync() {
      const chosen = Array.from(panel.querySelectorAll('input:checked')).map((box) => box.value);
      hidden.value = chosen.join(',');
      toggle.textContent = chosen.length === 0 ? allLabel
        : (chosen.length === 1
          ? (panel.querySelector('input:checked').dataset.label || chosen[0])
          : `${chosen.length} selected`);
      toggle.classList.toggle('is-active', chosen.length > 0);
    }

    function close(refocus) {
      panel.hidden = true;
      toggle.setAttribute('aria-expanded', 'false');
      if (refocus) toggle.focus();
    }

    toggle.addEventListener('click', () => {
      const open = panel.hidden;
      document.querySelectorAll('.fc-multi-panel').forEach((node) => { node.hidden = true; });
      document.querySelectorAll('.fc-multi-toggle').forEach((node) => {
        node.setAttribute('aria-expanded', 'false');
      });
      panel.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
      if (open) {
        const first = panel.querySelector('input');
        if (first) first.focus();
      }
    });
    done.addEventListener('click', () => close(true));
    wrap.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !panel.hidden) {
        event.stopPropagation();
        close(true);
      }
    });
    document.addEventListener('click', (event) => {
      if (!wrap.contains(event.target)) close(false);
    });

    const control = {
      name,
      rebuild() {
        const previous = new Set(String(hidden.value || '').split(',').filter(Boolean));
        panel.innerHTML = '';
        Array.from(select.options).slice(1).forEach((option) => {
          const row = document.createElement('label');
          row.className = 'fc-multi-option';
          const box = document.createElement('input');
          box.type = 'checkbox';
          box.value = option.value;
          box.dataset.label = option.textContent;
          box.checked = previous.has(option.value);
          box.addEventListener('change', sync);
          row.append(box, document.createTextNode(' ' + option.textContent));
          panel.appendChild(row);
        });
        panel.appendChild(done);
        sync();
      },
      set(value) {
        const wanted = new Set(String(value || '').split(',').map((item) => item.trim()).filter(Boolean));
        panel.querySelectorAll('input').forEach((box) => { box.checked = wanted.has(box.value); });
        sync();
      },
      clear() {
        panel.querySelectorAll('input').forEach((box) => { box.checked = false; });
        sync();
      },
    };
    multiControls[selectId] = control;
    return control;
  }

  function clearAllFilters() {
    const form = $('fc-filter-form');
    form.reset();
    Object.values(multiControls).forEach((control) => control.clear());
    state.query = { scope: 'business_school', career_view: 'all', region: '' };
    state.offset = 0;
    syncUrl();
    return loadFilters().then(loadSummary).then(loadJobs);
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
    const control = multiControls[selectId] || upgradeMulti(selectId);
    if (control) control.rebuild();
  }

  async function loadFilters() {
    const endpoint = scopedEndpoint('/api/faculty-jobs/filters');
    const payload = await api(endpoint);
    if (endpoint !== scopedEndpoint('/api/faculty-jobs/filters')) return;
    const filters = payload.filters || {};
    optionValues('fc-discipline', filters.disciplines);
    optionValues('fc-rank', filters.ranks);
    optionValues('fc-track', filters.tracks);
    optionValues('fc-appointment', filters.appointment_types);
    // Each board's share sits next to its name. One source currently supplies
    // most of the default view, and that belongs in front of whoever is
    // filtering rather than only on the source-health page.
    const sourceRows = filters.sources || [];
    const sourceJobs = Object.fromEntries(sourceRows.map((item) => [item.name, item.jobs]));
    const sourceNames = sourceRows.map((item) => item.name);
    optionValues('fc-source', sourceNames, (name) => `${name} (${sourceJobs[name]})`);
    optionValues('fc-exclude-source', sourceNames, (name) => `Exclude ${name} (${sourceJobs[name]})`);
    optionValues('fc-ever-source', sourceNames, (name) => `Ever listed by ${name}`);
    optionValues('fc-country', filters.countries);
    optionValues('fc-state', filters.states_provinces);
    optionValues('fc-career-stage', filters.career_stages);
    optionValues('fc-status', filters.statuses);
    optionValues('fc-school-tier', filters.school_tiers);
    optionValues('fc-university-level', filters.university_levels);
    const countryLabels = Object.fromEntries((filters.country_options || []).map((item) => [String(item.code || '').toUpperCase(), item.label]));
    Object.entries(state.query).forEach(([key, value]) => {
      const control = Object.values(multiControls).find((item) => item.name === key);
      const formValue = key === 'country'
        ? String(value).split(',').map((item) => countryLabels[item.trim().toUpperCase()] || item.trim()).join(',')
        : value;
      if (control) { control.set(formValue); return; }
      const field = $('fc-filter-form').elements.namedItem(key);
      if (field && field.type === 'checkbox') field.checked = ['1', 'true', 'yes'].includes(String(formValue));
      else if (field) field.value = formValue;
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
      const outcomes = source.scan_outcomes || {};
      const outcomeUnknown = outcomes.error_blocked_unknown_percent == null ? 'Unknown' : pct(outcomes.error_blocked_unknown_percent);
      const acceptance = source.acceptance_rate_percent == null ? 'Unknown' : pct(source.acceptance_rate_percent);
      const registry = source.registry_coverage;
      const registryNote = !registry ? '' : registry.available
        ? `<div class="fc-small" id="fc-carnegie-coverage">Carnegie 2025 · ${number(registry.schools)} schools (${number(registry.r2)} R2; ${number(registry.teaching_proxy)} teaching proxy; ${number(registry.overlap)} overlap).<br>${number(registry.portal_records)} portal records · ${number(registry.scanned_eligible_portal_urls)} / ${number(registry.eligible_portal_urls)} eligible portal URLs visited · ${number(registry.remaining_eligible_portal_urls)} not yet visited.<br>Checked within 7 days: ${number(registry.portal_urls_checked_last_7d)} · older or undated visits: ${number(registry.stale_or_undated_portal_urls)}.<br>${number(registry.latest_candidate_urls)} observed candidate URLs, not current job count · latest portal observation ${esc(dateText(registry.latest_observation_at))}.<br>${esc(registry.note)}<br><button class="fc-button fc-manage-only" id="fc-carnegie-update" type="button">Scan next 5 Carnegie portals</button></div>`
        : `<div class="fc-small">${esc(registry.reason)}</div>`;
      return `<div class="fc-stat-row"><span title="${esc(reason)}">${esc(source.name)}</span><span class="fc-stat-bar"><span style="width:${Math.min(100, Number(source.active_jobs || 0) / 2)}%"></span></span><span class="fc-stat-count">${active}</span></div><div class="fc-small">Raw active records: ${active} · business-scope records: ${business} · explicit school: ${number(source.explicit_school_jobs)} · field coverage: ${field('deadline_or_rolling', 'deadline')} · ${field('salary', 'salary')} · ${field('official_url', 'official URL')} · ${field('posted_date', 'posted')}<br>Rule-accepted: ${number(source.rule_accepted_jobs)} · review-only: ${number(source.review_only_jobs)} · acceptance rate: ${esc(acceptance)} · reviewed false positives: ${number(source.reviewed_false_positive_jobs)} · uncertain scan observations: ${esc(outcomeUnknown)} · listing completeness: ${esc(completenessText(source))}<br>${badge(source.support_status || source.last_status, tone)} ${esc(reason)}</div>${registryNote}`;
    }).join('');
    const carnegieButton = $('fc-carnegie-update');
    if (carnegieButton) carnegieButton.addEventListener('click', async () => {
      carnegieButton.disabled = true;
      try {
        const result = await api('/api/faculty-jobs/update', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sources: ['carnegie_official'], max_pages: 5 }),
        });
        setNote(result.message || 'Carnegie batch started. Refresh after completion to see coverage and postings.', 'success');
      } catch (error) { setNote(`Carnegie scan could not start: ${error.message}`, 'error'); }
      finally { carnegieButton.disabled = false; }
    });
  }

  function jobCard(job) {
    const title = known(job.title_raw, 'Untitled academic job');
    const institution = known(job.institution_name || job.institution_raw, 'Unknown institution');
    const location = [job.city, job.state_province, job.country].filter(Boolean).join(', ') || 'Unknown location';
    const timing = job.timing || {};
    const deadline = `硬截止：${timing.hard_deadline || '未确认'}${timing.hard_deadline_basis === 'stored_record_needs_verification' ? '（仅已有记录，待核验）' : ''}`;
    const mode = ({open_until_filled:'招满为止', rolling:'滚动审查', fixed:'固定截止记录'})[timing.recruitment_mode] || '招聘方式未确认';
    const sourceCount = Array.isArray(job.sources) ? new Set(job.sources.map((item) => item.name)).size : 0;
    const official = job.official_url ? `<a class="fc-link" href="${esc(job.official_url)}" target="_blank" rel="noopener">已收录入口 · 待核验 ↗</a>` : '<span>官方入口待核验</span>';
    const school = job.business_research_tier || job.school_tier || 'Unclassified';
    const scope = job.business_scope || 'unknown';
    const scopeText = ({
      business_school: 'Business school evidence',
      business_discipline: 'Business discipline · school unverified',
      non_business: 'Excluded: non-business',
      non_academic: 'Excluded: non-academic',
    })[scope] || 'Business scope unknown';
    const scopeTone = scope === 'business_school' ? 'blue' : scope === 'business_discipline' ? 'green' : 'amber';
    const detail = `<button class="fc-button secondary fc-detail-button" type="button" data-job-id="${esc(job.id)}">要求与原文</button>`;
    const career = `<div class="fc-badges">${careerBadges(job)}${job.freshness === 'stale' ? badge('需复核 · 超过 14 天未更新', 'amber') : ''}</div>`;
    const req = job.requirements || {};
    const application = req.fields?.application_url;
    const applyLink = application?.status === 'supported' ? `<a class="fc-link" href="${esc(application.value)}" target="_blank" rel="noopener">原文申请入口 ↗</a>` : official;
    const review = req.fields?.review_date;
    const reviewLine = review?.normalized_date ? `首轮／优先审查：${review.normalized_date}${review.normalized_date < job.status_as_of ? ' · 已过，不等于关闭' : ''}` : '首轮审查：未确认';
    const requirementsLine = `${job.posting_kind === 'pool' ? '人才库／持续招聘 · 具体空缺待确认 · ' : ''}官方证据 ${number(req.official_supported_count || 0)}/5${req.source_kind === 'job_board' && req.status === 'ok' && req.supported_count > 0 ? ' · 另有转载页证据' : ''}${req.status === 'blocked' ? ' · 读取受阻' : ''}`;
    return `<article class="fc-job-card"><div class="fc-job-top"><div><h3><a href="#job-${esc(job.id)}" class="fc-detail-link" data-job-id="${esc(job.id)}">${esc(title)}</a></h3><div class="fc-job-institution">${esc(institution)} · ${esc(location)}</div></div><span class="fc-inline-actions">${applyLink}${detail}</span></div><div class="fc-badges"><span class="fc-small">学校</span>${careerBadges(job)}<span class="fc-small fc-axis-separator">岗位</span>${(job.position_types || []).map(type => badge(POSITIONS[type], type === 'adjunct' ? 'amber' : 'green')).join('')}${badge(job.discipline_primary,'purple')}${badge(mode, 'blue')}${badge(job.status, job.status === 'closed' ? 'red' : 'green')}</div><div class="fc-job-meta"><span>${esc(requirementsLine)}</span><span>${esc(reviewLine)}</span><span>${esc(deadline)}</span><span>首次发现 ${esc(dateText(job.first_seen_at))}</span></div>${job.discipline_needs_verification ? '<p class="fc-small fc-warning">标题与目标学科可能不符，请先核验；未自动改写原分类。</p>' : ''}<div class="fc-job-foot"><span>${(job.actions || []).map(key => badge(ACTIONS[key], key === 'needs_verification' ? 'amber' : 'blue')).join(' ')} · ${number(sourceCount)} 个来源</span><span>最后成功核验：${esc(timeText(job.last_verified_at))}${timing.last_attempt_at ? ` · 最近尝试 ${esc(timeText(timing.last_attempt_at))}` : ''}</span></div></article>`;
  }

  function renderJobs(payload) {
    const jobs = payload.jobs || [];
    $('fc-jobs').innerHTML = jobs.length ? jobs.map(jobCard).join('') : '<div class="fc-empty"><strong>No jobs match these filters</strong>Try a wider region or remove a discipline/rank filter.</div>';
    $('fc-pager').innerHTML = '';
    const page = payload.pagination || { total: 0, offset: 0, limit: state.limit, has_more: false };
    $('fc-job-count').textContent = `${number(page.total)} 条符合当前筛选的记录 · 分页显示；不保证此刻仍开放。`;
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
    const request = ++state.jobRequest;
    $('fc-pager').innerHTML = '';
    $('fc-job-count').textContent = '正在读取当前筛选…';
    $('fc-jobs-title').textContent = state.query.scope === 'all' ? 'Observed source catalogue (audit)' : ACTIONS[state.query.action_view] || '当前目标岗位';
    $('fc-jobs').innerHTML = '<div class="fc-loading">Loading public job snapshot…</div>';
    try { const payload = await api(`/api/faculty-jobs?${buildQuery()}`); if (request === state.jobRequest) renderJobs(payload); }
    catch (error) { if (request === state.jobRequest) $('fc-jobs').innerHTML = `<div class="fc-note error">Could not load jobs: ${esc(error.message)}</div>`; }
  }

  function requirementsDetail(job) {
    const req = {...(job.requirements || {})};
    const captureTime = timeText(req.captured_at);
    const labels = { application_url: '官方申请入口', teaching_load: '教学负担', research_requirements: '研究要求', start_date: '入职时间', materials: '材料清单', review_date: '首轮／优先审查时间', hard_deadline: '硬截止（不是审查日期）', recruitment_mode: '招聘方式 · 是否招满为止', phd_requirement:'学位／博士条件', teaching_experience:'教学经历与效果要求', appointment_contract:'聘用合同原文', posting_kind:'公告性质原文' };
    const statuses = { supported:'有原文证据', not_stated:'已读原文未明示／未可靠提取', not_read:'尚未读取', blocked:'读取受阻', needs_verification:'需要核验' };
    const fields = Object.entries(labels).map(([name, label]) => {
      const field = req.fields?.[name] || { status: 'not_read' };
      const value = name === 'application_url' && field.status === 'supported' ? `<a class="fc-link" href="${esc(field.value)}" target="_blank" rel="noopener">打开公告提供的申请入口 ↗</a>` : field.value ? `<p>${esc(field.value)}</p>` : '';
      return `<section class="fc-requirement"><h4>${label} ${badge(statuses[field.status] || field.status, field.status === 'supported' ? 'green' : 'amber')}</h4>${value}${field.conflict ? `<p class="fc-warning">${esc(field.conflict)}</p>` : ''}${field.quote ? `<details><summary>查看原文证据</summary><blockquote class="fc-pre">${esc(field.quote)}</blockquote>${field.link_basis ? `<p class="fc-small">${esc(field.link_basis)}</p>` : ''}</details>` : '<p class="fc-small">没有可引用证据；不表示没有这项要求。</p>'}</section>`;
    }).join('');
    req.captured_at = captureTime;
    return `<section class="fc-requirements"><h3>申请前要核对的五项信息</h3><p class="fc-small">来源：${req.source_kind === 'official_posting' ? '学校／官方招聘公告' : req.source_kind === 'job_board' ? '招聘转载页 · 非官方核验' : '尚未读取'} · 读取时间 ${esc(req.captured_at || '未知')} · 官方证据 ${number(req.official_supported_count || 0)}/5。未自动判断你是否满足要求。</p>${req.source_url ? `<a class="fc-link" href="${esc(req.source_url)}" target="_blank" rel="noopener">核对本次证据来源 ↗</a>` : ''}${req.latest_attempt && req.latest_attempt.status !== 'ok' ? `<p class="fc-note">最近一次读取：${esc(req.latest_attempt.status)} · ${esc(req.latest_attempt.reason)}。既有证据仍保留，不代表当前仍开放。</p>` : ''}<div class="fc-requirements-grid">${fields}</div>${req.content_hash ? `<p class="fc-small fc-hash">原文 SHA-256 ${esc(req.content_hash)}</p>` : ''}</section>`;
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
      await loadCareerAccess();
      const manage = document.body.dataset.careerAccess === 'local';
      const action = manage ? `<button class="fc-button success" id="fc-save-job" type="button">Save to My Applications</button><button class="fc-button secondary" id="fc-include-scope" type="button">Include in business view</button><button class="fc-button danger" id="fc-exclude-scope" type="button">Exclude from business view</button>` : '';
      const overrideText = job.scope_override ? `${job.scope_override.action}: ${job.scope_override.reason || 'reason not provided'}` : 'None';
      body.innerHTML = `<div class="fc-inline-actions">${job.official_url ? `<a class="fc-button primary" href="${esc(job.official_url)}" target="_blank" rel="noopener">Open official application ↗</a>` : ''}${action}</div><div class="fc-detail-grid">${detailField('Original title', job.original_title || job.title_raw)}${detailField('Institution', job.institution_name)}${detailField('Business school', job.business_school_name || 'No posting-level school extracted')}${detailField('Faculty-market role', job.faculty_market_role)}${detailField('Role eligibility evidence', job.faculty_market_reason)}${detailField('Business scope', job.business_scope)}${detailField('Business-scope evidence', job.business_scope_reason)}${detailField('School evidence context', job.school_evidence_context)}${detailField('Manual scope override', overrideText)}${detailField('School evidence', job.school_evidence_label)}${detailField('Department', job.department)}${detailField('Location', [job.city, job.state_province, job.country].filter(Boolean).join(', '))}${detailField('Rank mapping', job.rank_normalized)}${detailField('Career stage', job.career_stage)}${detailField('Discipline', job.discipline_primary)}${detailField('Research areas', (job.research_areas || []).join(', '))}${detailField('Teaching areas', (job.teaching_areas || []).join(', '))}${detailField('Track / contract', job.track_type)}${detailField('Appointment type', job.appointment_type)}${detailField('Start term / year', [job.start_term, job.start_year].filter(Boolean).join(' / '))}${detailField('Deadline', job.deadline_date || job.deadline_mode)}${detailField('Deadline evidence', job.deadline_evidence)}${detailField('Salary evidence', job.salary_raw)}${detailField('PhD evidence', job.phd_required === 1 ? 'Required' : job.phd_required === 0 ? 'Not required' : 'Unknown')}${visaDetail(job)}${detailField('Language', job.language_requirements)}${detailField('University level', job.university_level)}${detailField('Business tier', job.school_tier)}${detailField('First seen', job.first_seen_at)}${detailField('Last checked', job.last_seen_at)}${detailField('Extraction confidence', [job.business_scope_confidence, job.rank_mapping_confidence, job.location_evidence].filter(Boolean).join(' · '))}</div><h3>Source excerpt</h3><div class="fc-pre">${esc(job.description_excerpt || 'No excerpt captured from the public listing.')}</div><h3>Status history</h3><ul class="fc-small">${(job.status_history || []).map((item) => `<li>${esc(item.observed_at)} · ${esc(item.status)} · ${esc(item.change_reason || '')}</li>`).join('') || '<li>Unknown</li>'}</ul><h3>Source links</h3><ul class="fc-small">${sourceLinks || '<li>Source link unavailable.</li>'}</ul><p class="fc-small">Rank explanation: ${esc(job.rank_mapping_explanation || 'Unknown')} Classification: ${esc(job.classification_reason || 'Unknown')} Deadline parsing: ${esc(job.deadline_parse_reason || 'Unknown')}.</p>`;
      body.insertAdjacentHTML('afterbegin', careerDetail(job));
      body.insertAdjacentHTML('afterbegin', requirementsDetail(job));
      const legacyGrid = body.querySelector('.fc-detail-grid');
      if (legacyGrid) legacyGrid.insertAdjacentHTML('beforebegin', '<h3>汇总记录与审计</h3><p class="fc-small">以下汇总字段可能尚未补全；请以顶部标明日期的官方原文为准。</p>');
      body.insertAdjacentHTML('afterbegin', `<div class="fc-inline-actions"><button class="fc-button secondary" id="fc-gap-button" type="button">对照我的成果与经历</button><a class="fc-link" href="/my-applications">填写本机资料</a></div><div id="fc-gap-result" aria-live="polite"></div>`);
      if (!manage) {
        const personalBar = $('fc-gap-button').parentElement;
        personalBar.remove();
        $('fc-gap-result').remove();
      }
      const gapButton = $('fc-gap-button');
      if (gapButton) gapButton.onclick = async () => {
        const target = $('fc-gap-result');
        target.textContent = '正在读取本机差距比较…';
        try {
          const payload = await api(`/api/faculty-jobs/${encodeURIComponent(id)}/gap`);
          const gap = payload.gap || {};
          gap.rows = (gap.rows || []).map(row => ({...row, candidate_record:candidateText(row)}));
          if ($('fc-gap-result') !== target) return;
          target.innerHTML = `<section class="fc-requirements"><h3>逐项准备差距</h3>${!gap.profile_configured ? '<p class="fc-note">尚未填写博士进度、论文和授课事实。请在 My Applications 补充后查看个人对照。</p>' : ''}<div class="fc-requirements-grid">${(gap.rows || []).map(row => `<article class="fc-requirement"><h4>${esc(row.label)}</h4><p class="fc-small">${esc(row.explanation)}</p><p><strong>公告原文：</strong>${esc(row.official_quote || '官方条件待核验')}</p><p><strong>你的记录：</strong>${esc(row.candidate_record || '尚未填写')}</p>${row.source_url ? `<a class="fc-link" href="${esc(row.source_url)}" target="_blank" rel="noopener">原文 · ${esc(timeText(row.verified_at))}</a>` : ''}</article>`).join('')}</div></section>`;
        } catch (error) { if ($('fc-gap-result') === target) target.innerHTML = `<p class="fc-note">${esc(error.message)} · 个人对照请在本机访问。</p>`; }
      };
      body.querySelectorAll('.fc-detail-label').forEach(label => {
        if (label.textContent === 'Last checked') label.textContent = '最近来源观察（非成功核验）';
        if (label.textContent === 'Deadline') label.textContent = '原有日期字段（仅供审计）';
      });
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
    $('fc-source-details').addEventListener('toggle', () => { if ($('fc-source-details').open && !sourcesLoaded) loadSourceDetails(); });
    $('fc-preferred').addEventListener('click', () => { state.query = {...PREFERRED}; $('fc-filter-form').reset(); Object.values(multiControls).forEach(control => control.clear()); refreshSelection(); });
    $('fc-r1-reference').addEventListener('click', () => { state.query = {...PREFERRED, career_view:'r1'}; $('fc-filter-form').reset(); Object.values(multiControls).forEach(control => control.clear()); refreshSelection(); });
    $('fc-position-types').addEventListener('click', event => {
      const button = event.target.closest('[data-position]'); if (!button) return;
      const types = new Set((state.query.position_type || '').split(',').filter(Boolean));
      const type = button.dataset.position;
      if (!type) types.clear(); else if (types.has(type)) types.delete(type); else types.add(type);
      state.query.position_type = [...types].join(','); refreshSelection();
    });
    $('fc-actions').addEventListener('click', event => { const button = event.target.closest('[data-action]'); if (button) { state.query.action_view = button.dataset.action; delete state.query.sort; refreshSelection(); } });
    $('fc-action-all').addEventListener('click', () => { state.query.action_view = 'all'; refreshSelection(); });
    $('fc-career-views').addEventListener('click', event => {
      const button = event.target.closest('[data-career-view]');
      if (button) selectCareerView(button.dataset.careerView);
    });
    $('fc-filter-form').addEventListener('submit', async (event) => { event.preventDefault(); const form = new FormData(event.currentTarget); const nextQuery = Object.fromEntries(form.entries()); state.query = { ...nextQuery, region: state.query.region || '' }; state.offset = 0; syncUrl(); await loadFilters(); await loadSummary(); loadJobs(); });
    $('fc-reset').addEventListener('click', clearAllFilters);
    const clearAll = $('fc-clear-all');
    if (clearAll) clearAll.addEventListener('click', clearAllFilters);
    $('fc-update').addEventListener('click', updateSources);
    const saveSearch = $('fc-save-search'); if (saveSearch) saveSearch.addEventListener('click', saveCurrentSearch);
    $('fc-detail-close').addEventListener('click', () => $('fc-detail-dialog').close());
    $('fc-detail-dialog').addEventListener('click', (event) => { if (event.target === $('fc-detail-dialog')) $('fc-detail-dialog').close(); });
  }

  async function loadSummary() {
    const endpoint = scopedEndpoint('/api/faculty-jobs/summary');
    try { const payload = await api(endpoint); if (endpoint === scopedEndpoint('/api/faculty-jobs/summary')) renderSummary(payload); } catch (error) { setNote(`Summary unavailable: ${error.message}`, 'error'); }
  }

  async function loadAll() {
    await loadCareerAccess();
    if (document.body.dataset.careerAccess !== 'local') {
      const heading = document.querySelector('.fc-hero h1');
      if (heading) heading.textContent = '公开教职数据';
    }
    await Promise.all([loadSummary(), loadJobs(), loadR1Comparison(), loadFilters().catch(error => setNote(`Filters unavailable: ${error.message}`, 'error'))]);
    if ($('fc-source-details').open) await loadSourceDetails();
  }

  let careerAccessPromise;
  function loadCareerAccess() {
    if (!careerAccessPromise) {
      careerAccessPromise = api('/api/faculty-jobs/capabilities').then(access => {
        const local = access.personal === true && access.manage === true;
        document.body.dataset.careerAccess = local ? 'local' : 'public';
        if (!local && $('fc-preferred')) $('fc-preferred').textContent = '美国＋R2／教学导向＋IS／Management／OBHR';
        return local;
      }).catch(() => { document.body.dataset.careerAccess = 'public'; return false; });
    }
    return careerAccessPromise;
  }

  async function loadR1Comparison() {
    const section = $('fc-r1-comparison');
    if (!section) return;
    section.hidden = state.query.career_view !== 'r1';
    if (section.hidden) return;
    const target = $('fc-r1-comparison-body');
    target.textContent = '正在读取官方要求覆盖…';
    try {
      const payload = await api('/api/faculty-jobs/requirements-comparison');
      if (state.query.career_view !== 'r1') return;
      const groups = payload.groups || {};
      const labels = {application_url:'申请入口', teaching_load:'教学负担', research_requirements:'研究要求', start_date:'入职时间', materials:'材料清单'};
      target.innerHTML = `<p class="fc-small">范围：美国 · IS / Management / OBHR。数字为已有官方原文证据的岗位数。</p><div class="fc-table-wrap"><table class="fc-table"><thead><tr><th>岗位与证据</th><th>R2／教学导向</th><th>R1</th></tr></thead><tbody><tr><td>当前岗位</td><td>${number(groups.r2_teaching?.jobs)}</td><td>${number(groups.r1?.jobs)}</td></tr><tr><td>成功读取官方页</td><td>${number(groups.r2_teaching?.official_readings)}</td><td>${number(groups.r1?.official_readings)}</td></tr>${Object.entries(labels).map(([key,label]) => `<tr><td>${esc(label)}</td><td>${number(groups.r2_teaching?.supported_fields?.[key] || 0)}</td><td>${number(groups.r1?.supported_fields?.[key] || 0)}</td></tr>`).join('')}</tbody></table></div><p class="fc-small">${document.body.dataset.careerAccess === 'local' ? '原文缺项不代表要求较低。查看岗位“要求与原文”后，可点“对照我的成果与经历”查看个人准备项。' : '原文缺项不代表要求较低。当前为公开数据浏览，请打开岗位原文核对具体条件。'}</p><div class="fc-requirements-grid">${(groups.r1?.examples || []).map(row => `<article class="fc-requirement"><h4>${esc(row.institution)}</h4><p>${esc(row.title)}</p>${row.research_quote ? `<p>研究：${esc(row.research_quote)}</p>` : ''}${row.teaching_quote ? `<p>教学负担：${esc(row.teaching_quote)}</p>` : ''}<a class="fc-link" href="${esc(row.source_url)}" target="_blank" rel="noopener">核对原文 · ${esc(timeText(row.verified_at))}</a></article>`).join('') || '<p class="fc-small">当前 R1 官方原文仍待补全。</p>'}</div>`;
    } catch (error) { if (state.query.career_view === 'r1') target.textContent = `要求参照暂不可读取：${error.message}`; }
  }

  async function loadSourceDetails() {
    sourcesLoaded = true;
    try { renderSources(await api('/api/faculty-jobs/sources')); }
    catch (error) { sourcesLoaded = false; $('fc-sources').innerHTML = `<div class="fc-note error">Source health unavailable: ${esc(error.message)}</div>`; }
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
    renderActionCenter();
    loadAll();
    const jobId = new URLSearchParams(window.location.search).get('job_id');
    if (jobId) setTimeout(() => loadDetail(jobId), 250);
  });
})();
