(function () {
  'use strict';

  const APP = document.getElementById('business-research-app');
  const READING_STATUSES = ['unread', 'reading', 'read'];
  const NOTE_TAGS = ['Theory', 'Method', 'Citation', 'Idea', 'Limitation', 'Future Research'];
  const PAPER_TABS = ['overview', 'theory', 'constructs', 'method', 'findings', 'notes'];

  const NAV = [
    ['Overview', '/abdc/research', 'overview'],
    ['Journals', '/abdc', 'journals'],
    ['Research Radar', '/abdc-astar-research', 'radar'],
    ['Theories', '/abdc/theories', 'theories'],
    ['Constructs', '/abdc/constructs', 'constructs'],
    ['Methods', '/abdc/methods', 'methods'],
    ['Landscape', '/abdc/landscape', 'landscape'],
    ['My Papers', '/abdc/library', 'library'],
  ];

  const TREND = {
    new: { glyph: '↑↑', label: 'new in the recent window' },
    up_strong: { glyph: '↑↑', label: 'up sharply' },
    up: { glyph: '↑', label: 'up' },
    flat: { glyph: '→', label: 'unchanged' },
    down: { glyph: '↓', label: 'down' },
  };

  // ── helpers ───────────────────────────────────────────────────────────────

  function esc(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function text(value, fallback) {
    return value == null || value === '' ? (fallback || '—') : String(value);
  }

  /** Thousands-separated count. Never use this for a year. */
  function num(value) {
    return value == null || value === '' ? '—' : Number(value).toLocaleString();
  }

  /** Plain integer, for years and other non-quantity numbers. */
  function plain(value, fallback) {
    return value == null || value === '' ? (fallback || '—') : String(value);
  }

  function pct(value) {
    return value == null ? '' : Number(value).toFixed(1) + '%';
  }

  function plural(count, singular, pluralForm) {
    return num(count) + ' ' + (Number(count) === 1 ? singular : (pluralForm || singular + 's'));
  }

  function refName(ref) {
    if (ref == null) return '';
    if (typeof ref === 'string') return ref;
    return ref.name || ref.label || ref.id || '';
  }

  function pathWithoutSlash() {
    const path = window.location.pathname.replace(/\/+$/, '');
    return path || '/';
  }

  function currentRoute() {
    const path = pathWithoutSlash();
    const parts = path.split('/').filter(Boolean);
    if (path === '/abdc/research' || path === '/research') return { kind: 'overview' };
    if (parts[0] === 'research') parts.shift();
    if (parts[0] === 'abdc') parts.shift();
    if (parts[0] === 'research') parts.shift();
    if (parts[0] === 'theories') return parts[1] ? { kind: 'theory', slug: decodeURIComponent(parts[1]) } : { kind: 'theories' };
    if (parts[0] === 'constructs') return parts[1] ? { kind: 'construct', slug: decodeURIComponent(parts[1]) } : { kind: 'constructs' };
    if (parts[0] === 'methods') return parts[1] ? { kind: 'method', slug: decodeURIComponent(parts[1]) } : { kind: 'methods' };
    if (parts[0] === 'papers' && parts[1]) return { kind: 'paper', id: parts[1] };
    if (parts[0] === 'landscape') return { kind: 'landscape' };
    if (parts[0] === 'library') return { kind: 'library' };
    return { kind: 'overview' };
  }

  /** The browser tab must say which page this is, not just which app. */
  function setPageTitle(title) {
    document.title = title ? title + ' · Business Research' : 'Business Research Workspace';
  }

  function activeNav(kind) {
    return NAV.map(function (item) {
      const active = item[2] === kind;
      return '<a href="' + item[1] + '"' + (active ? ' class="is-active" aria-current="page"' : '') + '>' +
        esc(item[0]) + '</a>';
    }).join('');
  }

  /**
   * The shared research-nav.js owns the ABDC tab strip. Keep this local nav
   * only as a standalone fallback, otherwise every Business Research route
   * would show two different versions of the same navigation.
   */
  function fallbackNav(kind) {
    if (document.body && document.body.classList.contains('research-nav-mounted')) return '';
    return '<nav class="br-subnav br-subnav-fallback" aria-label="Business Research navigation">' +
      activeNav(kind) + '</nav>';
  }

  /**
   * Page chrome. Detail pages render their own <h1> inside the body, so the
   * shell heading is suppressed there to keep exactly one <h1> per document.
   */
  function pageShell(options) {
    const showHeading = options.heading !== false;
    return '<div class="br-breadcrumb"><a href="/">Research Tools</a> / <a href="/abdc/research">Business Research</a>' +
      (options.crumb ? ' / ' + esc(options.crumb) : '') + '</div>' +
      (showHeading
        ? '<header class="br-page-banner"><div class="br-page-banner-inner"><div><div class="br-page-kicker">ABDC 商科研究</div>' +
          '<h1>' + esc(options.title) + '</h1>' +
          '<p>' + esc(options.subtitle || '') + '</p></div>' +
          '<div class="br-header-actions">' + (options.actions || '') + '</div></div></header>'
        : '') +
      fallbackNav(options.nav) +
      '<div class="br-page-body">' + (options.body || '') + '</div>';
  }

  function loading(label) {
    return '<div class="br-loading"><div class="br-spinner" role="status" aria-label="' +
      esc(label || 'Loading') + '"></div></div>';
  }

  function errorView(error) {
    const message = error && error.message ? error.message : String(error || 'Unknown error');
    return '<div class="br-error" role="alert"><strong>Unable to load research data.</strong>' +
      '<div>' + esc(message) + '</div>' +
      '<button type="button" class="br-button primary" data-retry="1" style="margin-top:10px">Retry</button></div>';
  }

  function emptyView(title, message) {
    return '<div class="br-empty"><strong>' + esc(title) + '</strong>' + esc(message || '') + '</div>';
  }

  /** Render a list, or an explicit empty state — never a blank container. */
  function listOrEmpty(items, render, emptyTitle, emptyMessage, wrapOpen, wrapClose) {
    const list = Array.isArray(items) ? items : [];
    if (!list.length) return emptyView(emptyTitle, emptyMessage);
    return (wrapOpen || '') + list.map(render).join('') + (wrapClose || '');
  }

  async function getJSON(url) {
    const response = await fetch(url, { cache: 'no-store' });
    let payload;
    try { payload = await response.json(); } catch (error) { payload = {}; }
    if (!response.ok || payload.success === false) {
      throw new Error(payload.error || ('HTTP ' + response.status));
    }
    return payload;
  }

  async function postJSON(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    let payload;
    try { payload = await response.json(); } catch (error) { payload = {}; }
    if (!response.ok || payload.success === false) {
      throw new Error(payload.error || ('HTTP ' + response.status));
    }
    return payload;
  }

  function dataBoundary(data) {
    const boundary = data && data.data_boundary;
    if (!boundary) return '';
    const catalog = boundary.catalog || {};
    const papers = boundary.papers || {};
    const inference = boundary.inference || {};
    return '<div class="br-notice info br-small"><b>Data boundary:</b> ' +
      'Catalog = ' + esc(catalog.status || 'unknown') + '. ' +
      'Papers = ' + esc(papers.status || 'unknown') + ' (' + esc(papers.source || '') + '). ' +
      'Construct links use ' + esc(inference.constructs || 'explicit metadata') + '. ' +
      esc(inference.tag_precision || '') +
      (boundary.sampled ? ' This result uses a bounded sample of ' + num(boundary.sample_size) + ' records.' : '') +
      '</div>';
  }

  function tagRow(items, className) {
    const list = Array.isArray(items) ? items : [];
    if (!list.length) return '';
    return '<div class="br-tag-row">' + list.map(function (item) {
      return '<span class="br-tag ' + (className || '') + '">' + esc(refName(item)) + '</span>';
    }).join('') + '</div>';
  }

  /** Chinese term shown beside the English one; English stays authoritative. */
  function zhName(entity) {
    const zh = entity && (entity.name_zh || entity.description_zh);
    return entity && entity.name_zh
      ? '<span class="br-zh-name">' + esc(entity.name_zh) + '</span>' : '';
  }

  function zhDefinition(entity) {
    const zh = entity && (entity.definition_zh || entity.description_zh);
    return zh ? '<p class="br-lede-zh" lang="zh">' + esc(zh) + '</p>' : '';
  }

  function seminalWorks(works, note) {
    const list = works || [];
    if (!list.length) {
      return emptyView('No source records recorded',
        'Add a verified origin, construct/measurement, or method-foundation source to the catalog.');
    }
    const roleLabels = {
      theory_origin: 'Theory origin', theory_review: 'Theory review',
      theory_extension: 'Theory extension', theory_source: 'Theory source',
      construct_definition: 'Construct definition',
      construct_definition_measurement: 'Definition + measurement',
      construct_measurement: 'Construct measurement',
      construct_definition_review: 'Construct review',
      method_origin: 'Method origin', method_foundation: 'Method foundation',
      method_foundation_review: 'Method review',
    };
    return '<div class="br-list">' + list.map(function (work) {
      const badge = work.verified
        ? '<span class="br-badge green">verified</span>'
        : '<span class="br-badge amber">pending check</span>';
      const kind = work.kind === 'origin' ? 'Origin'
        : work.kind === 'major_review' ? 'Review' : 'Extension';
      const doiLink = work.doi_url
        ? ' · <a href="' + esc(work.doi_url) + '" target="_blank" rel="noopener noreferrer">DOI ↗</a>'
        : '';
      const sourceLink = work.source_url
        ? ' · <a href="' + esc(work.source_url) + '" target="_blank" rel="noopener noreferrer">' +
          (work.access_is_full_text ? 'Original/full text ↗' : 'Source page ↗') + '</a>'
        : '';
      const role = roleLabels[work.source_role] || work.source_role || kind;
      const cited = work.cited_by_count != null
        ? ' · cited ' + num(work.cited_by_count) : '';
      return '<div class="br-list-item is-static"><strong>' + esc(work.authors) + ' (' +
        esc(plain(work.year)) + '). ' + esc(work.title) + '</strong>' +
        '<span>' + esc(work.venue || 'venue not recorded') + ' · ' + esc(role) + ' ' + badge +
        doiLink + sourceLink + cited +
        ' · ' + esc(work.display_status || 'check primary source') +
        ' · ' + esc(work.access_display_status || 'full-text access not checked') +
        (work.verification_note ? ' · ' + esc(work.verification_note) : '') + '</span></div>';
    }).join('') + '</div>' +
      (note ? '<div class="br-notice br-small" style="margin-top:10px">' + esc(note) + '</div>' : '');
  }

  function relationshipText(items, emptyMessage) {
    const list = Array.isArray(items) ? items : [];
    return list.length ? list.map(refName).join(' · ') : emptyMessage;
  }

  function scholarSummary(data) {
    const explicit = Array.isArray(data.key_scholars) ? data.key_scholars : [];
    if (explicit.length) return esc(explicit.join(' · '));
    const sourceAuthors = Array.isArray(data.source_authors) ? data.source_authors : [];
    if (!sourceAuthors.length) return esc(data.key_scholars_note || 'No scholar attribution recorded');
    return '<div class="br-source-author-list">' + sourceAuthors.map(function (row) {
      const badge = row.verified
        ? '<span class="br-badge green">verified source</span>'
        : '<span class="br-badge amber">catalog lead</span>';
      return '<div class="br-source-author"><strong>' + esc(row.authors) + '</strong> ' + badge +
        '<span>' + esc(row.work_title || 'Catalog work') + ' (' + esc(plain(row.year)) + ')' +
        ' · ' + esc(row.display_status || 'check primary source') + '</span></div>';
    }).join('') + '</div>' +
      '<div class="br-field-note">Source authors are transcribed from catalog works; they are not a canonical or exhaustive key-scholar list.</div>';
  }

  function entityPath(kind, id) {
    return '/abdc/' + kind + '/' + encodeURIComponent(id);
  }

  function paperPath(id) {
    return '/abdc/papers/' + encodeURIComponent(id);
  }

  function paperList(papers, emptyTitle, emptyMessage) {
    return listOrEmpty(papers, function (paper) {
      return '<a class="br-list-item" href="' + paperPath(paper.id) + '">' +
        '<strong>' + esc(text(paper.title, 'Untitled paper')) + '</strong>' +
        '<span>' + esc(text(paper.journal, 'Journal unavailable')) + ' · ' +
        esc(plain(paper.year, 'Year unavailable')) +
        (paper.rank ? ' · ABDC ' + esc(paper.rank) : '') +
        (paper.cited_by_count != null ? ' · citations ' + num(paper.cited_by_count) : '') +
        (paper.note_count ? ' · ' + num(paper.note_count) + ' notes' : '') +
        (paper.reading_status ? ' · ' + esc(paper.reading_status) : '') +
        (paper.favorite ? ' · favorite' : '') +
        '</span></a>';
    }, emptyTitle || 'No linked papers',
       emptyMessage || 'No verified linked paper records are available in the current A* cache.',
       '<div class="br-list">', '</div>');
  }

  function section(title, content, meta) {
    return '<section class="br-section"><div class="br-section-title"><h2>' + esc(title) + '</h2>' +
      (meta ? '<span>' + esc(meta) + '</span>' : '') + '</div>' +
      '<div class="br-section-body">' + content + '</div></section>';
  }

  function copyText(value, button) {
    const done = function () {
      if (!button) return;
      const old = button.dataset.label || button.textContent;
      button.dataset.label = old;
      button.textContent = 'Copied';
      window.setTimeout(function () { button.textContent = old; }, 1300);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(value).then(done).catch(function () { window.prompt('Copy this text', value); });
    } else {
      window.prompt('Copy this text', value);
    }
  }

  function bindRetry(container, fn) {
    const retry = container.querySelector('[data-retry="1"]');
    if (retry) retry.addEventListener('click', fn);
  }

  // ── storage layer ─────────────────────────────────────────────────────────
  // Every browser-persisted value goes through this object so the storage
  // backend can be swapped for a server account later without touching views.

  const ResearchStore = (function () {
    const KEYS = {
      state: 'business_research_local_state_v1',
      notes: 'business_research_local_notes_v1',
      recents: 'business_research_recent_papers_v1',
      saved: 'business_research_saved_entities_v1',
    };

    function read(key, fallback) {
      try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : fallback;
      } catch (error) { return fallback; }
    }

    function write(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); return true; }
      catch (error) { return false; }
    }

    return {
      keys: KEYS,

      /**
       * Paper workspace. Anything the server could not persist is merged back
       * in from local storage, so a failed write stays visible to the user
       * instead of vanishing on the next load.
       */
      async workspace(id) {
        const data = await getJSON('/api/abdc/research/papers/' + encodeURIComponent(id));
        const localState = read(KEYS.state, {})[String(id)];
        const localNotes = read(KEYS.notes, {})[String(id)] || [];
        if (localState) {
          data.library_state = Object.assign({}, data.library_state, localState);
          data.paper.status = data.library_state.reading_status || data.paper.status;
          data.paper.favorite = Boolean(data.library_state.favorite);
          data.local_state_pending = true;
        }
        if (localNotes.length) {
          const serverIds = new Set((data.notes || []).map(function (n) { return String(n.id); }));
          const pending = localNotes.filter(function (n) { return !serverIds.has(String(n.id)); });
          data.notes = pending.concat(data.notes || []);
          data.local_notes_pending = pending.length;
        }
        return data;
      },

      async setState(id, patch) {
        try {
          const result = await postJSON('/api/abdc/research/papers/' + encodeURIComponent(id) + '/state', patch);
          const all = read(KEYS.state, {});
          delete all[String(id)];
          write(KEYS.state, all);
          return result;
        } catch (error) {
          const all = read(KEYS.state, {});
          all[String(id)] = Object.assign({}, all[String(id)], patch, { updated_at: new Date().toISOString() });
          write(KEYS.state, all);
          return { success: true, state: all[String(id)], local_only: true };
        }
      },

      async saveNote(id, note) {
        try {
          return await postJSON('/api/abdc/research/papers/' + encodeURIComponent(id) + '/notes', note);
        } catch (error) {
          const all = read(KEYS.notes, {});
          const list = all[String(id)] || [];
          const saved = {
            id: note.note_id || ('local-' + Date.now()),
            paper_id: Number(id),
            note_text: note.note_text,
            tags: note.tags || [],
            updated_at: new Date().toISOString(),
            local_only: true,
          };
          all[String(id)] = [saved].concat(list.filter(function (n) { return String(n.id) !== String(saved.id); }));
          write(KEYS.notes, all);
          return { success: true, note: saved, local_only: true };
        }
      },

      async deleteNote(id, noteId) {
        if (String(noteId).indexOf('local-') === 0) {
          const all = read(KEYS.notes, {});
          all[String(id)] = (all[String(id)] || []).filter(function (n) { return String(n.id) !== String(noteId); });
          write(KEYS.notes, all);
          return { success: true, local_only: true };
        }
        return postJSON('/api/abdc/research/papers/' + encodeURIComponent(id) +
          '/notes/' + encodeURIComponent(noteId) + '/delete', {});
      },

      recents() { return read(KEYS.recents, []); },

      pushRecent(id, title) {
        const list = this.recents().filter(function (item) { return String(item.id) !== String(id); });
        list.unshift({ id: String(id), title: title, opened_at: new Date().toISOString() });
        write(KEYS.recents, list.slice(0, 20));
      },

      savedEntities() { return read(KEYS.saved, []); },

      isSaved(kind, id) {
        return this.savedEntities().some(function (item) { return item.kind === kind && item.id === id; });
      },

      toggleSaved(kind, id, name) {
        const list = this.savedEntities();
        const index = list.findIndex(function (item) { return item.kind === kind && item.id === id; });
        if (index >= 0) { list.splice(index, 1); }
        else { list.unshift({ kind: kind, id: id, name: name, saved_at: new Date().toISOString() }); }
        write(KEYS.saved, list.slice(0, 100));
        return index < 0;
      },
    };
  })();

  // ── shared views ──────────────────────────────────────────────────────────

  function mappingBadge(entity) {
    if (!entity || entity.mapping_status === 'mapped_precise_tag') return '';
    const label = entity.mapping_status === 'broad_tag_only' ? 'broad tag only'
      : entity.mapping_status === 'no_classifier_tag_in_cache' ? 'no classifier tag'
      : 'no tagged papers';
    return '<span class="br-badge amber" title="' + esc(entity.mapping_note || '') + '">' + esc(label) + '</span>';
  }

  function provenanceLabel(entity) {
    if (!entity) return '';
    if (entity.source_pack === 'management-organization-60') {
      return 'Book source · chapter starts p.' + esc(entity.source_page || '—');
    }
    if (entity.data_status === 'curated_scaffold') return 'Curated scaffold · verify sources';
    return entity.data_status || 'Catalog record';
  }

  function sourceTextView(source) {
    if (!source) return '';
    const status = source.status === 'ocr_derived_available'
      ? 'OCR-derived text available locally'
      : 'OCR text not ingested';
    const printed = source.printed_page_start
      ? 'Printed pages ' + plain(source.printed_page_start) +
        (source.printed_page_end ? '–' + plain(source.printed_page_end) : '+')
      : 'Printed page unavailable';
    const pdf = source.pdf_page_start
      ? 'PDF pages ' + plain(source.pdf_page_start) +
        (source.pdf_page_end ? '–' + plain(source.pdf_page_end) : '+')
      : 'PDF page locator unavailable';
    const match = source.ocr_title_match || {};
    const matchLabel = (match.english || match.chinese)
      ? 'Chapter title found on the locator page'
      : 'Title match still needs human review';
    const evidence = source.evidence_queue || {};
    const evidenceLabel = evidence.status === 'needs_human_coding'
      ? 'T–C–M evidence coding pending'
      : evidence.status === 'partially_human_coded'
        ? 'T–C–M evidence partially coded'
        : evidence.status === 'verified'
          ? 'T–C–M evidence verified'
          : (evidence.status || 'Evidence queue not initialized');
    const evidenceDetail = evidence.evidence_count != null
      ? evidenceLabel + ' · ' + plain(evidence.evidence_count) + ' page notes'
      : evidenceLabel;
    return '<div class="br-field-grid">' +
      '<div class="br-field"><div class="br-field-label">Text layer</div><div class="br-field-value">' +
      esc(status) + '</div></div>' +
      '<div class="br-field"><div class="br-field-label">Page locators</div><div class="br-field-value">' +
      esc(printed + ' · ' + pdf) + '</div></div>' +
      '<div class="br-field"><div class="br-field-label">Locator check</div><div class="br-field-value">' +
      esc(matchLabel + (source.chapter_locator_status ? ' · ' + source.chapter_locator_status : '')) +
      '</div></div>' +
      '<div class="br-field"><div class="br-field-label">Evidence ledger</div><div class="br-field-value">' +
      esc(evidenceDetail) +
      '</div></div></div>' +
      '<div class="br-notice br-small" style="margin-top:12px">' + esc(source.note ||
        'OCR is a derived reading aid. Review the original page before citing a claim.') + '</div>';
  }

  function countLine(entity) {
    const parts = ['<span class="br-count">' + plural(entity.paper_count, 'linked paper') + '</span>'];
    if (entity.broad_paper_count) {
      parts.push('<span class="br-count-broad">+' + num(entity.broad_paper_count) +
        ' under broader tag ' + esc((entity.broad_tags || []).join(', ')) + '</span>');
    }
    return parts.join('<span aria-hidden="true">·</span>');
  }

  function renderCard(entity, kind) {
    const href = entityPath(kind, entity.slug || entity.id);
    const typeLabel = kind === 'theories' ? 'Theory'
      : kind === 'methods' ? text(entity.category, 'Method') : 'Construct';
    const tags = kind === 'theories' ? entity.core_construct_refs
      : kind === 'methods' ? [entity.sub_category] : entity.roles;
    return '<a class="br-card is-clickable" href="' + href + '">' +
      '<div class="br-card-header"><div><h3>' + esc(entity.name) + '</h3>' + zhName(entity) +
      (entity.abbreviation ? '<div class="br-card-meta">' + esc(entity.abbreviation) + '</div>' : '') + '</div>' +
      '<div class="br-card-badges"><span class="br-badge ' +
      (kind === 'methods' ? 'purple' : kind === 'constructs' ? 'green' : 'blue') + '">' +
      esc(typeLabel) + '</span>' + mappingBadge(entity) + '</div></div>' +
      '<div class="br-card-meta">' + esc((entity.discipline || []).join(' · ') || entity.sub_category || '') + '</div>' +
      '<p class="br-card-description">' + esc(entity.definition || entity.description || '') + '</p>' +
      tagRow(tags) +
      '<div class="br-card-foot">' + countLine(entity) +
      '<span aria-hidden="true">·</span><span>' + esc(provenanceLabel(entity)) + '</span></div></a>';
  }

  /** Chips that link back into the catalog, with an explicit empty state. */
  function refCards(refs, kind, emptyTitle, emptyMessage) {
    return listOrEmpty(refs, function (item) {
      const id = item.id || item.slug;
      const label = refName(item);
      if (!id) {
        return '<div class="br-card"><h3>' + esc(label) + '</h3>' +
          '<div class="br-card-meta">Not in the catalog yet</div></div>';
      }
      return '<a class="br-card is-clickable" href="' + entityPath(kind, id) + '"><h3>' + esc(label) + '</h3>' +
        '<div class="br-card-meta">' + esc(item.abbreviation || item.category || item.definition || 'Open detail') + '</div></a>';
    }, emptyTitle, emptyMessage, '<div class="br-grid br-grid-3">', '</div>');
  }

  function flowChain(items, emptyMessage) {
    const list = (items || []).filter(Boolean);
    if (!list.length) return '<div class="br-card-meta">' + esc(emptyMessage || 'Not loaded') + '</div>';
    return '<div class="br-flow">' + list.map(function (item, index) {
      const label = refName(item);
      const node = item && item.id
        ? '<a class="br-flow-node" href="' + entityPath('constructs', item.id) + '">' + esc(label) + '</a>'
        : '<span class="br-flow-node">' + esc(label) + '</span>';
      return node + (index < list.length - 1 ? '<span class="br-flow-arrow" aria-hidden="true">→</span>' : '');
    }).join('') + '</div>';
  }

  // ── modal ─────────────────────────────────────────────────────────────────

  function openModal(title, subtitle, body, footer) {
    const opener = document.activeElement;
    const backdrop = document.createElement('div');
    backdrop.className = 'br-modal-backdrop';
    backdrop.innerHTML = '<div class="br-modal" role="dialog" aria-modal="true" aria-labelledby="br-modal-title">' +
      '<div class="br-modal-header"><div><h2 id="br-modal-title">' + esc(title) + '</h2>' +
      (subtitle ? '<div class="br-card-meta">' + esc(subtitle) + '</div>' : '') + '</div>' +
      '<button type="button" class="br-button" data-close-modal="1">Close</button></div>' +
      '<div class="br-modal-body">' + body + '</div>' +
      (footer ? '<div class="br-modal-footer">' + footer + '</div>' : '') + '</div>';
    document.body.appendChild(backdrop);
    document.body.classList.add('br-modal-open');

    const dialog = backdrop.querySelector('.br-modal');
    const focusables = function () {
      return Array.prototype.filter.call(
        dialog.querySelectorAll('a[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])'),
        function (el) { return el.offsetParent !== null; });
    };

    function close() {
      document.removeEventListener('keydown', onKey, true);
      backdrop.remove();
      document.body.classList.remove('br-modal-open');
      if (opener && typeof opener.focus === 'function') opener.focus();
    }

    function onKey(event) {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (event.key !== 'Tab') return;
      const items = focusables();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }

    document.addEventListener('keydown', onKey, true);
    backdrop.addEventListener('click', function (event) { if (event.target === backdrop) close(); });
    backdrop.querySelector('[data-close-modal]').addEventListener('click', close);
    const items = focusables();
    if (items.length) items[0].focus();
    return close;
  }

  // ── overview ──────────────────────────────────────────────────────────────

  function renderOverview() {
    setPageTitle('Overview');
    APP.innerHTML = pageShell({
      title: 'Business Research Workspace',
      subtitle: 'A connected workspace for ABDC journals, A* papers, theories, constructs, methods, and descriptive literature landscapes.',
      nav: 'overview',
      body: loading('Loading overview'),
    });
    const content = APP.lastElementChild;
    getJSON('/api/abdc/research/overview').then(function (data) {
      const counts = data.counts || {};
      const recent = (data.recent_papers || []).map(function (paper) {
        return {
          id: paper.id, title: paper.title, journal: paper.journal_title,
          year: String(paper.publication_date || '').slice(0, 4),
          rank: paper.journal_abdc_rating, cited_by_count: paper.cited_by_count,
        };
      });
      const kpis = [['Papers', counts.papers], ['A* papers', counts.a_star], ['A papers', counts.a],
                    ['Theories', counts.theories], ['Constructs', counts.constructs], ['Methods', counts.methods]];
      const entries = [
        ['Theory Library', '理论、构念、经典论文与研究脉络。', '/abdc/theories', 'blue'],
        ['Methods Lab', '研究设计、统计分析与计算方法。', '/abdc/methods', 'purple'],
        ['Paper Workspace', '从真实 A* 文章进入笔记、状态和交叉链接。', '/abdc/library', 'green'],
        ['Literature Landscape', '基于可用缓存观察主题、理论、方法和组合。', '/abdc/landscape', 'amber'],
      ];
      content.innerHTML =
        '<div class="br-kpis">' + kpis.map(function (item) {
          return '<div class="br-kpi"><div class="br-kpi-value">' + num(item[1]) + '</div>' +
            '<div class="br-kpi-label">' + esc(item[0]) + '</div></div>';
        }).join('') + '</div>' +
        '<div class="br-grid br-grid-4">' + entries.map(function (item) {
          return '<a class="br-card is-clickable" href="' + item[2] + '">' +
            '<span class="br-badge ' + item[3] + '">' + esc(item[0]) + '</span>' +
            '<h3 style="margin-top:12px">' + esc(item[0]) + '</h3><p>' + esc(item[1]) + '</p>' +
            '<div class="br-card-foot">Open workspace →</div></a>';
        }).join('') + '</div>' +
        section('Research entry points',
          '<div class="br-grid br-grid-3">' +
          '<a class="br-card is-clickable" href="/abdc"><h3>ABDC Journals</h3><p>Review journal quality lists and the current ABDC source boundary.</p></a>' +
          '<a class="br-card is-clickable" href="/abdc-astar-research"><h3>A* Research Radar</h3><p>Inspect the existing article cache, source records, classification, and abstract provenance.</p></a>' +
          '<a class="br-card is-clickable" href="/abdc/landscape"><h3>Descriptive Landscape</h3><p>Use a topic query to see where the available corpus is concentrated.</p></a></div>') +
        section('Recently available papers', paperList(recent, 'No recent papers',
          'The A* cache has not returned recent records yet.'), 'Existing A* cache') +
        dataBoundary(data);
    }).catch(function (error) {
      content.innerHTML = errorView(error);
      bindRetry(content, renderOverview);
    });
  }

  // ── catalog lists ─────────────────────────────────────────────────────────

  const CATALOG_META = {
    theories: {
      title: 'Theory Library',
      subtitle: '探索商科研究中的核心理论、构念、经典论文和最新应用。',
      placeholder: 'Search theories, constructs, keywords… 支持中文，如「社会交换」',
      label: 'theory',
    },
    constructs: {
      title: 'Construct Library',
      subtitle: '从定义、理论关系、测量元数据和实际论文使用情况进入构念。',
      placeholder: 'Search constructs or keywords… 支持中文，如「职业倦怠」',
      label: 'construct',
    },
    methods: {
      title: 'Methods Lab',
      subtitle: '研究设计、统计分析和计算社会科学方法的实用指南。',
      placeholder: 'Search methods… 支持中文，如「双重差分」',
      label: 'method',
    },
  };

  function renderCatalogList(kind) {
    const meta = CATALOG_META[kind];
    setPageTitle(meta.title);
    APP.innerHTML = pageShell({
      title: meta.title, subtitle: meta.subtitle, nav: kind,
      body: '<div id="br-catalog-page">' + loading('Loading ' + meta.label + 's') + '</div>',
    });
    const page = document.getElementById('br-catalog-page');
    const url = new URL(window.location.href);
    let query = url.searchParams.get('q') || '';
    let discipline = url.searchParams.get('discipline') || '';
    let category = url.searchParams.get('category') || 'all';

    function load() {
      page.innerHTML = loading('Loading ' + meta.label + 's');
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (discipline) params.set('discipline', discipline);
      if (kind === 'methods' && category && category !== 'all') params.set('category', category);
      const suffix = params.toString();
      history.replaceState(null, '', window.location.pathname + (suffix ? '?' + suffix : ''));
      getJSON('/api/abdc/research/' + kind + (suffix ? '?' + suffix : '')).then(function (data) {
        const entities = data.entities || [];
        const controls =
          '<form class="br-toolbar" id="br-catalog-form" role="search">' +
          '<label class="br-visually-hidden" for="br-catalog-query">' + esc(meta.placeholder) + '</label>' +
          '<input id="br-catalog-query" name="q" type="search" placeholder="' + esc(meta.placeholder) + '" value="' + esc(query) + '">' +
          (kind !== 'methods'
            ? '<label class="br-visually-hidden" for="br-catalog-discipline">Discipline</label>' +
              '<select id="br-catalog-discipline" class="br-select">' +
              '<option value="">All disciplines</option>' +
              (data.disciplines || []).map(function (item) {
                return '<option value="' + esc(item) + '"' + (item === discipline ? ' selected' : '') + '>' + esc(item) + '</option>';
              }).join('') + '</select>'
            : '<label class="br-visually-hidden" for="br-catalog-category">Method category</label>' +
              '<select id="br-catalog-category" class="br-select">' +
              '<option value="all">All method categories</option>' +
              (data.categories || []).map(function (item) {
                return '<option value="' + esc(item) + '"' + (item === category ? ' selected' : '') + '>' + esc(item) + '</option>';
              }).join('') + '</select>') +
          '<button type="submit" class="br-button primary">Search</button>' +
          '<span class="br-toolbar-note">' + plural(entities.length, 'catalog record') + '</span></form>';
        page.innerHTML = controls + dataBoundary(data) +
          listOrEmpty(entities, function (entity) { return renderCard(entity, kind); },
            'No ' + meta.label + 's found', 'Try another keyword or filter.',
            '<div class="br-grid br-grid-3">', '</div>');

        const form = document.getElementById('br-catalog-form');
        const queryInput = document.getElementById('br-catalog-query');
        form.addEventListener('submit', function (event) {
          event.preventDefault();
          query = queryInput ? queryInput.value.trim() : '';
          load();
        });
        const disciplineInput = document.getElementById('br-catalog-discipline');
        if (disciplineInput) disciplineInput.addEventListener('change', function () {
          discipline = disciplineInput.value; load();
        });
        const categoryInput = document.getElementById('br-catalog-category');
        if (categoryInput) categoryInput.addEventListener('change', function () {
          category = categoryInput.value; load();
        });
      }).catch(function (error) {
        page.innerHTML = errorView(error);
        bindRetry(page, load);
      });
    }
    load();
  }

  // ── theory detail ─────────────────────────────────────────────────────────

  function savedButton(kind, id, name) {
    const saved = ResearchStore.isSaved(kind, id);
    return '<button type="button" class="br-button' + (saved ? ' success' : '') +
      '" data-save-entity="1" aria-pressed="' + (saved ? 'true' : 'false') + '">' +
      (saved ? '✓ In my library' : 'Add to library') + '</button>';
  }

  function bindSavedButton(container, kind, id, name) {
    const button = container.querySelector('[data-save-entity]');
    if (!button) return;
    button.addEventListener('click', function () {
      const nowSaved = ResearchStore.toggleSaved(kind, id, name);
      button.classList.toggle('success', nowSaved);
      button.setAttribute('aria-pressed', nowSaved ? 'true' : 'false');
      button.textContent = nowSaved ? '✓ In my library' : 'Add to library';
    });
  }

  function conceptualModelView(model) {
    if (!model) {
      return emptyView('No conceptual model recorded',
        'The catalog has no pathway or antecedent/outcome record for this theory, so the page shows nothing rather than a generic diagram.');
    }
    if (model.kind === 'pathways') {
      return '<div class="br-model">' + (model.pathways || []).map(function (pathway) {
        return '<div class="br-model-column"><h4>' + esc(pathway.label || 'Pathway') + '</h4>' +
          flowChain(pathway.steps, 'No steps recorded') + '</div>';
      }).join('') + '</div>' +
      (model.note ? '<div class="br-notice br-small">' + esc(model.note) + '</div>' : '');
    }
    return '<div class="br-model br-model-3">' + (model.columns || []).map(function (column) {
      return '<div class="br-model-column"><h4>' + esc(column.label) + '</h4>' +
        listOrEmpty(column.items, function (item) {
          return item.id
            ? '<a class="br-chip-link" href="' + entityPath('constructs', item.id) + '">' + esc(refName(item)) + '</a>'
            : '<span class="br-chip-link is-plain">' + esc(refName(item)) + '</span>';
        }, 'No catalog relationship recorded', '', '<div class="br-chip-stack">', '</div>') + '</div>';
    }).join('') + '</div>' +
    (model.note ? '<div class="br-notice br-small">' + esc(model.note) + '</div>' : '');
  }

  function broadPaperSection(payload, kindLabel) {
    if (!payload || !payload.total) return '';
    return section('Papers under a broader tag',
      '<div class="br-notice">' + esc(payload.note) + ' Tag: ' +
      esc((payload.tags || []).join(', ')) + '.</div>' +
      '<div style="margin-top:12px">' + paperList(payload.papers, 'No papers', '') + '</div>',
      plural(payload.total, 'additional ' + kindLabel + ' paper'));
  }

  function renderTheoryDetail(slug) {
    setPageTitle('Theory');
    APP.innerHTML = pageShell({
      nav: 'theories', heading: false, crumb: 'Theories',
      body: loading('Loading theory'),
    });
    const content = APP.lastElementChild;
    getJSON('/api/abdc/research/theories/' + encodeURIComponent(slug)).then(function (data) {
      const theory = data.theory;
      setPageTitle(theory.name);
      content.innerHTML =
        '<div class="br-detail-head"><div>' +
        '<div class="br-card-meta">' + esc(theory.abbreviation || 'Theory') + ' · Origin ' +
        esc(plain(theory.origin_year, 'not loaded')) + '</div>' +
        '<h1>' + esc(theory.name) + '</h1>' + zhName(theory) +
        '<p class="br-lede">' + esc(theory.definition) + '</p>' + zhDefinition(theory) +
        '<div class="br-card-meta">' + esc((theory.discipline || []).join(' · ')) +
        (provenanceLabel(theory) ? ' · ' + esc(provenanceLabel(theory)) : '') + '</div>' +
        tagRow(theory.keywords) + '</div>' +
        '<div class="br-detail-actions">' + savedButton('theory', theory.id, theory.name) +
        '<button type="button" class="br-button" data-copy-summary="1">Copy summary</button></div></div>' +
        (theory.mapping_note ? '<div class="br-notice">' + esc(theory.mapping_note) + '</div>' : '') +
        section('Overview',
          '<div class="br-field-grid">' +
          '<div class="br-field"><div class="br-field-label">Core proposition</div><div class="br-field-value">' + esc(theory.definition) + '</div></div>' +
          '<div class="br-field"><div class="br-field-label">Key mechanisms</div><div class="br-field-value">' +
          esc((theory.mechanisms || []).join(' · ') || 'No mechanisms recorded') + '</div></div>' +
          '<div class="br-field"><div class="br-field-label">Antecedents</div><div class="br-field-value">' +
          esc(relationshipText(data.antecedents, 'No catalog relationship recorded')) + '</div></div>' +
          '<div class="br-field"><div class="br-field-label">Outcomes</div><div class="br-field-value">' +
          esc(relationshipText(data.outcomes, 'No catalog relationship recorded')) + '</div></div>' +
          '<div class="br-field"><div class="br-field-label">Moderators</div><div class="br-field-value">' +
          esc(relationshipText(data.moderators, 'No catalog relationship recorded')) + '</div></div>' +
          '<div class="br-field"><div class="br-field-label">Key scholars / source authors</div><div class="br-field-value">' +
          scholarSummary(data) + '</div></div>' +
          '</div>') +
        section('Conceptual model', conceptualModelView(data.conceptual_model), 'Catalog scaffold') +
        section('Core constructs',
          refCards(data.core_constructs, 'constructs', 'No constructs linked',
            'The catalog does not yet contain a verified construct relationship.'),
          'Catalog relationship') +
        section('Seminal works · 经典文献',
          seminalWorks(data.source_works || data.seminal_works, data.seminal_papers_note),
          'Verification status shown per row') +
        section('Recent A* applications',
          paperList(data.recent_applications, 'No classified applications found',
            'No paper in the cache carries a precise classifier tag for this theory.'),
          'Precise classification tags') +
        broadPaperSection(data.broad_tag_applications, 'theory') +
        section('Applications',
          tagRow(theory.applications, 'green') ||
          emptyView('No application contexts', 'No context labels are loaded.')) +
        (theory.source_note ? section('Catalog provenance',
          '<div class="br-notice info">' + esc(theory.source_note) + '</div>',
          theory.source_pack === 'management-organization-60' ? 'Attached book scan' : 'Curated scaffold') : '') +
        (theory.source_text ? section('Original chapter text · 原文章节文本',
          sourceTextView(theory.source_text), 'Local OCR reading layer') : '') +
        section('Known boundary conditions',
          listOrEmpty(theory.boundary_conditions, function (item) { return '<li>' + esc(item) + '</li>'; },
            'No boundary conditions loaded', 'Add a verified boundary condition to the catalog.',
            '<ul class="br-step-list">', '</ul>')) +
        section('Criticisms & debates',
          listOrEmpty(theory.criticisms, function (item) { return '<div class="br-warning">' + esc(item) + '</div>'; },
            'No criticisms loaded', 'A research tool should not present a theory as settled; add the debates.',
            '<div class="br-warning-list">', '</div>')) +
        section('Related theories',
          refCards(data.related_theories, 'theories', 'No related theories',
            'The catalog records no related theory for this entry.')) +
        dataBoundary(data);

      bindSavedButton(content, 'theory', theory.id, theory.name);
      const copyButton = content.querySelector('[data-copy-summary]');
      if (copyButton) copyButton.addEventListener('click', function () {
        copyText(theory.name + (theory.abbreviation ? ' (' + theory.abbreviation + ')' : '') +
          '\n\n' + theory.definition, copyButton);
      });
    }).catch(function (error) {
      content.innerHTML = errorView(error);
      bindRetry(content, function () { renderTheoryDetail(slug); });
    });
  }

  // ── construct detail ──────────────────────────────────────────────────────

  function renderConstructDetail(slug) {
    setPageTitle('Construct');
    APP.innerHTML = pageShell({
      nav: 'constructs', heading: false, crumb: 'Constructs',
      body: loading('Loading construct'),
    });
    const content = APP.lastElementChild;
    let sort = 'relevance_desc';

    function load() {
      content.innerHTML = loading('Loading construct');
      getJSON('/api/abdc/research/constructs/' + encodeURIComponent(slug) + '?sort=' + encodeURIComponent(sort))
        .then(function (data) {
          const construct = data.construct;
          const network = data.network || {};
          setPageTitle(construct.name);
          const scales = construct.measurement_scales || [];
          const scaleHtml = scales.length
            ? '<div class="br-matrix-wrap"><table class="br-matrix"><caption class="br-visually-hidden">Measurement scale metadata</caption>' +
              '<thead><tr><th scope="col">Scale name</th><th scope="col">Authors</th><th scope="col">Year</th>' +
              '<th scope="col">Items</th><th scope="col">Response scale</th><th scope="col">Source status</th></tr></thead><tbody>' +
              scales.map(function (scale) {
                return '<tr><th scope="row">' + esc(scale.name) + '</th><td>' + esc(text(scale.authors)) + '</td>' +
                  '<td>' + esc(plain(scale.year)) + '</td><td>' + esc(plain(scale.items)) + '</td>' +
                  '<td>' + esc(text(scale.response_scale)) + '</td><td>' + esc(text(scale.source_status)) + '</td></tr>';
              }).join('') + '</tbody></table></div>'
            : emptyView('No measurement metadata loaded',
                'Add a verified scale metadata record before using this construct in a manuscript.');

          const chain = [].concat(
            (network.antecedents || []).slice(0, 1),
            [{ id: construct.id, name: construct.name }],
            (network.outcomes || []).slice(0, 1));

          content.innerHTML =
            '<div class="br-detail-head"><div>' +
            '<div class="br-card-meta">Construct · ' + esc((construct.discipline || []).join(' · ')) + '</div>' +
            '<h1>' + esc(construct.name) + '</h1>' + zhName(construct) +
            '<p class="br-lede">' + esc(construct.definition) + '</p>' + zhDefinition(construct) +
            tagRow(construct.keywords) + '</div>' +
            '<div class="br-detail-actions">' + savedButton('construct', construct.id, construct.name) +
            '<span class="br-badge green">' + plural(construct.paper_count, 'observed paper') + '</span></div></div>' +
            section('Definition', '<div class="br-abstract">' + esc(construct.definition) + '</div>') +
            section('Origin & measurement sources · 定义与测量原始文献',
              seminalWorks(construct.source_works || construct.seminal_works,
                construct.source_coverage_note),
              'Theory–Construct–Method evidence') +
            section('Related theories',
              refCards(data.related_theories, 'theories', 'No related theories',
                'The catalog records no theory relationship for this construct.')) +
            section('Role in research',
              tagRow(construct.roles, 'blue') ||
              emptyView('Role not loaded', 'The catalog does not assign a fixed role.')) +
            section('Construct network',
              (chain.length > 1 ? flowChain(chain, '') : '') +
              '<div class="br-grid br-grid-4" style="margin-top:14px">' +
              [['Antecedents', network.antecedents], ['Mediators', network.mediators],
               ['Moderators', network.moderators], ['Outcomes', network.outcomes]].map(function (pair) {
                return '<div class="br-field"><div class="br-field-label">' + esc(pair[0]) + '</div>' +
                  listOrEmpty(pair[1], function (item) {
                    return item.id
                      ? '<a class="br-chip-link" href="' + entityPath('constructs', item.id) + '">' + esc(refName(item)) + '</a>'
                      : '<span class="br-chip-link is-plain">' + esc(refName(item)) + '</span>';
                  }, 'None recorded', '', '<div class="br-chip-stack">', '</div>') + '</div>';
              }).join('') + '</div>' +
              '<div class="br-notice info">' + esc(network.note || '') + '</div>',
              'Catalog scaffold') +
            section('Measurement scales', scaleHtml +
              '<div class="br-notice">Scale items are intentionally not copied into the system. Copyrighted instruments require source-level verification and appropriate permission; this page stores metadata only.</div>') +
            section('Papers using this construct',
              '<div class="br-toolbar" role="group" aria-label="Sort papers">' +
              [['relevance_desc', 'Most relevant'], ['date_desc', 'Recent'], ['citations_desc', 'Citation count']]
                .map(function (item) {
                  return '<button type="button" class="br-chip' + (sort === item[0] ? ' is-active' : '') +
                    '" data-sort="' + item[0] + '" aria-pressed="' + (sort === item[0] ? 'true' : 'false') + '">' +
                    esc(item[1]) + '</button>';
                }).join('') + '</div>' +
              paperList(data.papers, 'No keyword-linked papers found',
                'No title or abstract in the cache contains this construct’s keywords.'),
              'Keyword inference from current cache') +
            dataBoundary(data);

          bindSavedButton(content, 'construct', construct.id, construct.name);
          content.querySelectorAll('[data-sort]').forEach(function (button) {
            button.addEventListener('click', function () { sort = button.dataset.sort; load(); });
          });
        }).catch(function (error) {
          content.innerHTML = errorView(error);
          bindRetry(content, load);
        });
    }
    load();
  }

  // ── method detail ─────────────────────────────────────────────────────────

  function designDiagram(method) {
    const diagram = method.design_diagram;
    if (diagram && diagram.kind === 'did') {
      return '<div class="br-method-design"><div class="br-did">' +
        (diagram.series || []).map(function (series) {
          return '<div class="br-did-row"><span class="br-did-label">' + esc(series.label) + '</span>' +
            '<span class="br-did-line' + (series.emphasis ? ' is-treated' : '') + '" aria-hidden="true"></span></div>';
        }).join('') +
        '<div class="br-did-axis">' + (diagram.axis || []).map(function (item) {
          return '<span>' + esc(item) + '</span>';
        }).join('') + '</div></div>' +
        (diagram.note ? '<div class="br-card-meta" style="margin-top:12px">' + esc(diagram.note) + '</div>' : '') +
        '</div>';
    }
    return '<div class="br-method-design"><div class="br-design-track">' +
      '<div class="br-design-node">Research question</div>' +
      '<div class="br-design-node active">' + esc(method.name) + '</div>' +
      '<div class="br-design-node">Observed evidence</div></div>' +
      '<div class="br-card-meta" style="margin-top:12px">Design choices, estimand, timing, and unit of analysis should be documented before estimation.</div></div>';
  }

  function renderMethodDetail(slug) {
    setPageTitle('Method');
    APP.innerHTML = pageShell({
      nav: 'methods', heading: false, crumb: 'Methods',
      body: loading('Loading method'),
    });
    const content = APP.lastElementChild;
    getJSON('/api/abdc/research/methods/' + encodeURIComponent(slug)).then(function (data) {
      const method = data.method;
      setPageTitle(method.name);
      const codeExamples = method.code_examples || [];
      let codeLanguage = codeExamples.length ? codeExamples[0].language : '';

      function codeBlock() {
        if (!codeExamples.length) {
          return emptyView('No code example loaded',
            'This method is not primarily executed through statistical code, or a reviewed example has not been added to the catalog.');
        }
        const current = codeExamples.filter(function (item) { return item.language === codeLanguage; })[0] || codeExamples[0];
        return '<div class="br-code-tabs" role="tablist" aria-label="Code language">' +
          codeExamples.map(function (item) {
            const selected = item.language === codeLanguage;
            return '<button type="button" role="tab" class="br-chip' + (selected ? ' is-active' : '') +
              '" data-code-language="' + esc(item.language) + '" aria-selected="' + (selected ? 'true' : 'false') +
              '" id="br-code-tab-' + esc(item.language) + '" aria-controls="br-code-panel"' +
              (selected ? '' : ' tabindex="-1"') + '>' + esc(item.language) + '</button>';
          }).join('') + '</div>' +
          '<div class="br-code-wrap" id="br-code-panel" role="tabpanel" aria-labelledby="br-code-tab-' + esc(codeLanguage) + '">' +
          '<button type="button" class="br-button br-code-copy" data-copy-code="1">Copy</button>' +
          '<pre class="br-code"><code>' + esc(current ? current.code : '') + '</code></pre></div>' +
          '<div class="br-card-meta">Examples are original short scaffolds for reproducibility planning, not a substitute for method documentation.</div>';
      }

      function bulletSection(title, items, emptyTitle, emptyMessage, className) {
        return section(title, listOrEmpty(items, function (item) {
          return '<div class="br-field"><div class="br-field-value">' + esc(item) + '</div></div>';
        }, emptyTitle, emptyMessage, '<div class="br-grid br-grid-2 ' + (className || '') + '">', '</div>'));
      }

      content.innerHTML =
        '<div class="br-detail-head"><div>' +
        '<div class="br-card-meta">' + esc(method.category || 'method') + ' · ' +
        esc(method.sub_category || '') + ' · ' + esc(method.difficulty || '') + '</div>' +
        '<h1>' + esc(method.name) + '</h1>' + zhName(method) +
        '<p class="br-lede">' + esc(method.description) + '</p>' + zhDefinition(method) + '</div>' +
        '<div class="br-detail-actions">' + savedButton('method', method.id, method.name) +
        '<span class="br-badge purple">' + plural(method.paper_count, 'linked paper') + '</span></div></div>' +
        (method.mapping_note ? '<div class="br-notice">' + esc(method.mapping_note) + '</div>' : '') +
        section('What it is', '<div class="br-abstract">' + esc(method.description) + '</div>') +
        section('When to use', listOrEmpty(method.use_when, function (item) {
          return '<li>' + esc(item) + '</li>';
        }, 'No use cases loaded', 'Add the conditions under which this method applies.',
           '<ul class="br-check-list">', '</ul>')) +
        section('Research design', designDiagram(method)) +
        bulletSection('Key assumptions', method.assumptions, 'No assumptions loaded',
          'A method page without its assumptions is not usable for design decisions.') +
        section('Workflow', listOrEmpty(method.workflow, function (item) {
          return '<li>' + esc(item) + '</li>';
        }, 'No workflow loaded', 'Add the ordered steps for this method.', '<ol class="br-step-list">', '</ol>')) +
        bulletSection('Diagnostics', method.diagnostics, 'No diagnostics loaded',
          'Add the checks a reviewer would expect to see.') +
        section('Common mistakes', listOrEmpty(method.pitfalls, function (item) {
          return '<div class="br-warning">' + esc(item) + '</div>';
        }, 'No pitfalls loaded', 'Add the recurring errors for this method.',
           '<div class="br-warning-list">', '</div>')) +
        section('Code examples', codeBlock()) +
        section('Foundational method sources · 方法原始文献',
          seminalWorks(method.source_works || method.seminal_works,
            method.source_coverage_note),
          'Theory–Construct–Method evidence') +
        section('Example papers', paperList(data.example_papers, 'No method-tagged papers found',
          'No paper in the cache carries a precise classifier tag for this method.'),
          'Precise classification tags') +
        broadPaperSection(data.broad_tag_papers, 'method') +
        section('Related methods', refCards(data.related_methods, 'methods', 'No related methods',
          'The catalog records no related method for this entry.')) +
        dataBoundary(data);

      bindSavedButton(content, 'method', method.id, method.name);

      const codeSection = content.querySelector('#br-code-panel') &&
        content.querySelector('#br-code-panel').closest('.br-section-body');

      function bindCode() {
        if (!codeSection) return;
        codeSection.querySelectorAll('[data-code-language]').forEach(function (button) {
          button.addEventListener('click', function () {
            codeLanguage = button.dataset.codeLanguage;
            codeSection.innerHTML = codeBlock();
            bindCode();
            const active = codeSection.querySelector('[aria-selected="true"]');
            if (active) active.focus();
          });
        });
        const copyButton = codeSection.querySelector('[data-copy-code]');
        if (copyButton) copyButton.addEventListener('click', function () {
          const current = codeExamples.filter(function (item) { return item.language === codeLanguage; })[0] || codeExamples[0];
          copyText(current ? current.code : '', copyButton);
        });
      }
      bindCode();
    }).catch(function (error) {
      content.innerHTML = errorView(error);
      bindRetry(content, function () { renderMethodDetail(slug); });
    });
  }

  // ── paper workspace ───────────────────────────────────────────────────────

  function citationText(paper, format) {
    const authors = (paper.authors || []).join(', ') || '[Author metadata unavailable]';
    const year = paper.year || 'n.d.';
    const journal = paper.journal && paper.journal.title ? paper.journal.title : '[Journal metadata unavailable]';
    if (format === 'bibtex') {
      const first = (paper.authors || [])[0] || 'paper';
      const key = String(first).replace(/[^a-z0-9]/gi, '').toLowerCase() + year + String(paper.id);
      return '@article{' + key + ',\n  title = {' + (paper.title || '') + '},\n  author = {' + authors +
        '},\n  journal = {' + journal + '},\n  year = {' + year + '}' +
        (paper.doi ? ',\n  doi = {' + paper.doi + '}' : '') + '\n}';
    }
    return authors + ' (' + year + '). ' + text(paper.title, '[Title unavailable]') + '. ' + journal +
      (paper.doi ? '. https://doi.org/' + paper.doi : '.');
  }

  function renderPaperDetail(id) {
    setPageTitle('Paper');
    APP.innerHTML = pageShell({
      nav: 'library', heading: false, crumb: 'Paper',
      body: loading('Loading paper'),
    });
    const content = APP.lastElementChild;
    ResearchStore.workspace(id).then(function (data) {
      const paper = data.paper;
      setPageTitle(paper.title || 'Paper');
      ResearchStore.pushRecent(id, paper.title);
      const state = data.library_state || {};
      let activeTab = 'overview';
      let currentState = {
        reading_status: state.reading_status || paper.status || 'unread',
        favorite: Boolean(state.favorite || paper.favorite),
      };
      let editingNoteId = null;
      let statusMessage = data.local_state_pending
        ? 'Reading status could not be saved to the server and is held on this device.' : '';

      function header() {
        const journal = paper.journal || {};
        return '<div class="br-paper-header">' +
          '<div class="br-card-meta">Paper ' + esc(paper.id) + ' · ' +
          esc(text(paper.dataStatus, 'metadata status unavailable')) + '</div>' +
          '<h1>' + esc(text(paper.title, 'Title unavailable')) + '</h1>' +
          '<div class="br-paper-authors">' +
          esc((paper.authors || []).join(' · ') || 'Author metadata unavailable') + ' · ' +
          esc(plain(paper.year, 'Year unavailable')) + '</div>' +
          '<div class="br-paper-meta"><span>' + esc(text(journal.title, 'Journal unavailable')) + '</span>' +
          (paper.abdcRank ? '<span class="br-badge amber">ABDC ' + esc(paper.abdcRank) + '</span>' : '') +
          (paper.doi ? '<span>DOI ' + esc(paper.doi) + '</span>' : '<span>DOI unavailable</span>') +
          (paper.citedByCount != null ? '<span>Citations ' + num(paper.citedByCount) + '</span>' : '') + '</div>' +
          '<div class="br-paper-actions">' +
          '<label class="br-visually-hidden" for="br-reading-status">Reading status</label>' +
          '<select class="br-select" id="br-reading-status">' +
          READING_STATUSES.map(function (status) {
            return '<option value="' + status + '"' +
              (status === currentState.reading_status ? ' selected' : '') + '>' + status + '</option>';
          }).join('') + '</select>' +
          '<button type="button" class="br-button' + (currentState.favorite ? ' success' : '') +
          '" id="br-favorite" aria-pressed="' + (currentState.favorite ? 'true' : 'false') + '">' +
          (currentState.favorite ? '★ Favorite' : '☆ Favorite') + '</button>' +
          (paper.doiUrl ? '<a class="br-button" href="' + esc(paper.doiUrl) +
            '" target="_blank" rel="noopener noreferrer">Open DOI ↗</a>' : '') +
          '<button type="button" class="br-button" id="br-copy-apa">Copy APA</button>' +
          '<button type="button" class="br-button" id="br-copy-bibtex">BibTeX</button>' +
          '<button type="button" class="br-button" id="br-copy-plain">Plain text</button></div>' +
          (statusMessage ? '<div class="br-notice br-small" role="status">' + esc(statusMessage) + '</div>' : '') +
          '<div class="br-paper-tabs" role="tablist" aria-label="Paper sections">' +
          PAPER_TABS.map(function (tab) {
            const selected = activeTab === tab;
            return '<button type="button" role="tab" class="br-paper-tab' + (selected ? ' is-active' : '') +
              '" data-paper-tab="' + tab + '" id="br-tab-' + tab + '" aria-controls="br-tabpanel"' +
              ' aria-selected="' + (selected ? 'true' : 'false') + '"' + (selected ? '' : ' tabindex="-1"') + '>' +
              tab.charAt(0).toUpperCase() + tab.slice(1) + '</button>';
          }).join('') + '</div></div>';
      }

      function sidebar() {
        const journal = paper.journal || {};
        const cls = paper.classification || {};
        function chipList(refs, kind, emptyLabel) {
          return listOrEmpty(refs, function (ref) {
            return '<a class="br-chip-link" href="' + entityPath(kind, ref.id) + '">' + esc(ref.name) + '</a>';
          }, emptyLabel, '', '<div class="br-chip-stack">', '</div>');
        }
        return '<aside class="br-sidebar" aria-label="Paper facts">' +
          '<div class="br-card"><h3>At a glance</h3>' +
          '<dl class="br-facts">' +
          '<dt>Journal</dt><dd>' + esc(text(journal.title, 'unavailable')) + '</dd>' +
          '<dt>ABDC rank</dt><dd>' + esc(text(paper.abdcRank, 'unavailable')) + '</dd>' +
          '<dt>Year</dt><dd>' + esc(plain(paper.year, 'unavailable')) + '</dd>' +
          '<dt>Citations</dt><dd>' + num(paper.citedByCount) + '</dd>' +
          '<dt>Discipline</dt><dd>' + esc((paper.disciplines || []).join(', ') || 'unclassified') + '</dd>' +
          '<dt>Source records</dt><dd>' + num((data.source_records || []).length) + '</dd>' +
          '<dt>Notes</dt><dd>' + num((data.notes || []).length) + '</dd>' +
          '</dl></div>' +
          '<div class="br-card"><h3>Theories</h3>' + chipList(paper.theories, 'theories', 'No mapped theory') + '</div>' +
          '<div class="br-card"><h3>Constructs</h3>' + chipList(paper.constructs, 'constructs', 'No inferred construct') + '</div>' +
          '<div class="br-card"><h3>Methods</h3>' + chipList(paper.methods, 'methods', 'No mapped method') + '</div>' +
          '<div class="br-card"><h3>Classifier topics</h3>' +
          (tagRow(cls.research_topic) || '<div class="br-card-meta">No topic labels</div>') + '</div>' +
          '</aside>';
      }

      function overviewTab() {
        return section('Abstract', paper.abstract
          ? '<div class="br-abstract">' + esc(paper.abstract) + '</div>'
          : '<div class="br-notice">Abstract is missing from the current verified metadata sources. This is not evidence that the publisher has no abstract.</div>') +
          section('Study metadata',
            '<div class="br-field-grid">' +
            '<div class="br-field"><div class="br-field-label">Research question</div><div class="br-field-value">' +
            esc(text(paper.researchQuestion, 'Not structured in current cache')) + '</div></div>' +
            '<div class="br-field"><div class="br-field-label">Sample</div><div class="br-field-value">' +
            esc(text(paper.sample, 'Not structured in current cache')) + '</div></div>' +
            '<div class="br-field"><div class="br-field-label">Country / context</div><div class="br-field-value">' +
            esc(text(paper.country, 'Not structured in current cache')) + '</div></div>' +
            '<div class="br-field"><div class="br-field-label">Abstract status</div><div class="br-field-value">' +
            esc(text(paper.abstractStatus, 'unknown')) + ' · ' +
            esc(text(paper.abstractReviewStatus, 'review status unavailable')) + '</div></div></div>') +
          section('Evidence and provenance',
            '<div class="br-notice info">' + esc(data.workspace_note) + '</div>' +
            '<div style="margin-top:10px">' +
            listOrEmpty(data.source_records, function (source) {
              return '<div class="br-list-item"><strong>' + esc(text(source.source_name, 'Source record')) + '</strong>' +
                '<span>' + esc(text(source.source_type, 'source type')) + ' · ' +
                esc(text(source.fetched_at, 'time unavailable')) +
                (source.source_url ? ' · <a href="' + esc(source.source_url) +
                  '" target="_blank" rel="noopener noreferrer">source ↗</a>' : '') + '</span></div>';
            }, 'No source records', 'The cache has no provenance rows for this paper.',
               '<div class="br-list">', '</div>') + '</div>');
      }

      function refTab(refs, kind, title, rawTags, emptyTitle, emptyMessage) {
        return section(title,
          refCards(refs, kind, emptyTitle, emptyMessage) +
          (rawTags !== null
            ? '<div class="br-notice" style="margin-top:12px">Raw classifier tags: ' +
              esc((rawTags || []).join(', ') || 'none') + '</div>'
            : ''),
          kind === 'constructs' ? 'Inferred links are not manual coding' : 'Existing classification tags');
      }

      function notesTab() {
        const notes = data.notes || [];
        const editing = editingNoteId
          ? notes.filter(function (n) { return String(n.id) === String(editingNoteId); })[0]
          : null;
        return section(editing ? 'Edit note' : 'My Notes',
          '<div class="br-note-form">' +
          '<label class="br-visually-hidden" for="br-note-text">Research note</label>' +
          '<textarea id="br-note-text" class="br-textarea" placeholder="Write a research note…">' +
          esc(editing ? editing.note_text : '') + '</textarea>' +
          '<fieldset class="br-note-tags"><legend class="br-visually-hidden">Note tags</legend>' +
          NOTE_TAGS.map(function (tag) {
            const on = editing && (editing.tags || []).indexOf(tag) >= 0;
            return '<label><input type="checkbox" value="' + esc(tag) + '"' + (on ? ' checked' : '') + '> ' +
              esc(tag) + '</label>';
          }).join('') + '</fieldset>' +
          '<button type="button" class="br-button primary" id="br-save-note">' +
          (editing ? 'Update note' : 'Save note') + '</button>' +
          (editing ? '<button type="button" class="br-button" id="br-cancel-note">Cancel</button>' : '') +
          '<span class="br-toolbar-note" id="br-note-status" role="status"></span></div>' +
          '<div style="margin-top:14px">' +
          listOrEmpty(notes, function (note) {
            return '<div class="br-note"><div class="br-note-body">' + esc(note.note_text) + '</div>' +
              '<div class="br-note-meta">' + esc((note.tags || []).join(' · ') || 'Untagged') + ' · ' +
              esc(text(note.updated_at, '')) + (note.local_only ? ' · saved on this device only' : '') +
              '<span class="br-note-actions">' +
              '<button type="button" class="br-chip" data-edit-note="' + esc(note.id) + '">Edit</button>' +
              '<button type="button" class="br-chip" data-delete-note="' + esc(note.id) + '">Delete</button>' +
              '</span></div></div>';
          }, 'No notes yet',
             'Save a theory, method, citation, idea, limitation, or future-research note.', '', '') +
          '</div>');
      }

      function tabContent() {
        const cls = paper.classification || {};
        if (activeTab === 'overview') return overviewTab();
        if (activeTab === 'theory') {
          return refTab(paper.theories, 'theories', 'Theories', cls.theory_tags,
            'No mapped theory tag',
            'The current A* classification did not map this paper to a catalog theory. Do not infer a theory from the title alone.');
        }
        if (activeTab === 'constructs') {
          return refTab(paper.constructs, 'constructs', 'Constructs', null,
            'No inferred constructs',
            'No catalog construct keyword was detected in the available title or abstract.');
        }
        if (activeTab === 'method') {
          return refTab(paper.methods, 'methods', 'Methods', cls.method_tags,
            'No mapped method tag',
            'The current A* classification did not map this paper to a catalog method.');
        }
        if (activeTab === 'findings') {
          return section('Findings', emptyView('Structured findings are not available',
            'The current A* metadata cache contains title, abstract, source, and classifier fields, but no verified finding-by-finding extraction. The workspace leaves this blank rather than inventing results.')) +
            section('Limitations', emptyView('No structured limitations loaded',
              'Add a verified paper reading note below when you inspect the paper.')) +
            section('Future research', emptyView('No structured future research loaded',
              'Add a tagged note when the paper provides a traceable opportunity.'));
        }
        return notesTab();
      }

      function persist(patch) {
        Object.assign(currentState, patch);
        return ResearchStore.setState(id, currentState).then(function (result) {
          statusMessage = result.local_only
            ? 'Saved on this device only — the server rejected the write.' : '';
          render();
        });
      }

      function render() {
        content.innerHTML = header() +
          '<div class="br-two-column">' +
          '<div class="br-paper-panel" id="br-tabpanel" role="tabpanel" aria-labelledby="br-tab-' + activeTab + '" tabindex="0">' +
          tabContent() + '</div>' + sidebar() + '</div>' + dataBoundary(data);

        const tabs = Array.prototype.slice.call(content.querySelectorAll('[data-paper-tab]'));
        tabs.forEach(function (button, index) {
          button.addEventListener('click', function () { activeTab = button.dataset.paperTab; render(); });
          button.addEventListener('keydown', function (event) {
            let next = null;
            if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
            else if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
            else if (event.key === 'Home') next = tabs[0];
            else if (event.key === 'End') next = tabs[tabs.length - 1];
            if (!next) return;
            event.preventDefault();
            activeTab = next.dataset.paperTab;
            render();
            const focusTarget = content.querySelector('[data-paper-tab="' + activeTab + '"]');
            if (focusTarget) focusTarget.focus();
          });
        });

        const status = content.querySelector('#br-reading-status');
        if (status) status.addEventListener('change', function () {
          persist({ reading_status: status.value });
        });
        const favorite = content.querySelector('#br-favorite');
        if (favorite) favorite.addEventListener('click', function () {
          persist({ favorite: !currentState.favorite });
        });
        const copies = [['#br-copy-apa', 'apa'], ['#br-copy-bibtex', 'bibtex'], ['#br-copy-plain', 'plain']];
        copies.forEach(function (pair) {
          const button = content.querySelector(pair[0]);
          if (button) button.addEventListener('click', function () {
            copyText(citationText(paper, pair[1]), button);
          });
        });

        const saveNote = content.querySelector('#br-save-note');
        if (saveNote) saveNote.addEventListener('click', function () {
          const textarea = content.querySelector('#br-note-text');
          const tags = Array.prototype.map.call(
            content.querySelectorAll('.br-note-tags input:checked'), function (input) { return input.value; });
          const statusEl = content.querySelector('#br-note-status');
          if (!textarea || !textarea.value.trim()) {
            if (statusEl) statusEl.textContent = 'Write a note first.';
            return;
          }
          saveNote.disabled = true;
          const payload = { note_text: textarea.value.trim(), tags: tags };
          if (editingNoteId) payload.note_id = editingNoteId;
          ResearchStore.saveNote(id, payload).then(function (saved) {
            const rest = (data.notes || []).filter(function (n) { return String(n.id) !== String(saved.note.id); });
            data.notes = [saved.note].concat(rest);
            editingNoteId = null;
            activeTab = 'notes';
            render();
          }).catch(function (error) {
            if (statusEl) statusEl.textContent = error.message;
            saveNote.disabled = false;
          });
        });
        const cancelNote = content.querySelector('#br-cancel-note');
        if (cancelNote) cancelNote.addEventListener('click', function () {
          editingNoteId = null; render();
        });
        content.querySelectorAll('[data-edit-note]').forEach(function (button) {
          button.addEventListener('click', function () {
            editingNoteId = button.dataset.editNote; activeTab = 'notes'; render();
          });
        });
        content.querySelectorAll('[data-delete-note]').forEach(function (button) {
          button.addEventListener('click', function () {
            const noteId = button.dataset.deleteNote;
            const close = openModal('Delete this note?', 'This cannot be undone.',
              '<p class="br-card-meta">The note will be removed from your research library.</p>',
              '<button type="button" class="br-button danger" data-confirm-delete="1">Delete note</button>');
            document.querySelector('[data-confirm-delete]').addEventListener('click', function () {
              ResearchStore.deleteNote(id, noteId).then(function () {
                data.notes = (data.notes || []).filter(function (n) { return String(n.id) !== String(noteId); });
                close();
                render();
              }).catch(function (error) {
                close();
                statusMessage = 'Could not delete the note: ' + error.message;
                render();
              });
            });
          });
        });
      }
      render();
    }).catch(function (error) {
      content.innerHTML = errorView(error);
      bindRetry(content, function () { renderPaperDetail(id); });
    });
  }

  // ── library ───────────────────────────────────────────────────────────────

  function renderLibrary() {
    setPageTitle('My Papers');
    APP.innerHTML = pageShell({
      title: 'My Papers',
      subtitle: 'Your research shelf: reading status, favorites, notes, recently opened papers, and saved catalog entries.',
      nav: 'library',
      body: loading('Loading library'),
    });
    const content = APP.lastElementChild;
    const localRecents = ResearchStore.recents();
    const params = localRecents.length
      ? '?recent=' + encodeURIComponent(localRecents.slice(0, 12).map(function (r) { return r.id; }).join(','))
      : '';
    getJSON('/api/abdc/research/library' + params).then(function (data) {
      const papers = data.papers || [];
      const recent = data.recent_papers || [];
      const saved = ResearchStore.savedEntities();
      content.innerHTML =
        '<div class="br-notice info">Reading status, favorites, and notes are stored in the separate Business Research state database. If that database is read-only, this browser keeps them locally and the paper page says so.</div>' +
        section('Saved papers',
          paperList(papers, 'Your research workspace is empty',
            'Open a paper from Research Radar, Theory Library, or Literature Landscape, then mark it Reading, Read, or Favorite.'),
          plural(papers.length, 'paper')) +
        section('Recently opened',
          paperList(recent, 'No recently opened papers',
            'Papers you open from anywhere in the workspace appear here.'),
          plural(recent.length, 'paper')) +
        section('Saved theories, constructs, and methods',
          listOrEmpty(saved, function (item) {
            const kindPath = item.kind === 'theory' ? 'theories'
              : item.kind === 'construct' ? 'constructs' : 'methods';
            return '<a class="br-card is-clickable" href="' + entityPath(kindPath, item.id) + '">' +
              '<h3>' + esc(item.name) + '</h3>' +
              '<div class="br-card-meta">' + esc(item.kind) + '</div></a>';
          }, 'Nothing saved yet',
             'Use "Add to library" on a theory, construct, or method page.',
             '<div class="br-grid br-grid-3">', '</div>'),
          plural(saved.length, 'entry', 'entries')) +
        dataBoundary(data);
    }).catch(function (error) {
      content.innerHTML = errorView(error);
      bindRetry(content, renderLibrary);
    });
  }

  // ── landscape ─────────────────────────────────────────────────────────────

  function barRows(items, showShare) {
    const list = items || [];
    if (!list.length) return emptyView('No distribution data', 'No classified records matched this query.');
    const max = Math.max.apply(null, list.map(function (item) { return item.count || 0; }).concat([1]));
    return '<div class="br-bar-list">' + list.map(function (item) {
      const width = Math.max(1, (item.count / max) * 100);
      return '<div class="br-bar-row"><span>' + esc(item.label) + '</span>' +
        '<div class="br-bar-track"><div class="br-bar-fill" style="width:' + width + '%"></div></div>' +
        '<span class="br-bar-value">' + num(item.count) +
        (showShare && item.share != null ? ' <small>' + esc(pct(item.share)) + '</small>' : '') +
        '</span></div>';
    }).join('') + '</div>';
  }

  function networkView(network) {
    const nodes = (network && network.nodes) || [];
    const links = (network && network.links) || [];
    if (!nodes.length) {
      return emptyView('No construct signal', 'No catalog construct keyword appeared in this corpus.');
    }
    const nodeHtml = '<div class="br-net-nodes">' + nodes.slice(0, 10).map(function (node) {
      return '<a class="br-flow-node" href="' + entityPath('constructs', node.id) + '">' + esc(node.label) +
        '<small>' + plural(node.count, 'paper') + '</small></a>';
    }).join('') + '</div>';
    const linkHtml = links.length
      ? '<ul class="br-net-links">' + links.map(function (link) {
          return '<li><span class="br-net-pair">' + esc(link.source_label) +
            ' <span aria-hidden="true">↔</span> ' + esc(link.target_label) + '</span>' +
            '<span class="br-net-bar" aria-hidden="true"><i style="width:' +
            Math.max(3, (link.strength || 0) * 100) + '%"></i></span>' +
            '<span class="br-net-count">' + plural(link.count, 'co-occurrence') + '</span></li>';
        }).join('') + '</ul>'
      : '<div class="br-card-meta">No construct pair co-occurred in more than one paper.</div>';
    return nodeHtml + '<h4 class="br-subheading">Strongest co-occurrences</h4>' + linkHtml;
  }

  function matrixView(matrix) {
    const rows = (matrix && matrix.rows) || [];
    const columns = (matrix && matrix.columns) || [];
    if (!rows.length || !columns.length) {
      return emptyView('Matrix unavailable',
        'The query did not produce enough mapped theories and outcome constructs to cross-tabulate.');
    }
    return '<div class="br-matrix-wrap"><table class="br-matrix">' +
      '<caption class="br-visually-hidden">Papers by theory and outcome construct</caption><thead><tr>' +
      '<th scope="col">Theory × Outcome</th>' +
      columns.map(function (column) { return '<th scope="col">' + esc(column.label) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows.map(function (row) {
        return '<tr><th scope="row">' + esc(row.label) + '</th>' + row.cells.map(function (cell) {
          return '<td><button type="button" data-matrix-cell="' + esc(cell.id) + '" aria-label="' +
            esc(cell.label + ': ' + plural(cell.count, 'paper')) + '">' + num(cell.count) + '</button></td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>';
  }

  function underexploredView(data) {
    if (data.underexplored_suppressed) {
      return '<div class="br-notice" role="note">' + esc(data.underexplored_suppressed) + '</div>';
    }
    return listOrEmpty(data.underexplored_combinations, function (item) {
      return '<div class="br-opportunity"><strong>' + esc(item.label) + ' · ' +
        plural(item.count, 'paper') + '</strong><span>' + esc(item.interpretation) + '</span></div>';
    }, 'No low-count cells', 'The current matrix did not identify a relatively low-count combination.',
       '<div class="br-underexplored">', '</div>');
  }

  function renderLandscapeData(data) {
    if (data.requires_topic) return emptyView('Enter a research topic', data.message);
    const overview = data.overview || {};
    const emerging = data.emerging_topics || [];
    const kpis = [['Papers matched', num(overview.papers)], ['Analyzed', num(overview.analyzed_papers)],
                  ['A*', num(overview.a_star)], ['A', num(overview.a)],
                  ['From', plain(overview.from_year)], ['To', plain(overview.to_year)]];
    return '<div class="br-kpis">' + kpis.map(function (item) {
      return '<div class="br-kpi"><div class="br-kpi-value">' + item[1] + '</div>' +
        '<div class="br-kpi-label">' + esc(item[0]) + '</div></div>';
    }).join('') + '</div>' +
      '<div class="br-notice info"><b>' + esc(data.topic) + '</b> · ' + esc(data.selection_notes || '') +
      (data.relaxed_to_any_term ? ' No paper matched every term, so the query was widened to papers matching any term.' : '') +
      (overview.sampled ? ' The matched corpus is larger than the ' + num(overview.sample_limit) +
        '-paper analysis sample, so distributions describe the most recent slice.' : '') + '</div>' +
      '<div class="br-landscape-grid" style="margin-top:16px">' +
      '<div class="br-card"><h3>Research themes</h3><p class="br-card-meta">Observed classifier topics</p>' +
      barRows(data.themes, true) + '</div>' +
      '<div class="br-card"><h3>Theory distribution</h3><p class="br-card-meta">Precise classifier tags only</p>' +
      barRows(data.theories, true) + '</div>' +
      '<div class="br-card"><h3>Method distribution</h3><p class="br-card-meta">A paper may carry more than one method tag</p>' +
      barRows(data.methods, true) + '</div>' +
      '<div class="br-card"><h3>Construct distribution</h3><p class="br-card-meta">Title / abstract keyword inference</p>' +
      barRows(data.constructs, true) + '</div>' +
      '<div class="br-card wide"><h3>Construct network</h3>' +
      '<p class="br-card-meta">Co-occurrence among inferred constructs; a descriptive network, not a causal model.</p>' +
      networkView(data.construct_network) + '</div>' +
      '<div class="br-card wide"><h3>Theory × Outcome matrix</h3>' +
      '<p class="br-card-meta">Select a cell to inspect the observed papers in that combination.</p>' +
      matrixView(data.matrix) + '</div>' +
      '<div class="br-card"><h3>Underexplored Combinations</h3>' +
      '<p class="br-card-meta">' + esc(data.underexplored_disclaimer || '') + '</p>' +
      underexploredView(data) + '</div>' +
      '<div class="br-card"><h3>Emerging topics</h3>' +
      '<p class="br-card-meta">Recent count comparison, not an automatic trend claim.</p>' +
      listOrEmpty(emerging, function (item) {
        const trend = TREND[item.direction] || TREND.flat;
        return '<div class="br-trend"><span class="br-trend-arrow" aria-hidden="true">' + trend.glyph + '</span>' +
          '<span style="flex:1">' + esc(item.label) + ' <em class="br-trend-word">' + esc(trend.label) + '</em>' +
          '<small>' + num(item.recent_count) + ' recent · ' + num(item.prior_count) + ' prior · ' +
          esc(item.basis) + '</small></span></div>';
      }, 'No emerging-topic signal',
         'A topic needs at least three recent papers and a comparable prior period.', '', '') + '</div>' +
      '</div>' +
      section('Representative papers',
        paperList(data.representative_papers, 'No representative papers found',
          'No paper in this corpus carried enough metadata to rank.'),
        'Selected by relevance, citations, and recency') +
      dataBoundary(data);
  }

  function renderLandscape() {
    setPageTitle('Literature Landscape');
    APP.innerHTML = pageShell({
      title: 'Literature Landscape',
      subtitle: '探索一个研究主题中的理论、方法、构念和研究机会。',
      nav: 'landscape',
      body: '<div id="br-landscape-page"></div>',
    });
    const page = document.getElementById('br-landscape-page');
    const params = new URLSearchParams(window.location.search);
    let lastData = null;
    const thisYear = new Date().getFullYear();

    page.innerHTML =
      '<form class="br-toolbar" id="br-landscape-form">' +
      '<label class="br-visually-hidden" for="br-landscape-topic">Research topic</label>' +
      '<input id="br-landscape-topic" required type="search" placeholder="e.g. algorithmic management employee voice" value="' +
      esc(params.get('topic') || '') + '">' +
      '<label class="br-visually-hidden" for="br-landscape-from">From year</label>' +
      '<input id="br-landscape-from" type="number" min="1900" max="2100" placeholder="From year" value="' +
      esc(params.get('from_year') || String(thisYear - 6)) + '">' +
      '<label class="br-visually-hidden" for="br-landscape-to">To year</label>' +
      '<input id="br-landscape-to" type="number" min="1900" max="2100" placeholder="To year" value="' +
      esc(params.get('to_year') || String(thisYear)) + '">' +
      '<label class="br-visually-hidden" for="br-landscape-rank">Journal rank</label>' +
      '<select id="br-landscape-rank" class="br-select"><option value="A*,A">A* + A</option>' +
      '<option value="A*">A* only</option><option value="A">A only</option></select>' +
      '<label class="br-visually-hidden" for="br-landscape-discipline">Discipline</label>' +
      '<select id="br-landscape-discipline" class="br-select"><option value="">All disciplines</option>' +
      ['Information Systems', 'Management / Strategy', 'Marketing', 'OB / HR', 'Computational Social Science']
        .map(function (item) { return '<option value="' + esc(item) + '">' + esc(item) + '</option>'; }).join('') +
      '</select>' +
      '<button type="submit" class="br-button primary">Build Landscape</button></form>' +
      '<div id="br-landscape-output">' +
      emptyView('Enter a research topic',
        'The result is descriptive: it shows where the available cache is concentrated and which combinations are relatively less represented. These patterns do not by themselves establish a theoretical research gap.') +
      '</div>';

    const rankInput = document.getElementById('br-landscape-rank');
    if (params.get('rank')) rankInput.value = params.get('rank');
    const disciplineInput = document.getElementById('br-landscape-discipline');
    if (params.get('discipline')) disciplineInput.value = params.get('discipline');

    function load(query) {
      const output = document.getElementById('br-landscape-output');
      output.innerHTML = loading('Building landscape');
      getJSON('/api/abdc/research/landscape?' + query.toString()).then(function (data) {
        lastData = data;
        output.innerHTML = renderLandscapeData(data);
        output.querySelectorAll('[data-matrix-cell]').forEach(function (button) {
          button.addEventListener('click', function () {
            let cell = null;
            (lastData.matrix.rows || []).forEach(function (row) {
              row.cells.forEach(function (item) {
                if (item.id === button.dataset.matrixCell) cell = item;
              });
            });
            if (!cell) return;
            openModal(cell.label, plural(cell.count, 'observed paper') + ' in the current query',
              paperList(cell.papers, 'No paper records in this cell',
                'No paper in this corpus carries both tags.') +
              '<div class="br-notice" style="margin-top:14px">This cell is a descriptive co-occurrence count from the available cache. It is not evidence of a causal relationship or a formal research gap.</div>');
          });
        });
      }).catch(function (error) {
        output.innerHTML = errorView(error);
        bindRetry(output, function () { load(query); });
      });
    }

    document.getElementById('br-landscape-form').addEventListener('submit', function (event) {
      event.preventDefault();
      const topic = document.getElementById('br-landscape-topic').value.trim();
      if (!topic) return;
      const query = new URLSearchParams({
        topic: topic,
        from_year: document.getElementById('br-landscape-from').value,
        to_year: document.getElementById('br-landscape-to').value,
        rank: rankInput.value,
        discipline: disciplineInput.value,
      });
      history.replaceState(null, '', window.location.pathname + '?' + query.toString());
      load(query);
    });

    if (params.get('topic')) load(params);
  }

  // ── router ────────────────────────────────────────────────────────────────

  function render() {
    const route = currentRoute();
    if (route.kind === 'theories') return renderCatalogList('theories');
    if (route.kind === 'constructs') return renderCatalogList('constructs');
    if (route.kind === 'methods') return renderCatalogList('methods');
    if (route.kind === 'theory') return renderTheoryDetail(route.slug);
    if (route.kind === 'construct') return renderConstructDetail(route.slug);
    if (route.kind === 'method') return renderMethodDetail(route.slug);
    if (route.kind === 'paper') return renderPaperDetail(route.id);
    if (route.kind === 'landscape') return renderLandscape();
    if (route.kind === 'library') return renderLibrary();
    return renderOverview();
  }

  if (APP) render();
})();
