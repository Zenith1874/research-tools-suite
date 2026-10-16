/* Observatory page.
 *
 * Every figure this renders has existed only inside a command-line report.
 * The one rule the rendering follows: a count is never drawn without the
 * thing that qualifies it -- its denominator, its coverage, or the sentence
 * saying what it is not. Those sentences come from the API as fields, so the
 * page cannot show a number and drop its caveat.
 */
(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function number(value) {
    if (value == null || value === '') return '—';
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString() : String(value);
  }

  function bytes(value) {
    if (!value) return '—';
    const mb = value / 1048576;
    return mb >= 1 ? mb.toFixed(1) + ' MB' : (value / 1024).toFixed(0) + ' KB';
  }

  /* `value` may carry a <small> qualifier -- "364 of 446", "996 · 71.3%" --
   * because a figure and its denominator are one object here. Escaping it
   * would print the tag; the callers build it from numbers, never from
   * anything a source supplied. The label is escaped as ordinary text. */
  function figure(value, label, unit) {
    return `<div class="am-figure"><div class="am-figure-value">${value}${
      unit ? `<small> ${esc(unit)}</small>` : ''}</div>` +
      `<div class="am-figure-label">${esc(label)}</div></div>`;
  }

  function caveat(text) {
    return text ? `<div class="am-caveat">${esc(text)}</div>` : '';
  }

  /* `extra` marks a card as dense enough to want two grid tracks. It used to
   * be a `:first-child` rule, which meant reordering the cards silently moved
   * the wide layout to whatever landed first. */
  function card(title, subtitle, body, extra) {
    return `<section class="am-card${extra ? ' ' + extra : ''}"><h2>${esc(title)}</h2>` +
      (subtitle ? `<p class="am-sub">${esc(subtitle)}</p>` : '') + body + '</section>';
  }

  // ---- the five layers, and what each is not ----------------------------
  /* Each layer says what it answers, what it is *not*, and how much it holds.
   * The middle line is a caveat about meaning, not a status -- but with no
   * holding figure beside it, a layer with 11,763 filings and a layer with
   * nothing looked identical, and the red text read as "not done". The count
   * is what distinguishes them, so an empty layer now says so in its own
   * words and carries the reason it is empty. */
  function renderLayers(order) {
    if (!order || !order.length) return '';
    return '<div class="am-layers">' + order.map((entry) => {
      /* Three states, not two. `null` means the store this layer reads has
       * not been loaded at all -- we do not know what it holds. Rendering
       * that as "nothing yet" would be the same conflation the rest of this
       * project spends its effort avoiding. */
      const unknown = entry.rows == null;
      const empty = !unknown && !entry.rows;
      const holding = unknown
        ? '<div class="am-layer-holds empty">not loaded — no figure to report</div>'
        : (empty
          ? `<div class="am-layer-holds empty">nothing yet${
              entry.empty_because ? ` — ${esc(entry.empty_because)}` : ''}</div>`
          : `<div class="am-layer-holds">${number(entry.rows)} ${esc(entry.unit || 'rows')}</div>`);
      return `<div class="am-layer${empty || unknown ? ' is-empty' : ''}">
         <div class="am-layer-name">${esc(entry.layer)}</div>
         ${holding}
         <div class="am-layer-answers">${esc(entry.answers)}</div>
         <div class="am-layer-not">${esc(entry.not)}</div>
       </div>`;
    }).join('') + '</div>';
  }

  // ---- observations -----------------------------------------------------
  function coverageRow(row) {
    const pct = Number(row.percent) || 0;
    const tone = pct === 0 ? 'none' : pct < 25 ? 'low' : '';
    return `<div class="am-cov-row">
        <span class="am-cov-name">${esc(row.field)}</span>
        <span class="am-cov-pct">${pct.toFixed(1)}% · ${number(row.filled)} of ${number(row.of)}</span>
        <span class="am-cov-track"><span class="am-cov-fill ${tone}" style="width:${Math.max(pct, 0)}%"></span></span>
        <span class="am-cov-note">${esc(row.note)}</span>
      </div>`;
  }

  function renderObservations(data) {
    const strict = data.strict_scope || {};
    const inactive = Object.entries(strict.inactive_by_status || {})
      .map(([status, n]) => `${number(n)} ${status.replace(/_/g, ' ')}`).join(' · ') || 'none';
    const figures = '<div class="am-figures">' + [
      figure(number(data.canonical_jobs), 'Canonical jobs'),
      figure(number(data.source_observations), 'Source observations'),
      figure(number(data.field_provenance_rows), 'Field provenance rows'),
      figure(number(data.status_history_rows), 'Status history rows'),
    ].join('') + '</div>';

    const scope = `<div class="am-figures">${[
      figure(`${number(strict.active)}<small> of ${number(strict.catalogue)}</small>`,
             'Strict scope: active of catalogue'),
      figure(esc(data.current_market_cycle), 'Current hiring cycle'),
      figure(number(data.market_cycle_known), 'Jobs with a known cycle'),
    ].join('')}</div>` +
      `<p class="am-sub">Not active: ${esc(inactive)}. Closed and status-unknown are ` +
      `different things and are never folded together.</p>`;

    const coverage = '<div class="am-section-head">Field coverage, strict active scope</div>' +
      '<div class="am-coverage">' +
      (data.field_coverage || []).map(coverageRow).join('') + '</div>';

    const fetches = Object.entries(data.detail_fetches || {})
      .map(([status, n]) => `<span class="am-chip ${status === 'ok' ? 'ok' : 'warn'}">${
        esc(status)} ${number(n)}</span>`).join('') ||
      '<span class="am-chip stop">no detail page read yet</span>';

    return card('Observations',
      `Since ${data.earliest_observation ? data.earliest_observation.slice(0, 10) : 'unknown'}` +
      ` · schema v${data.schema_version} · ${number(data.ingestion_runs)} ingestion runs`,
      figures + scope + coverage +
      `<div class="am-section-head">Detail page reads</div><div>${fetches}</div>` +
      caveat(data.bottleneck), 'am-wide');
  }

  // ---- raw archive ------------------------------------------------------
  function renderArchive(data) {
    const since = data.available_since ? data.available_since.slice(0, 10) : null;
    const figures = '<div class="am-figures">' + [
      figure(number(data.blobs), 'Stored pages'),
      figure(number(data.observations), 'Fetch records'),
      figure(bytes(data.stored_bytes), 'On disk'),
      figure(data.compression ? data.compression + '×' : '—', 'Compression'),
    ].join('') + '</div>';
    const kinds = Object.entries(data.by_kind || {})
      .map(([kind, n]) => `<span class="am-chip">${esc(kind)} ${number(n)}</span>`).join('');
    const bodiless = data.observations_without_body
      ? `<p class="am-sub">${number(data.observations_without_body)} record(s) have no body: ` +
        `a refusal or a challenge page. We asked and were turned away, which is ` +
        `different from never having looked.</p>` : '';
    return card('Raw source archive',
      since ? `Covering pages read from ${since} onward` : 'Not enabled',
      figures + (kinds ? `<div>${kinds}</div>` : '') + bodiless + caveat(data.why));
  }

  // ---- market snapshots -------------------------------------------------
  function sparkline(daily) {
    const points = (daily || []).filter((d) => d.active_jobs != null);
    if (points.length < 2) return '';
    const w = 300, h = 46, pad = 4;
    const values = points.map((d) => Number(d.new_jobs) || 0);
    const max = Math.max(...values, 1);
    const step = (w - pad * 2) / (points.length - 1);
    const coords = values.map((v, i) =>
      [pad + i * step, h - pad - (v / max) * (h - pad * 2)]);
    const line = coords.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const area = `${line} L${coords[coords.length - 1][0].toFixed(1)},${h - pad} L${pad},${h - pad} Z`;
    return `<svg class="am-spark" viewBox="0 0 ${w} ${h}" role="img"
        aria-label="New postings per day, peak ${max}">
      <path d="${area}" fill="var(--fc-blue-soft)"></path>
      <path d="${line}" fill="none" stroke="var(--fc-blue)" stroke-width="1.6"
        stroke-linejoin="round"></path>
      <circle cx="${coords[coords.length - 1][0].toFixed(1)}"
        cy="${coords[coords.length - 1][1].toFixed(1)}" r="2.4" fill="var(--fc-blue)"></circle>
    </svg><div class="am-spark-note">New postings per day, peak ${max}. ` +
      `${points.length} days from ${esc(points[0].snapshot_date)} to ` +
      `${esc(points[points.length - 1].snapshot_date)}.</div>`;
  }

  function renderSnapshots(data) {
    if (!data.days) {
      return card('Market snapshots', 'Nothing recorded yet',
        '<p class="am-empty">No day has been materialised. Run ' +
        '<code>scripts/backfill_market_snapshots.py --apply</code> to reconstruct ' +
        'from the history already held.</p>');
    }
    const figures = '<div class="am-figures">' + [
      figure(number(data.days), 'Days covered'),
      figure(number(data.rows), 'Snapshot rows'),
      figure(number(data.reconstructed_days), 'Reconstructed days'),
      figure(number(data.stable_panel_size), 'Sources in the stable panel'),
    ].join('') + '</div>';

    const rows = (data.daily || []).slice(-8).reverse().map((d) =>
      `<tr><td>${esc(d.snapshot_date)}</td><td class="num">${number(d.active_jobs)}</td>` +
      `<td class="num">${number(d.new_jobs)}</td><td class="num">${number(d.closed_jobs)}</td>` +
      `<td class="num">${number(d.deadline_changed)}</td><td class="num">${number(d.source_count)}</td>` +
      `<td>${d.reconstructed ? '<span class="am-chip warn">reconstructed</span>'
        : '<span class="am-chip ok">observed</span>'}</td></tr>`).join('');

    const panel = (data.stable_panel || []).map((name) =>
      `<span class="am-chip">${esc(name)}</span>`).join('');

    return card('Market snapshots',
      `${data.earliest || ''} onward · a materialisation, not the source of truth`,
      figures + sparkline(data.daily) +
      '<div class="am-section-head">Recent days</div>' +
      `<div class="am-scroll"><table class="am-table"><thead><tr>
        <th>Date</th><th>Active</th><th>New</th><th>Closed</th><th>Deadline moved</th>
        <th>Sources</th><th>Kind</th></tr></thead><tbody>${rows}</tbody></table></div>` +
      '<div class="am-section-head">Stable source panel</div>' +
      `<div>${panel || '<span class="am-chip stop">none</span>'}</div>` +
      caveat(data.panel_note) + caveat(data.reconstruction_note));
  }

  // ---- source x field coverage ------------------------------------------
  /* Two numbers that look alike and are not: how much of a discipline the
   * biggest board *carries*, and how much would be *lost* if it stopped. Where
   * postings are cross-listed those diverge, and only the second is risk. The
   * bar draws the second. */
  function riskBar(percent) {
    const p = Math.max(0, Math.min(100, Number(percent) || 0));
    const level = p >= 75 ? 'none' : (p >= 50 ? 'low' : '');
    return `<div class="am-cov-track am-risk"><div class="am-cov-fill ${level}"
      style="width:${p.toFixed(1)}%"></div></div>`;
  }

  function stateChip(state) {
    const tone = state === 'complete' ? 'ok'
      : (state === 'partial' ? 'warn' : 'stop');
    const label = state === 'not_read' ? 'never read'
      : (state === 'unverifiable' ? 'unverifiable' : state);
    return `<span class="am-chip ${tone}">${esc(label)}</span>`;
  }

  function renderCoverage(data) {
    if (!data || !data.sources || !data.sources.length) {
      return card('Source coverage', 'Not available',
        '<p class="am-empty">No source has contributed a posting in this scope.</p>');
    }
    const top = data.sources[0];
    const catalogue = data.sources.reduce((sum, row) => sum + (row.total_jobs || 0), 0);
    const figures = '<div class="am-figures">' + [
      figure(number(data.source_count), 'Sources contributing'),
      figure(number((data.silent_sources || []).length), 'Configured but silent'),
      figure(`${((100 * (top.total_jobs || 0)) / (catalogue || 1)).toFixed(0)}<small>%</small>`,
        `On ${top.source} alone`),
      figure(number((data.disciplines || []).length), 'Disciplines covered'),
      figure(number(data.folded_duplicates || 0), 'One vacancy, two boards'),
    ].join('') + '</div>';

    const disciplines = (data.disciplines || []).map((row) =>
      `<tr><td>${esc(row.discipline)}</td>
        <td class="num">${number(row.jobs)}</td>
        <td class="num">${number(row.sources_contributing)}</td>
        <td>${esc(row.largest_source || '—')}</td>
        <td class="num">${(row.largest_share || 0).toFixed(0)}%</td>
        <td class="num">${(row.largest_source_only_share || 0).toFixed(0)}%</td>
        <td class="num">${(row.single_sourced_share || 0).toFixed(0)}%</td>
        <td class="am-risk-cell">${riskBar(row.largest_source_only_share)}</td></tr>`).join('');

    const gaps = (data.gaps || []).map((row) =>
      `<tr><td>${esc(row.source)}</td><td>${esc(row.field)}</td>
        <td class="num">${(row.percent || 0).toFixed(1)}%</td>
        <td class="num">${number(row.missing)}</td>
        <td>${stateChip(row.completeness_state)}</td></tr>`).join('');

    const silent = (data.silent_sources || []).map((row) =>
      `<span class="am-chip ${row.completeness_state === 'not_read' ? 'stop' : 'warn'}">` +
      `${esc(row.source)} · ${esc(row.completeness_state)}</span>`).join('');

    return card('Source × field coverage',
      'Which board carries which discipline, and what each board leaves empty',
      figures +
      '<div class="am-section-head">If one board went dark</div>' +
      `<div class="am-scroll"><table class="am-table"><thead><tr>
        <th>Discipline</th><th>Postings</th><th>Boards</th><th>Largest board</th>
        <th>Carries</th><th>Would lose</th><th>On one board</th><th></th></tr></thead>
        <tbody>${disciplines}</tbody></table></div>` +
      caveat(data.concentration_note) + caveat(data.single_sourced_note) +
      '<div class="am-section-head">Largest field gaps</div>' +
      `<div class="am-scroll"><table class="am-table"><thead><tr>
        <th>Source</th><th>Field</th><th>Filled</th><th>Postings missing it</th>
        <th>Source read as</th></tr></thead><tbody>${gaps}</tbody></table></div>` +
      `<p class="am-sub">${esc(data.gap_note || '')}</p>` +
      (silent ? '<div class="am-section-head">Configured, contributed nothing</div>' +
        `<div>${silent}</div>` : '') +
      caveat(data.reading_note) + caveat(data.basis_note),
      'am-wide');
  }

  // ---- H-1B labour condition applications --------------------------------
  /* Kept as its own card rather than folded into a "sponsorship" total. PERM
   * is the permanent-residency step; an LCA is the wage attestation filed
   * before a temporary-visa petition. A school can file dozens of the second
   * and none of the first, so one combined number would answer neither
   * question. The card leads with the distinction that gets lost first:
   * a filing is not a hire. */
  function renderLca(lca) {
    if (!lca || !lca.fiscal_years || !lca.fiscal_years.length) {
      return card('H-1B filings (DOL LCA)', 'Not loaded',
        '<p class="am-empty">Run the LCA loader to populate this.</p>');
    }
    const totals = lca.business_totals || {};
    const wages = lca.business_wages || {};
    const figures = '<div class="am-figures">' + [
      figure(number(totals.cases), 'Business-faculty filings'),
      figure(`${number(totals.certified)}<small> of ${number(totals.cases)}</small>`,
        'Certified, not withdrawn'),
      figure(number(totals.new_employment), 'For a new hire'),
      figure(wages.median_annual_wage
        ? `$${Number(wages.median_annual_wage).toLocaleString()}`
        : '—', 'Median offered wage'),
    ].join('') + '</div>';

    const years = (lca.by_year || []).map((row) =>
      `<tr><td>FY${esc(row.fiscal_year)}</td>
        <td class="num">${number(row.cases)}</td>
        <td class="num">${number(row.certified)}</td>
        <td class="num">${number(row.new_employment)}</td>
        <td class="num">${number(row.employers)}</td></tr>`).join('');

    const employers = (lca.top_employers || []).map((row) =>
      `<tr><td>${esc(row.employer_name)}</td>
        <td class="num">${number(row.cases)}</td>
        <td class="num">${number(row.certified)}</td>
        <td class="num">${number(row.new_employment)}</td>
        <td class="num">${row.median_annual_wage
          ? '$' + Number(row.median_annual_wage).toLocaleString() : '—'}</td></tr>`).join('');

    /* An excluded row is named, not silently dropped: one keyed-in extra digit
     * ($8,155,283 against a $52,397 prevailing wage) reported an institution
     * at a $1.24m mean before this became a median. */
    const excluded = (wages.wage_rows_excluded
      ? `<p class="am-sub">${number(wages.wage_rows_excluded)} filing(s) excluded from ` +
        `the wage figures as keying errors, e.g. ` +
        (wages.excluded_examples || []).slice(0, 1).map((row) =>
          `${esc(row.employer_name)} at $${Number(row.wage_from).toLocaleString()} ` +
          `against a prevailing wage of $${Number(row.prevailing_wage).toLocaleString()}`)
          .join('') + '.</p>'
      : '');

    const evidence = Object.entries(lca.by_evidence || {}).map(([kind, n]) =>
      `<span class="am-chip">${esc(kind)} ${number(n)}</span>`).join('');

    return card('H-1B filings (DOL LCA)',
      `FY${lca.fiscal_years.join(', FY')} · ${number(lca.faculty_cases)} faculty filings, ` +
      `of which ${number(totals.cases)} under SOC ${esc(lca.business_soc)}`,
      figures +
      '<div class="am-section-head">By year, business faculty</div>' +
      `<div class="am-scroll"><table class="am-table"><thead><tr>
        <th>Year</th><th>Filings</th><th>Certified</th><th>New hire</th><th>Employers</th>
        </tr></thead><tbody>${years}</tbody></table></div>` +
      '<div class="am-section-head">Files most often</div>' +
      `<div class="am-scroll"><table class="am-table"><thead><tr>
        <th>Employer</th><th>Filings</th><th>Certified</th><th>New hire</th>
        <th>Median wage</th></tr></thead><tbody>${employers}</tbody></table></div>` +
      excluded +
      (evidence ? '<div class="am-section-head">How each filing was identified as faculty</div>' +
        `<div>${evidence}</div>` : '') +
      caveat(lca.caveat) + caveat(lca.versus_perm),
      'am-wide');
  }

  // ---- link health -------------------------------------------------------
  /* Whether the addresses this site hands out still open. Kept apart from
   * coverage because it answers a different question, and because only one of
   * its states is about a posting: a 404 is the file being gone, a 502 is the
   * publisher's server failing. Colouring them alike would invite reading an
   * outage as a wave of withdrawals. */
  function renderLinks(data) {
    if (!data || !data.available) {
      return card('Link health', 'Not available',
        `<p class="am-empty">${esc((data && data.reason) || 'No link check has run.')}</p>`);
    }
    const state = data.by_state || {};
    const checked = data.checked_links || 0;
    const figures = '<div class="am-figures">' + [
      figure(`${number(checked)}<small> of ${number(data.links_total)}</small>`,
        'Links checked'),
      figure(number(state.ok || 0), 'Open normally'),
      figure(number(data.postings_with_a_dead_link || 0), 'Genuinely dead (404)'),
      figure(number(Object.keys(data.hosts_down || {}).length), 'Hosts failing'),
    ].join('') + '</div>';

    /* `gone` is the only state that is evidence about a posting, so it is the
     * only one styled as a problem with the posting. */
    const tone = {ok: 'ok', gone: 'stop', server_error: 'warn',
                  blocked: 'warn', unreachable: 'warn'};
    const chips = Object.entries(state)
      .sort((a, b) => b[1] - a[1])
      .map(([name, n]) =>
        `<span class="am-chip ${tone[name] || 'warn'}">${
          esc(name.replace(/_/g, ' '))} ${number(n)}</span>`).join('');

    const down = Object.entries(data.hosts_down || {}).map(([host, info]) =>
      `<tr><td>${esc(host)}</td><td class="num">${number(info.links)}</td>` +
      `<td>${esc(String(info.host_down_state || '').replace(/_/g, ' '))}</td></tr>`).join('');

    return card('Link health',
      data.last_checked
        ? `Last checked ${esc(data.last_checked.slice(0, 10))} · ${
            number(data.links_unchecked)} not yet checked`
        : 'No check has run yet',
      figures +
      '<div class="am-section-head">By outcome</div>' +
      `<div>${chips || '<span class="am-chip stop">nothing checked</span>'}</div>` +
      (down ? '<div class="am-section-head">Hosts failing across the board</div>' +
        `<div class="am-scroll"><table class="am-table"><thead><tr>
          <th>Host</th><th>Links</th><th>Failing as</th></tr></thead>
          <tbody>${down}</tbody></table></div>` +
        caveat(data.hosts_down_note) : '') +
      caveat(data.reading_note));
  }

  // ---- official reference data ------------------------------------------
  function renderIpeds(ipeds) {
    if (!ipeds || !ipeds.years || !ipeds.years.length) {
      return card('Doctoral production (IPEDS)', 'Not loaded',
        '<p class="am-empty">Run the IPEDS loader to populate this.</p>');
    }
    const figures = '<div class="am-figures">' + [
      figure(number(ipeds.broad_doctoral_production), `Business doctorates ${ipeds.latest_year}`),
      figure(number(ipeds.research_academic_proxy_r1), 'At R1 institutions'),
      figure(number(ipeds.institutions), 'Institutions on file'),
      figure(number(ipeds.crosswalk_codes), 'CIP codes mapped'),
    ].join('') + '</div>';
    const fields = (ipeds.by_broad_field || []).slice(0, 7).map((row) =>
      `<tr><td>${esc(row.broad_field)}</td><td class="num">${number(row.doctorates)}</td>` +
      `<td class="num">${number(row.nonresident)}</td>` +
      `<td class="num">${number(row.institutions)}</td></tr>`).join('');
    return card('Doctoral production (IPEDS)',
      `Years loaded: ${ipeds.years.join(', ')} · ${number(ipeds.completion_rows)} rows`,
      figures +
      `<div class="am-scroll"><table class="am-table"><thead><tr>
        <th>Broad field</th><th>Doctorates</th><th>Nonresident</th><th>Institutions</th>
        </tr></thead><tbody>${fields}</tbody></table></div>` +
      caveat(ipeds.caveat));
  }

  function renderSed(sed) {
    if (!sed || !sed.benchmark) {
      return card('National benchmark (NSF SED)', 'Not loaded',
        '<p class="am-empty">Run the SED loader to populate this.</p>');
    }
    const b = sed.benchmark;
    const figures = '<div class="am-figures">' + [
      figure(number(b.business_research_doctorates), `Business research doctorates ${b.data_year}`),
      figure(b.temporary_visa_share != null ? b.temporary_visa_share + '%' : '—',
             'On a temporary visa'),
      figure(b.academe_share_of_employed != null ? b.academe_share_of_employed + '%' : '—',
             'Of the employed, into academe'),
      figure(b.tenure_track_share_of_academe != null ? b.tenure_track_share_of_academe + '%' : '—',
             'Of those, tenure-track'),
    ].join('') + '</div>';
    const funnel = `<div class="am-scroll"><table class="am-table"><tbody>
        <tr><td>Reported postgraduation plans</td><td class="num">${number(b.reporting_postgraduation_plans)}</td></tr>
        <tr><td>Definite employment</td><td class="num">${b.definite_employment_share}%</td></tr>
        <tr><td>Still seeking</td><td class="num">${b.seeking_share}%</td></tr>
        <tr><td><strong>Realised tenure-track outcomes (estimate)</strong></td>
            <td class="num"><strong>${number(b.realized_tt_outcomes_est)}</strong></td></tr>
      </tbody></table></div>`;
    /* Every loaded cycle, because the movement is the finding. One year shows
     * 1,356 doctorates; two show output down 10% while the share still seeking
     * employment at graduation went from 11.8% to 18.2%. Two cycles is a
     * comparison and not a trend, and the caveat says so rather than letting a
     * two-point table imply one. */
    const series = (sed.series || []).length > 1
      ? '<div class="am-section-head">By cycle</div>' +
        `<div class="am-scroll"><table class="am-table"><thead><tr>
          <th>Cycle</th><th>Doctorates</th><th>Temporary visa</th>
          <th>Definite job</th><th>Still seeking</th><th>Realised TT (est)</th>
          </tr></thead><tbody>${(sed.series || []).map((row) =>
            `<tr><td>${esc(row.data_year)}</td>
              <td class="num">${number(row.business_research_doctorates)}</td>
              <td class="num">${row.temporary_visa_share ?? '—'}%</td>
              <td class="num">${row.definite_employment_share ?? '—'}%</td>
              <td class="num">${row.seeking_share ?? '—'}%</td>
              <td class="num">${number(row.realized_tt_outcomes_est)}</td></tr>`).join('')
        }</tbody></table></div>` + caveat(sed.series_note)
      : '';

    return card('National benchmark (NSF SED)',
      `Years loaded: ${(sed.years || []).join(', ')} · ${number(sed.observations)} observations`,
      figures + funnel + series + caveat(b.not_a_candidate_supply));
  }

  function renderPerm(perm) {
    if (!perm || !perm.fiscal_years || !perm.fiscal_years.length) {
      return card('Sponsorship evidence (DOL PERM)', 'Not loaded',
        '<p class="am-empty">Run the PERM loader to populate this.</p>');
    }
    const matchRate = perm.faculty_cases
      ? (100 * perm.matched_cases / perm.faculty_cases).toFixed(1) : '0';
    const figures = '<div class="am-figures">' + [
      figure(number(perm.faculty_cases), `Faculty cases, FY${perm.fiscal_years.join(', FY')}`),
      figure(`${number(perm.matched_cases)}<small> · ${matchRate}%</small>`,
             'Matched to an institution'),
      figure(number(perm.with_phd_origin), 'With the PhD institution named'),
      figure(number((perm.matching || {}).queued), 'Names awaiting review'),
    ].join('') + '</div>';
    const evidence = Object.entries(perm.by_evidence || {}).map(([kind, n]) =>
      `<span class="am-chip ${kind === 'college_u_teacher_flag' ? 'ok' : 'warn'}">${
        esc(kind.replace(/_/g, ' '))} ${number(n)}</span>`).join('');
    const fields = (perm.top_fields || []).map((row) =>
      `<tr><td>${esc(row.field)}</td><td class="num">${number(row.cases)}</td></tr>`).join('');
    const queue = ((perm.matching || {}).queue_top || []).map((row) =>
      `<tr><td>${esc(row.name)}</td><td class="num">${number(row.occurrences)}</td></tr>`).join('');
    return card('Sponsorship evidence (DOL PERM)',
      'Identified by the form’s own college-teacher flag where possible, not by ' +
      'guessing at job titles',
      figures + `<div>${evidence}</div>` +
      '<div class="am-section-head">Business fields named</div>' +
      `<div class="am-scroll"><table class="am-table"><tbody>${fields}</tbody></table></div>` +
      (queue ? '<div class="am-section-head">Employers awaiting a person</div>' +
        `<div class="am-scroll"><table class="am-table"><tbody>${queue}</tbody></table></div>` +
        '<p class="am-sub">Unmatched names are queued, never dropped. Most are ' +
        'institutions this project has never held — medical centres, community ' +
        'colleges, foreign employers.</p>' : '') +
      caveat(perm.caveat));
  }

  function renderPipeline(pipeline) {
    const urls = pipeline.confirmed_urls || {};
    const confirmed = (urls.roster || 0) + (urls.job_market || 0) + (urls.placement || 0);
    const figures = '<div class="am-figures">' + [
      figure(number(pipeline.programs_registered), 'Programmes registered'),
      figure(number(confirmed), 'Page addresses confirmed'),
      figure(number(pipeline.snapshots), 'Page snapshots captured'),
    ].join('') + '</div>';
    const layers = (pipeline.layers || []).length
      ? (pipeline.layers || []).map((row) =>
          `<span class="am-chip">${esc(row.layer.replace(/_/g, ' '))} ${number(row.people)}</span>`).join('')
      : '<span class="am-chip stop">no person observed yet</span>';

    /* The four outcomes of reading a programme page, kept visually apart.
     * Only `confirmed` is evidence: `not_found` describes a website, and
     * `blocked` and `unreachable` mean we do not know what the page says.
     * Colouring them the same would invite reading a 404 as an absence. */
    const tone = {confirmed: 'ok', not_found: 'warn', blocked: 'stop',
                  unreachable: 'stop', unchecked: 'stop'};
    const discovery = (pipeline.discovery || []).map((row) =>
      `<span class="am-chip ${tone[row.status] || 'warn'}">` +
      `${esc(String(row.status).replace(/_/g, ' '))} ${number(row.programs)}</span>`).join('');

    return card('PhD pipeline panel',
      'Four layers, reported separately and never summed'
      + (pipeline.last_checked
         ? ` · pages last read ${esc(pipeline.last_checked.slice(0, 10))}` : ''),
      figures +
      (discovery ? '<div class="am-section-head">Reading each programme page</div>' +
        `<div>${discovery}</div>` : '') +
      '<div class="am-section-head">People observed, by layer</div>' +
      `<div>${layers}</div>` +
      caveat(pipeline.why_most_urls_are_still_missing) + caveat(pipeline.not_a_supply));
  }

  function renderReleases(official) {
    const rows = (official.releases || []).map((row) =>
      `<tr><td>${esc(row.dataset)}</td><td>${esc(row.release_key)}</td>` +
      `<td class="num">${esc(row.data_year)}</td><td class="num">${bytes(row.byte_size)}</td>` +
      `<td><code>${esc(row.sha)}</code></td>` +
      `<td>${esc((row.downloaded_at || '').slice(0, 10))}</td></tr>`).join('');
    const failed = (official.failed_loads || []).map((row) =>
      `<tr><td>${esc(row.dataset)}</td><td><span class="am-chip stop">${esc(row.status)}</span></td>` +
      `<td>${esc((row.error || '').slice(0, 90))}</td></tr>`).join('');
    return card('Where each figure came from',
      'Every official file is recorded with the URL that worked and the hash of what arrived',
      `<div class="am-scroll"><table class="am-table"><thead><tr>
         <th>Dataset</th><th>Release</th><th>Year</th><th>Size</th><th>SHA-256</th><th>Downloaded</th>
       </tr></thead><tbody>${rows || '<tr><td colspan="6">none</td></tr>'}</tbody></table></div>` +
      (failed ? '<div class="am-section-head">Failed loads</div>' +
        `<div class="am-scroll"><table class="am-table"><tbody>${failed}</tbody></table></div>` +
        '<p class="am-sub">A failure is a row, never a silent zero: without it a 404 ' +
        'and an empty year look identical.</p>' : ''));
  }

  function render(payload) {
    const app = $('am-app');
    if (!payload || !payload.ok) {
      app.innerHTML = `<div class="fc-note info">Could not read the observatory: ${
        esc((payload && payload.error) || 'unknown error')}</div>`;
      return;
    }
    const official = payload.official || {};
    const officialCards = official.available
      ? renderIpeds(official.ipeds) + renderSed(official.sed) +
        renderLca(official.lca) + renderPerm(official.perm) +
        renderReleases(official)
      : card('Official reference data', 'Not available',
          `<p class="am-empty">${esc(official.reason || 'the loaders have not run')}</p>`);

    app.innerHTML =
      renderLayers(payload.layer_order) +
      '<div class="am-grid">' +
      renderObservations(payload.observations || {}) +
      renderArchive(payload.archive || {}) +
      renderSnapshots(payload.snapshots || {}) +
      renderCoverage(payload.coverage || {}) +
      renderLinks(payload.links || {}) +
      renderPipeline(payload.pipeline || {}) +
      officialCards +
      '</div>';
  }

  async function load() {
    try {
      const response = await fetch('/api/academic-market/observatory', {
        headers: { Accept: 'application/json' },
      });
      render(await response.json());
    } catch (error) {
      $('am-app').innerHTML =
        `<div class="fc-note info">Could not reach the observatory endpoint: ${
          esc(error.message)}</div>`;
    }
  }

  document.addEventListener('DOMContentLoaded', load);
  if (document.readyState !== 'loading') load();
})();
