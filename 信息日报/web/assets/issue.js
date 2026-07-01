// 详情页：根据 URL 中的 date 加载该期数据，渲染 10 条写作线索
(function () {
  var clueListEl = document.getElementById('clue-list');
  var dateEl = document.getElementById('issue-date');
  var statsEl = document.getElementById('issue-stats');
  var topbarDateEl = document.getElementById('topbar-date');

  // 课题标签配色（循环使用，视觉接近示意图）
  var TAG_COLORS = [
    '#1664ff', '#9b2fd6', '#13b5b1', '#27a35a',
    '#f5821f', '#e0457b', '#5b6bef', '#0fa3c4',
  ];

  function getParam(name) {
    var m = new RegExp('[?&]' + name + '=([^&]+)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function fmtDate(dateStr, weekday) {
    var parts = (dateStr || '').split('-');
    if (parts.length !== 3) return dateStr + (weekday ? ' ' + weekday : '');
    return parts[0] + '年' + parts[1] + '月' + parts[2] + '日' + (weekday ? ' ' + weekday : '');
  }

  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // 动态更新 Open Graph meta 标签
  function updateOGTags(title, description, date) {
    var baseUrl = location.origin + location.pathname.replace(/issue\.html.*$/, '');
    var pageUrl = baseUrl + 'issue.html?date=' + date;
    
    // 更新 og:title
    updateMetaTag('property', 'og:title', title);
    // 更新 og:description
    updateMetaTag('property', 'og:description', description || '每日热点信息，点击查看详情');
    // 更新 og:url
    updateMetaTag('property', 'og:url', pageUrl);
    // 更新 og:image (可选：如果有每日动态图片的话)
    // updateMetaTag('property', 'og:image', baseUrl + 'assets/og-' + date + '.png');
  }

  // 动态更新 Twitter Card meta 标签
  function updateTwitterTags(title, description) {
    updateMetaTag('name', 'twitter:title', title);
    updateMetaTag('name', 'twitter:description', description || '每日热点信息，点击查看详情');
  }

  // 通用函数：更新或创建 meta 标签
  function updateMetaTag(attr, attrValue, content) {
    var selector = 'meta[' + attr + '="' + attrValue + '"]';
    var meta = document.querySelector(selector);
    
    if (meta) {
      meta.setAttribute('content', content);
    } else {
      // 如果标签不存在，创建新的
      meta = document.createElement('meta');
      meta.setAttribute(attr, attrValue);
      meta.setAttribute('content', content);
      document.head.appendChild(meta);
    }
  }

  function renderTopics(topics) {
    if (!topics || !topics.length) return '';
    var tags = topics
      .map(function (t, i) {
        var color = TAG_COLORS[i % TAG_COLORS.length];
        return '<span class="topic-tag" style="background:' + color + '">' +
          escapeHtml(t) + '</span>';
      })
      .join('');
    return (
      '<div class="clue-row">' +
      '<span class="clue-label">相关课题：</span>' +
      '<div class="topic-tags">' + tags + '</div>' +
      '</div>'
    );
  }

  function renderSources(sources) {
    if (!sources || !sources.length) return '';
    var items = sources
      .map(function (s) {
        var label = '《' + escapeHtml(s.title || '') + '》';
        if (s.url) {
          return '<a class="source-link" href="' + escapeHtml(s.url) +
            '" target="_blank" rel="noopener">' + label + '</a>';
        }
        return '<span class="source-nolink">' + label + '</span>';
      })
      .join('<span class="source-sep">、</span>');
    return (
      '<div class="source-block">' +
      '<span class="clue-label">来源列表：</span>' +
      '<div class="source-list">' + items + '</div>' +
      '</div>'
    );
  }

  // 线索分类徽章配色
  var CAT_COLORS_MAP = {
    'AI': '#1664ff', '科技': '#0fa3c4', '金融': '#27a35a', '消费民生': '#f5821f',
    '文旅': '#e0457b', '数字内容': '#9b2fd6', '时政': '#d63b3b', '企业商业': '#5b6bef',
    '地方治理': '#13b5b1', '社会热点': '#86909c',
  };
  function renderCatBadge(cat) {
    if (!cat) return '';
    var color = CAT_COLORS_MAP[cat] || '#86909c';
    return '<span class="cat-badge" style="background:' + color + '">' + escapeHtml(cat) + '</span>';
  }

  function renderClue(clue) {
    var catRow = clue.category
      ? '<div class="clue-cat-row">' + renderCatBadge(clue.category) + '</div>'
      : '';
    return (
      '<div class="clue-card">' +
      catRow +
      '<div class="clue-title">' + clue.index + '. ' + escapeHtml(clue.title || '') + '</div>' +
      '<div class="clue-summary">' + escapeHtml(clue.summary || '') + '</div>' +
      renderTopics(clue.topics) +
      renderSources(clue.sources) +
      '</div>'
    );
  }

  function render(data) {
    var formattedDate = fmtDate(data.date, data.weekday);
    dateEl.textContent = formattedDate;
    topbarDateEl.textContent = formattedDate;
    
    var st = data.stats || {};
    var description = '';
    if (st.total) {
      statsEl.textContent =
        '今天的日报，从 ' + st.total + ' 条资讯中筛选出 ' +
        (st.selected || 0) + ' 条潜在相关资讯，聚合成 ' +
        (st.clues || 0) + ' 条线索';
      description = '从 ' + st.total + ' 条资讯中筛选出 ' +
        (st.selected || 0) + ' 条潜在相关资讯，聚合成 ' +
        (st.clues || 0) + ' 条线索';
    }
    
    var html = (data.clues || []).map(renderClue).join('');
    clueListEl.innerHTML = html || '<div class="empty">本期暂无线索</div>';
    
    var pageTitle = '材料选题日报 · ' + formattedDate;
    document.title = pageTitle;
    
    // 动态更新 Open Graph meta 标签，优化分享卡片
    updateOGTags(pageTitle, description, data.date);
    updateTwitterTags(pageTitle, description);

    // 通知分享功能：数据已就绪
    if (window._onShareDataReady) {
      window._onShareDataReady(data);
    }

    // 添加下载全文链接
    if (data.docx_url && data.docx_name) {
      var dlHtml = '<div class="download-block">' +
        '<span class="dl-label">下载全文：</span>' +
        '<a class="dl-link" href="#" ' +
        'data-url="' + escapeHtml(data.docx_url) + '" ' +
        'data-name="' + escapeHtml(data.docx_name) + '" ' +
        'onclick="window._downloadDocx(this);return false;">' +
        escapeHtml(data.docx_name) +
        '</a></div>';
      clueListEl.innerHTML += dlHtml;
    }
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

  var date = getParam('date');
  if (!date) {
    clueListEl.innerHTML = '<div class="empty">缺少日期参数</div>';
    return;
  }

  // 分享按钮已由 share.js 处理（生成金句卡片弹窗）

  fetchWithTimeout('data/' + date + '.json')
    .then(function (r) {
      if (!r.ok) throw new Error('该期数据不存在（状态码 ' + r.status + '）');
      return r.json();
    })
    .then(render)
    .catch(function (err) {
      clueListEl.innerHTML = '<div class="empty">加载失败：' + err.message + '</div>';
    });
})();

// 全局：强制下载 docx 文件（避免浏览器直接打开或错误命名）
window._downloadDocx = function (el) {
  var url = el.getAttribute('data-url');
  var filename = el.getAttribute('data-name');
  if (!url || !filename) return;

  // 先检查文件是否存在（带超时）
  var timer = setTimeout(function () {
    alert('下载超时，请稍后重试');
  }, 10000);

  fetch(url, { method: 'HEAD' })
    .then(function (res) {
      clearTimeout(timer);
      if (!res.ok) {
        alert('文件不存在，可能无法下载');
        return;
      }
      // 文件存在，开始下载
      return fetch(url);
    })
    .then(function (res) {
      if (!res || !res.ok) return;
      return res.blob();
    })
    .then(function (blob) {
      if (!blob) return;
      var mimeBlob = new Blob([blob], {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
      });
      var blobUrl = URL.createObjectURL(mimeBlob);
      var a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      a.style.display = 'none';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(blobUrl); }, 1000);
    })
    .catch(function (err) {
      clearTimeout(timer);
      console.error('下载失败', err);
      alert('下载失败，请稍后重试');
    });
};

