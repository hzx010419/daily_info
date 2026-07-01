// 首页：栏目 tab（往期日报 / 追踪线 / 全部线索）+ 全局搜索 + 分类标签筛选
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
    tab: 'issues',
    cat: '',            // 当前选中的分类标签（空 = 全部）
    issues: [],         // manifest.issues
    timelines: [],      // timelines.json
    clues: [],          // search-index.entries
    categories: [],     // [{name,count}]
    loadedTimelines: false,
    loadedClues: false,
  };

  // ---------- 工具 ----------
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
    return p.length === 3 ? (p[1] + '/' + p[2]) : d;
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

  // 分类标签配色
  var CAT_COLORS = {
    'AI': '#1664ff', '科技': '#0fa3c4', '金融': '#27a35a', '消费民生': '#f5821f',
    '文旅': '#e0457b', '数字内容': '#9b2fd6', '时政': '#d63b3b', '企业商业': '#5b6bef',
    '地方治理': '#13b5b1', '社会热点': '#86909c',
  };
  function catColor(c) { return CAT_COLORS[c] || '#86909c'; }
  function catBadge(c) {
    if (!c) return '';
    return '<span class="cat-badge" style="background:' + catColor(c) + '">' + escapeHtml(c) + '</span>';
  }

  // ---------- 分类筛选栏 ----------
  function renderCatFilter() {
    if (state.tab === 'issues' || !state.categories.length) {
      catFilterEl.hidden = true;
      return;
    }
    catFilterEl.hidden = false;
    var chips = ['<button class="chip' + (state.cat === '' ? ' active' : '') + '" data-cat="">全部</button>'];
    state.categories.forEach(function (c) {
      var active = state.cat === c.name ? ' active' : '';
      chips.push('<button class="chip' + active + '" data-cat="' + escapeHtml(c.name) + '" style="--chip:' + catColor(c.name) + '">' +
        escapeHtml(c.name) + '<span class="chip-n">' + c.count + '</span></button>');
    });
    catFilterEl.innerHTML = chips.join('');
  }

  // ---------- 往期日报 ----------
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
    issueListEl.innerHTML = items.map(function (it) {
      return '<a class="issue-card" href="issue.html?date=' + encodeURIComponent(it.date) + '">' +
        '<span class="date">' + fmtDate(it.date, it.weekday) + '</span>' +
        '<span class="count">' + (it.clue_count || 0) + ' 条线索</span>' +
        '<span class="headline">' + escapeHtml(it.headline || '') + '</span>' +
        '<span class="arrow">›</span></a>';
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
        return '<a class="tl-step" href="issue.html?date=' + encodeURIComponent(e.date) + '">' +
          '<span class="tl-dot"></span>' +
          '<span class="tl-date">' + fmtShort(e.date) + '</span>' +
          '<span class="tl-title">' + escapeHtml(e.title || '') + '</span></a>';
      }).join('');
      var tags = (t.tags || []).map(function (x) {
        return '<span class="mini-tag">' + escapeHtml(x) + '</span>';
      }).join('');
      return '<div class="timeline-card">' +
        '<div class="tl-head">' + catBadge(t.category) +
        '<span class="tl-name">' + escapeHtml(t.title || '') + '</span></div>' +
        '<div class="tl-meta">跨 ' + t.count + ' 期 · ' + fmtShort(t.date_start) + ' → ' + fmtShort(t.date_end) + '</div>' +
        (tags ? '<div class="tl-tags">' + tags + '</div>' : '') +
        '<div class="tl-steps">' + steps + '</div></div>';
    }).join('');
  }

  // ---------- 全部线索（全局搜索） ----------
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
    // 默认按日期倒序
    items = items.slice(0, 500);
    clueResultsEl.innerHTML = '<div class="result-count">共 ' + items.length + ' 条线索</div>' +
      items.map(function (c) {
        var tags = (c.topics || []).slice(0, 4).map(function (x) {
          return '<span class="mini-tag">' + escapeHtml(x) + '</span>';
        }).join('');
        return '<a class="result-card" href="issue.html?date=' + encodeURIComponent(c.date) + '">' +
          '<div class="rc-top">' + catBadge(c.category) +
          '<span class="rc-date">' + fmtShort(c.date) + '</span></div>' +
          '<div class="rc-title">' + escapeHtml(c.title || '') + '</div>' +
          (c.excerpt ? '<div class="rc-excerpt">' + escapeHtml(c.excerpt) + '…</div>' : '') +
          (tags ? '<div class="rc-tags">' + tags + '</div>' : '') +
          '</a>';
      }).join('');
  }

  // ---------- 渲染分发 ----------
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

  // ---------- 数据加载 ----------
  function loadTimelines() {
    state.loadedTimelines = true;
    fetchJSON('data/timelines.json').then(function (d) {
      state.timelines = d.timelines || [];
      renderCurrent();
    }).catch(function () {
      timelineListEl.innerHTML = '<div class="empty">追踪线数据暂未生成</div>';
    });
  }
  function loadClues() {
    state.loadedClues = true;
    fetchJSON('data/search-index.json').then(function (d) {
      state.clues = d.entries || [];
      state.categories = d.categories || [];
      renderCurrent();
    }).catch(function () {
      clueResultsEl.innerHTML = '<div class="empty">线索索引暂未生成</div>';
    });
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

  // ---------- 事件 ----------
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
