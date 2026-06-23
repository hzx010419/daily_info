// 首页：加载 manifest，渲染往期归档列表，支持搜索与排序
(function () {
  var listEl = document.getElementById('issue-list');
  var searchEl = document.getElementById('search');
  var sortEl = document.getElementById('sort');
  var titleEl = document.getElementById('site-title');
  var subtitleEl = document.getElementById('site-subtitle');

  var allIssues = [];

  function fmtDate(dateStr, weekday) {
    // 2026-06-22 -> 2026年06月22日 星期一
    var parts = (dateStr || '').split('-');
    if (parts.length !== 3) return dateStr + (weekday ? ' ' + weekday : '');
    return parts[0] + '年' + parts[1] + '月' + parts[2] + '日' + (weekday ? ' ' + weekday : '');
  }

  function render() {
    var kw = (searchEl.value || '').trim().toLowerCase();
    var order = sortEl.value;

    var items = allIssues.slice();
    if (kw) {
      items = items.filter(function (it) {
        return (
          (it.date || '').toLowerCase().indexOf(kw) >= 0 ||
          (it.headline || '').toLowerCase().indexOf(kw) >= 0
        );
      });
    }
    items.sort(function (a, b) {
      return order === 'asc'
        ? a.date.localeCompare(b.date)
        : b.date.localeCompare(a.date);
    });

    if (!items.length) {
      listEl.innerHTML = '<div class="empty">没有匹配的日报</div>';
      return;
    }

    var html = items
      .map(function (it) {
        return (
          '<a class="issue-card" href="issue.html?date=' + encodeURIComponent(it.date) + '">' +
          '<span class="date">' + fmtDate(it.date, it.weekday) + '</span>' +
          '<span class="count">' + (it.clue_count || 0) + ' 条线索</span>' +
          '<span class="headline">' + escapeHtml(it.headline || '') + '</span>' +
          '<span class="arrow">›</span>' +
          '</a>'
        );
      })
      .join('');
    listEl.innerHTML = html;
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // 带超时的 fetch（10 秒）
  function fetchWithTimeout(url, timeout) {
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () {
        reject(new Error('加载超时，请检查网络连接'));
      }, timeout || 10000);
      fetch(url)
        .then(function (r) {
          clearTimeout(timer);
          resolve(r);
        })
        .catch(function (err) {
          clearTimeout(timer);
          reject(err);
        });
    });
  }

  fetchWithTimeout('data/manifest.json')
    .then(function (r) {
      if (!r.ok) throw new Error('manifest 加载失败（状态码 ' + r.status + '）');
      return r.json();
    })
    .then(function (data) {
      if (data.title && titleEl) titleEl.textContent = data.title;
      if (data.subtitle && subtitleEl) subtitleEl.textContent = data.subtitle;
      allIssues = data.issues || [];
      render();
    })
    .catch(function (err) {
      listEl.innerHTML =
        '<div class="empty">数据加载失败：' + err.message +
        '<br/><small>请检查网络连接后刷新页面</small></div>';
    });

  searchEl.addEventListener('input', render);
  sortEl.addEventListener('change', render);
})();
