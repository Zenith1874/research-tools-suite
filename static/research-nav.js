(function () {
  'use strict';

  const groups = {
    china: {
      label: '中国宏观',
      summary: '实体 · 金融 · 财政 · 城市',
      defaultHref: '/dashboard',
      items: [
        { label: '货币信用', href: '/dashboard', description: '央行金融统计、货币与信用核心指标。' },
        { label: '实体、人口与外贸', href: '/china-macro', description: '增长、消费投资、价格景气、就业收入、人口家庭、双币种外贸与跨境资金。' },
        { label: '香港宏观', href: '/hong-kong-macro', description: '香港住房、经济、再出口贸易、储备金融与中国联动描述性分析。' },
        { label: '统计分析', href: '/macro-analytics', description: '中国、美国与中美对照的派生统计分析。' },
        { label: '趋势情景', href: '/macro-scenario', description: '宏观指标的条件路径、扰动模拟、滚动回测与缺口清单。' },
        { label: '中美 GDP', href: '/gdp', description: '全国历史规模、增长与中国省级/美国州级地区 GDP。' },
        { label: '中国房价', href: '/housing', description: '70城官方新房/二手指数、全国销售面积、BIS与安居客挂牌参考。' },
        { label: '财政债务', href: '/fiscal-debt', description: '年度财政收支、未来情景、政府债务与央行相关工具。' },
        { label: '债务推演', href: '/debt-ceiling', description: '人大批准的国债/地方债限额、剩余空间与两条时间推演线。' },
        { label: '利率汇率', href: '/china-rates', description: 'LPR、SHIBOR 与人民币中间价。' },
        { label: '城市经济', href: '/city-economy', description: '城市房价、地区 GDP、地方财政、土地财政与地方债。' },
        { label: '房价推演', href: '/housing-scenario', description: '70城多情景路径、模拟敏感性区间与历史机械回测。' }
      ]
    },
    us: {
      label: '美国宏观',
      summary: '美国宏观总览',
      defaultHref: '/us-macro',
      items: [
        { label: '美国宏观总览', href: '/us-macro', description: '就业、通胀、增长、联邦财政债务与完整利率曲线。' },
        { label: '中美 GDP', href: '/gdp', description: '全国历史规模与美国州级 GDP。' }
      ]
    },
    research: {
      label: 'ABDC 商科研究',
      summary: '期刊 · 雷达 · 理论 · 方法 · 版图',
      defaultHref: '/abdc/research',
      items: [
        { label: '研究总览', href: '/abdc/research', description: 'Business Research Workspace 入口与数据边界。' },
        { label: 'ABDC 期刊列表', href: '/abdc', description: '按名称、ISSN、FoR、等级与版本查询期刊。' },
        { label: 'A* 研究雷达', href: '/abdc-astar-research', description: '追踪最新文章、主题、方法与研究机会。' },
        { label: 'Theory Library', href: '/abdc/theories', description: '理论、构念、经典论文与应用脉络。' },
        { label: 'Construct Library', href: '/abdc/constructs', description: '构念定义、理论关系、测量元数据与论文。' },
        { label: 'Methods Lab', href: '/abdc/methods', description: '研究设计、统计与计算方法。' },
        { label: 'Literature Landscape', href: '/abdc/landscape', description: '按主题观察文献集中和相对少见组合。' },
        { label: 'My Papers', href: '/abdc/library', description: '阅读状态、收藏、笔记与最近研究论文。' }
      ],
      disciplines: [
        { label: 'Information Systems', slug: 'information-systems' },
        { label: 'Management', slug: 'management' },
        { label: 'Marketing', slug: 'marketing' },
        { label: 'OB / HR', slug: 'ob-hr' },
        { label: '计算社会科学', slug: 'computational-social-science' }
      ]
    },
    career: {
      label: '学术职业',
      summary: '职位 · 学校 · 市场 · 申请',
      defaultHref: '/faculty-jobs',
      items: [
        { label: 'Business Faculty Jobs', href: '/faculty-jobs', description: '跨美国、加拿大与欧洲公开商学院/商科职位源的规范化检索。' },
        { label: 'School Explorer', href: '/school-explorer', description: '大学研究层级、商学院证据与职位覆盖比较。' },
        { label: 'Job Market Analytics', href: '/job-market-analytics', description: '按地区、学科、职级、合同与招聘周期观察公开样本。' },
        { label: 'My Applications', href: '/my-applications', description: '本机私有的职位收藏、申请阶段、笔记和个人匹配评分。' }
      ]
    },
    tools: {
      label: '科研工具',
      summary: '阅读副本 · 文档翻译 · 语音转录',
      defaultHref: '/ebook-conversion',
      items: [
        { label: '阅读副本工坊', href: '/ebook-conversion', description: '把 PDF 转成手机看的 EPUB 和墨水屏看的裁边分栏 PDF；纯本机，不需要 GPU。' },
        { label: '学术语言工作台', href: '/paper-translation', description: '隐私优先的 PDF、DOCX 与文本翻译；GPU 按需连接，打开页面不会联系集群。' },
        { label: '研究语音工作台', href: '/audio-transcription', description: '访谈与会议的说话人区分、转录、翻译和双语字幕；GPU 按需连接。' }
      ]
    },
    leisure: {
      label: '娱乐',
      summary: '悦读FM · 按需提醒',
      defaultHref: '/yuedu-fm',
      items: [
        { label: '悦读FM', href: '/yuedu-fm', description: '本地保存标题、节目文字、封面和音频，断网也可收听。' },
        { label: 'CardCookie 监控', href: '/cardcookie-monitor', description: '手动开启 Walmart 与 Best Buy 的低频库存、折扣和价格变化提醒。' }
      ]
    }
  };

  function activeGroupForPath(pathname) {
    if (/^\/(dashboard|china-macro|hong-kong-macro|macro-analytics|macro-scenario|fiscal-debt|financial\/debug|china-rates|city-economy|housing-scenario|housing|gdp|debt-ceiling)/.test(pathname)) return 'china';
    if (/^\/us-macro/.test(pathname)) return 'us';
    if (/^\/(abdc|abdc-astar-research|research)/.test(pathname)) return 'research';
    if (/^\/(faculty-jobs|school-explorer|job-market-analytics|my-applications)/.test(pathname)) return 'career';
    if (/^\/(yuedu-fm|cardcookie-monitor)/.test(pathname)) return 'leisure';
    return '';
  }

  function activeSubnavHref() {
    const field = new URLSearchParams(window.location.search).get('field');
    if (field) return '/abdc-astar-research?field=' + encodeURIComponent(field);
    const pathname = window.location.pathname.replace(/\/$/, '') || '/';
    // Paper detail pages belong to the Paper Workspace even though their
    // route is /abdc/papers/<id>, not the workspace landing route.
    if (/^\/abdc\/papers\//.test(pathname)) return '/abdc/library';
    return pathname;
  }

  function isSubnavActive(activeHref, itemHref) {
    if (activeHref === itemHref) return true;
    // Detail routes inherit the active state of their library page. The root
    // /abdc journal route is intentionally exact so it does not also activate
    // for /abdc/research or another ABDC sub-route.
    return itemHref !== '/abdc' && activeHref.indexOf(itemHref + '/') === 0;
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
      const active = isSubnavActive(activeHref, item.href);
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
      '<div class="research-nav-brand-block"><a class="research-nav-brand" href="/">研究工作台</a>' +
      '<span class="research-nav-access" aria-live="polite">检查权限…</span></div>' +
      '<nav class="research-nav-tabs" aria-label="主要研究与工具入口">' +
      Object.keys(groups).map(function (key) {
        const group = groups[key];
        return '<a class="research-nav-tab' + (active === key ? ' is-active' : '') + '" data-group="' + key + '" href="' + group.defaultHref + '"' +
          (active === key ? ' aria-current="page"' : '') + '><span class="research-nav-tab-label">' + group.label + '</span>' +
          '<span class="research-nav-tab-summary">' + group.summary + '</span></a>';
      }).join('') + '</nav>' +
      '<div class="research-nav-search"><input type="search" aria-label="搜索研究页面" placeholder="搜索页面、指标、期刊或工具" autocomplete="off">' +
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
    const access = shell.querySelector('.research-nav-access');
    let searchMatches = [];
    let highlighted = -1;

    function protectReadOnlyControls() {
      const writeLabel = /(更新|同步观测表|全量回填|重新分类|健康检查|补全|保存)/;
      document.querySelectorAll('button').forEach(function (button) {
        if (!writeLabel.test((button.textContent || '').trim())) return;
        button.disabled = true;
        button.classList.add('research-nav-write-disabled');
        button.title = '局域网只读模式：请在服务器本机执行此操作';
      });
    }

    fetch('/api/health', { cache: 'no-store' })
      .then(function (response) { return response.json(); })
      .then(function (health) {
        const canWrite = Boolean(health.client_can_write);
        access.textContent = canWrite ? '本机管理' : '局域网只读';
        access.classList.add(canWrite ? 'is-manage' : 'is-read-only');
        document.body.dataset.accessMode = canWrite ? 'manage' : 'read-only';
        if (!canWrite) {
          protectReadOnlyControls();
          new MutationObserver(protectReadOnlyControls).observe(document.body, {
            childList: true,
            subtree: true
          });
        }
      })
      .catch(function () { access.textContent = '状态未知'; });

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
