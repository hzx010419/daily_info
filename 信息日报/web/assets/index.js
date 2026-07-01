// 首页：栏目 tab（往期日报 / 追踪线 / 全部线索）+ 全局搜索 + 分类筛选
// 卡片式 newsroom 排版；移动端与桌面端由 CSS 提供两套布局
(function () {
  var searchEl = document.getElementById('search');
  var sortEl = document.getElementById('sort');
  var sortBox = document.getElementById('sort-box');
  var titleEl = document.getElementById('site-title');
  var subtitleEl = document.getElementById('site-subtitle');
  var catFilterEl = document.getElementById('cat-filter');

  var issueListEl = document.getElementById('issue-list');
  var timelineListEl = document.getElementById('timeline-list');
  var clueResultsEl = document.getElementById('clue-results');

  var state = {
    tab: 'issues', cat: '',
    issues: [], timelines: [], clues: [], categories: [],
    loadedTimelines: false, loadedClues: false,
  };

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function fmtDate(d, w) {
    var p = (d || '').split('-');
    if (p.length !== 3) return d + (w ? ' ' + w : '');
    return p[0] + '年' + p[1] + '月' + p[2] + '日' + (w ? ' ' + w : '');
  }
  function fmtShort(d) {
    var p = (d || '').split('-');
    return p.length === 3 ? (p[1] + '.' + p[2]) : d;
  }
  function fetchJSON(url, timeout) {
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { reject(new Error('加载超时')); }, timeout || 10000);
      fetch(url).then(function (r) {
        clearTimeout(timer);
        if (!r.ok) throw new Error('状态码 ' + r.status);
        return r.json();
      }).then(resolve).catch(function (e) { clearTimeout(timer); reject(e); });
    });
  }

  var CAT_COLORS = {
    'AI': '#4b56d2', '科技': '#0ea5b7', '金融': '#1f9d57', '消费民生': '#e08a1e',
    '文旅': '#d4487d', '数字内容': '#8b46d6', '时政': '#d0453a', '企业商业': '#5566e0',
    '地方治理': '#0f9b8e', '社会热点': '#7a828e',
  };
  function catColor(c) { return CAT_COLORS[c] || '#7a828e'; }
  function eyebrow(c) {
    if (!c) return '';
    return '<span class="eyebrow" style="color:' + catColor(c) + '">' + escapeHtml(c) + '</span>';
  }
  function miniTags(list, n) {
    return (list || []).slice(0, n || 3).map(function (x) {
      return '<span class="mini-tag">' + escapeHtml(x) + '</span>';
    }).join('');
  }

  // ---------- 分类筛选栏 ----------
  function renderCatFilter() {
    if (state.tab === 'issues' || !state.categories.length) { catFilterEl.hidden = true; return; }
    catFilterEl.hidden = false;
    var chips = ['<button class="chip' + (state.cat === '' ? ' active' : '') + '" data-cat="">全部</button>'];
    state.categories.forEach(function (c) {
      var active = state.cat === c.name ? ' active' : '';
      chips.push('<button class="chip' + active + '" data-cat="' + escapeHtml(c.name) +
        '" style="--chip:' + catColor(c.name) + '">' + escapeHtml(c.name) +
        '<span class="chip-n">' + c.count + '</span></button>');
    });
    catFilterEl.innerHTML = chips.join('');
  }

  // ---------- 往期日报（头条大卡 + 卡片网格）----------
  function renderIssues() {
    var kw = (searchEl.value || '').trim().toLowerCase();
    var order = sortEl.value;
    var items = state.issues.slice();
    if (kw) {
      items = items.filter(function (it) {
        return (it.date || '').toLowerCase().indexOf(kw) >= 0 ||
          (it.headline || '').toLowerCase().indexOf(kw) >= 0;
      });
    }
    items.sort(function (a, b) {
      return order === 'asc' ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date);
    });
    if (!items.length) { issueListEl.innerHTML = '<div class="empty">没有匹配的日报</div>'; return; }
    issueListEl.innerHTML = items.map(function (it, i) {
      var feat = (i === 0 && !kw && order === 'desc') ? ' featured' : '';
      return '<a class="issue-card' + feat + '" href="issue.html?date=' + encodeURIComponent(it.date) + '">' +
        '<div class="ic-top"><span class="ic-kicker">每日资讯</span>' +
        '<span class="ic-date">' + fmtDate(it.date, it.weekday) + '</span></div>' +
        '<h3 class="ic-headline">' + escapeHtml(it.headline || '') + '</h3>' +
        '<div class="ic-meta">' + (it.clue_count || 0) + ' 条线索<span class="ic-go">阅读全文 →</span></div>' +
        '</a>';
    }).join('');
  }

  // ---------- 追踪线 ----------
  function renderTimelines() {
    var kw = (searchEl.value || '').trim().toLowerCase();
    var items = state.timelines.filter(function (t) {
      if (state.cat && t.category !== state.cat) return false;
      if (!kw) return true;
      if ((t.title || '').toLowerCase().indexOf(kw) >= 0) return true;
      return (t.tags || []).join(' ').toLowerCase().indexOf(kw) >= 0;
    });
    if (!items.length) {
      timelineListEl.innerHTML = '<div class="empty">暂无跨期追踪线<br/><small>多期出现同一主题后会自动串联</small></div>';
      return;
    }
    timelineListEl.innerHTML = items.map(function (t) {
      var steps = (t.entries || []).map(function (e) {
        return '<a class="tl-step" href="issue.html?date=' + encodeURIComponent(e.date) + '&i=' + (e.index || '') + '">' +
          '<span class="tl-dot"></span><span class="tl-date">' + fmtShort(e.date) + '</span>' +
          '<span class="tl-title">' + escapeHtml(e.title || '') + '</span></a>';
      }).join('');
      return '<div class="timeline-card">' +
        '<div class="tl-head">' + eyebrow(t.category) +
        '<span class="tl-span">跨 ' + (t.issues || t.count) + ' 期 · ' + (t.count) + ' 条 · ' + fmtShort(t.date_start) + ' – ' + fmtShort(t.date_end) + '</span></div>' +
        '<h3 class="tl-name">' + escapeHtml(t.title || '') + '</h3>' +
        (miniTags(t.tags, 6) ? '<div class="tl-tags">' + miniTags(t.tags, 6) + '</div>' : '') +
        '<div class="tl-steps">' + steps + '</div></div>';
    }).join('');
  }

  // ---------- 全部线索（信息流卡片）----------
  function renderClues() {
    var kw = (searchEl.value || '').trim().toLowerCase();
    var items = state.clues.filter(function (c) {
      if (state.cat && c.category !== state.cat) return false;
      if (!kw) return true;
      if ((c.title || '').toLowerCase().indexOf(kw) >= 0) return true;
      if ((c.excerpt || '').toLowerCase().indexOf(kw) >= 0) return true;
      return (c.topics || []).join(' ').toLowerCase().indexOf(kw) >= 0;
    });
    if (!items.length) { clueResultsEl.innerHTML = '<div class="empty">没有匹配的线索</div>'; return; }
    items = items.slice(0, 500);
    clueResultsEl.innerHTML = items.map(function (c) {
      var meta = fmtShort(c.date) + (c.sources ? ' · ' + c.sources + ' 来源' : '');
      return '<a class="feed-card" href="issue.html?date=' + encodeURIComponent(c.date) + '&i=' + (c.index || '') + '">' +
        '<div class="fc-top">' + eyebrow(c.category) + '<span class="fc-meta">' + meta + '</span></div>' +
        '<h3 class="fc-title">' + escapeHtml(c.title || '') + '</h3>' +
        (c.excerpt ? '<p class="fc-excerpt">' + escapeHtml(c.excerpt) + '…</p>' : '') +
        (miniTags(c.topics, 3) ? '<div class="fc-tags">' + miniTags(c.topics, 3) + '</div>' : '') +
        '</a>';
    }).join('');
  }

  function renderCurrent() {
    renderCatFilter();
    sortBox.style.display = state.tab === 'issues' ? '' : 'none';
    if (state.tab === 'issues') renderIssues();
    else if (state.tab === 'timelines') renderTimelines();
    else renderClues();
  }

  function showPanel(tab) {
    state.tab = tab;
    document.querySelectorAll('.tab').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-tab') === tab);
    });
    document.getElementById('panel-issues').hidden = tab !== 'issues';
    document.getElementById('panel-timelines').hidden = tab !== 'timelines';
    document.getElementById('panel-clues').hidden = tab !== 'clues';
    if (tab === 'timelines' && !state.loadedTimelines) loadTimelines();
    if (tab === 'clues' && !state.loadedClues) loadClues();
    renderCurrent();
  }

  function loadTimelines() {
    state.loadedTimelines = true;
    fetchJSON('data/timelines.json').then(function (d) {
      state.timelines = d.timelines || []; renderCurrent();
    }).catch(function () { timelineListEl.innerHTML = '<div class="empty">追踪线数据暂未生成</div>'; });
  }
  function loadClues() {
    state.loadedClues = true;
    fetchJSON('data/search-index.json').then(function (d) {
      state.clues = d.entries || []; state.categories = d.categories || []; renderCurrent();
    }).catch(function () { clueResultsEl.innerHTML = '<div class="empty">线索索引暂未生成</div>'; });
  }

  fetchJSON('data/manifest.json').then(function (data) {
    if (data.title && titleEl) titleEl.textContent = data.title;
    if (data.subtitle && subtitleEl) subtitleEl.textContent = data.subtitle;
    state.issues = data.issues || [];
    renderCurrent();
  }).catch(function (err) {
    issueListEl.innerHTML = '<div class="empty">数据加载失败：' + err.message +
      '<br/><small>请检查网络连接后刷新页面</small></div>';
  });

  document.getElementById('tabbar').addEventListener('click', function (e) {
    var btn = e.target.closest('.tab');
    if (btn) showPanel(btn.getAttribute('data-tab'));
  });
  catFilterEl.addEventListener('click', function (e) {
    var chip = e.target.closest('.chip');
    if (!chip) return;
    state.cat = chip.getAttribute('data-cat') || '';
    renderCurrent();
  });
  searchEl.addEventListener('input', renderCurrent);
  sortEl.addEventListener('change', renderCurrent);
})();
