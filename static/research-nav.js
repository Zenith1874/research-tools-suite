(function () {
  'use strict';

  const groups = {
    china: {
      label: '中国宏观',
      summary: '总览 · 财政债务 · 利率汇率 · 房地产',
      defaultHref: '/dashboard',
      items: [
        { label: '宏观总览', href: '/dashboard', description: '央行金融统计、货币与信用核心指标。' },
        { label: '财政收支与债务', href: '/fiscal-debt', description: '年度财政收支、未来情景、政府债务与央行相关工具。' },
        { label: '利率与汇率', href: '/china-rates', description: 'LPR、SHIBOR 与人民币中间价。' },
        { label: '房地产', href: '/housing', description: '70 城官方指数、BIS 与挂牌价双口径。' }
      ]
    },
    us: {
      label: '美国宏观',
      summary: '美国宏观总览',
      defaultHref: '/us-macro',
      items: [
        { label: '美国宏观总览', href: '/us-macro', description: '失业率、JOLTS、联邦基金利率与 10Y 美债。' }
      ]
    },
    research: {
      label: 'ABDC 商科研究',
      summary: '期刊列表 · A* 研究雷达',
      defaultHref: '/abdc-astar-research',
      items: [
        { label: 'ABDC 期刊列表', href: '/abdc', description: '按名称、ISSN、FoR、等级与版本查询期刊。' },
        { label: 'A* 研究雷达', href: '/abdc-astar-research', description: '追踪最新文章、主题、方法与研究机会。' }
      ],
      disciplines: [
        { label: 'Information Systems', slug: 'information-systems' },
        { label: 'Management', slug: 'management' },
        { label: 'Marketing', slug: 'marketing' },
        { label: 'OB / HR', slug: 'ob-hr' },
        { label: '计算社会科学', slug: 'computational-social-science' }
      ]
    }
  };

  function activeGroupForPath(pathname) {
    if (/^\/(dashboard|fiscal-debt|financial\/debug|china-rates|housing)/.test(pathname)) return 'china';
    if (/^\/us-macro/.test(pathname)) return 'us';
    if (/^\/(abdc|abdc-astar-research)/.test(pathname)) return 'research';
    return '';
  }

  function activeSubnavHref() {
    const field = new URLSearchParams(window.location.search).get('field');
    if (field) return '/abdc-astar-research?field=' + encodeURIComponent(field);
    return window.location.pathname.replace(/\/$/, '') || '/';
  }

  const searchable = [];
  Object.keys(groups).forEach(function (key) {
    const group = groups[key];
    group.items.forEach(function (item) {
      searchable.push({ label: item.label, href: item.href, meta: group.label + ' · ' + item.description });
    });
    (group.disciplines || []).forEach(function (item) {
      searchable.push({
        label: item.label,
        href: '/abdc-astar-research?field=' + encodeURIComponent(item.slug),
        meta: 'ABDC 商科研究 · 学科频道'
      });
    });
  });

  function subnavHtml(activeGroup) {
    if (!activeGroup) return '';
    const group = groups[activeGroup];
    const activeHref = activeSubnavHref();
    const pages = group.items.map(function (item) {
      const active = activeHref === item.href;
      return '<a class="research-nav-subnav-link' + (active ? ' is-active' : '') + '" href="' + item.href + '"' +
        (active ? ' aria-current="page"' : '') + '>' + item.label + '</a>';
    }).join('');
    let fields = '';
    if (group.disciplines) {
      fields = '<span class="research-nav-subnav-divider" aria-hidden="true"></span>' +
        group.disciplines.map(function (item) {
          const href = '/abdc-astar-research?field=' + encodeURIComponent(item.slug);
          const active = activeHref === href;
          return '<a class="research-nav-subnav-link' + (active ? ' is-active' : '') + '" href="' + href + '"' +
            (active ? ' aria-current="page"' : '') + '>' + item.label + '</a>';
        }).join('');
    }
    return '<nav class="research-nav-subnav" aria-label="' + group.label + '子页面"><div class="research-nav-subnav-inner">' +
      '<span class="research-nav-subnav-label">' + group.label + '</span>' + pages + fields + '</div></nav>';
  }

  function buildNav() {
    const active = activeGroupForPath(window.location.pathname);
    const shell = document.createElement('header');
    shell.className = 'research-nav-shell';
    shell.innerHTML = '<div class="research-nav-inner">' +
      '<a class="research-nav-brand" href="/">研究工作台</a>' +
      '<nav class="research-nav-tabs" aria-label="主要研究领域">' +
      Object.keys(groups).map(function (key) {
        const group = groups[key];
        return '<a class="research-nav-tab' + (active === key ? ' is-active' : '') + '" data-group="' + key + '" href="' + group.defaultHref + '"' +
          (active === key ? ' aria-current="page"' : '') + '><span class="research-nav-tab-label">' + group.label + '</span>' +
          '<span class="research-nav-tab-summary">' + group.summary + '</span></a>';
      }).join('') + '</nav>' +
      '<div class="research-nav-search"><input type="search" aria-label="搜索研究页面" placeholder="搜索页面、指标、期刊或主题" autocomplete="off">' +
      '<div class="research-nav-search-results" role="listbox"></div></div></div>' + subnavHtml(active);
    document.body.insertBefore(shell, document.body.firstChild);
    document.body.classList.add('research-nav-mounted');
    if (active) document.body.classList.add('research-nav-has-subnav');
    return shell;
  }

  function init() {
    if (!document.body || document.querySelector('.research-nav-shell')) return;
    const shell = buildNav();
    const search = shell.querySelector('.research-nav-search input');
    const results = shell.querySelector('.research-nav-search-results');
    let searchMatches = [];
    let highlighted = -1;

    function closeSearch() {
      results.classList.remove('is-open');
      results.innerHTML = '';
      searchMatches = [];
      highlighted = -1;
    }

    function drawSearch() {
      results.innerHTML = searchMatches.length
        ? searchMatches.map(function (item, index) {
            return '<a class="research-nav-result' + (index === highlighted ? ' is-highlighted' : '') + '" href="' + item.href + '" role="option" aria-selected="' + (index === highlighted) + '">' +
              '<strong>' + item.label + '</strong><span>' + item.meta + '</span></a>';
          }).join('')
        : '<div class="research-nav-empty">没有匹配的研究页面</div>';
      results.classList.add('is-open');
    }

    search.addEventListener('input', function () {
      const query = search.value.trim().toLocaleLowerCase();
      if (!query) { closeSearch(); return; }
      searchMatches = searchable.filter(function (item) {
        return (item.label + ' ' + item.meta).toLocaleLowerCase().indexOf(query) >= 0;
      }).slice(0, 8);
      highlighted = searchMatches.length ? 0 : -1;
      drawSearch();
    });

    search.addEventListener('focus', function () {
      if (search.value.trim()) search.dispatchEvent(new Event('input'));
    });

    search.addEventListener('keydown', function (event) {
      if (!results.classList.contains('is-open')) return;
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        if (!searchMatches.length) return;
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        highlighted = (highlighted + delta + searchMatches.length) % searchMatches.length;
        drawSearch();
      } else if (event.key === 'Enter' && highlighted >= 0) {
        event.preventDefault();
        window.location.assign(searchMatches[highlighted].href);
      } else if (event.key === 'Escape') {
        closeSearch();
      }
    });

    results.addEventListener('click', function (event) {
      const link = event.target.closest && event.target.closest('a.research-nav-result');
      if (!link) return;
      event.preventDefault();
      window.location.assign(link.href);
    });

    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') closeSearch();
    });
    document.addEventListener('click', function (event) {
      if (!event.target.closest('.research-nav-search')) closeSearch();
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
