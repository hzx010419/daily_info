/**
 * 分享生图功能 - 生成带二维码的分享图片
 * 风格参考：信息卡片式设计（类似 i-MU / 优选游戏信号）
 */
(function () {
  var currentData = null;
  var currentUrl = '';

  // 获取当前日期参数
  function getDateParam() {
    var m = new RegExp('[?&]date=([^&]+)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  // 生成二维码（简化版）
  function generateQRCode(text, size) {
    var canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    var ctx = canvas.getContext('2d');

    function simpleHash(str) {
      var hash = 0;
      for (var i = 0; i < str.length; i++) {
        hash = ((hash << 5) - hash) + str.charCodeAt(i);
        hash = hash & hash;
      }
      return Math.abs(hash);
    }

    var hash = simpleHash(text);
    var moduleCount = 21;
    var modules = [];
    var seed = hash;

    for (var i = 0; i < moduleCount * moduleCount; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      modules.push(seed % 3 === 0);
    }

    function drawFinder(x, y, cs) {
      ctx.fillStyle = '#000'; ctx.fillRect(x, y, cs * 7, cs * 7);
      ctx.fillStyle = '#fff'; ctx.fillRect(x + cs, y + cs, cs * 5, cs * 5);
      ctx.fillStyle = '#000'; ctx.fillRect(x + cs * 2, y + cs * 2, cs * 3, cs * 3);
    }

    var padding = Math.floor(size * 0.08);
    var drawArea = size - padding * 2;
    var cellSize = drawArea / moduleCount;

    // 白底
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, size, size);

    // 定位图案
    drawFinder(padding, padding, cellSize);
    drawFinder(padding + (moduleCount - 7) * cellSize, padding, cellSize);
    drawFinder(padding, padding + (moduleCount - 7) * cellSize, cellSize);

    // 数据模块
    for (var row = 0; row < moduleCount; row++) {
      for (var col = 0; col < moduleCount; col++) {
        if ((row < 8 && col < 8) ||
            (row < 8 && col > moduleCount - 9) ||
            (row > moduleCount - 9 && col < 8)) continue;
        var idx = row * moduleCount + col;
        if (modules[idx]) {
          ctx.fillStyle = '#000';
          ctx.fillRect(
            padding + col * cellSize + 0.5,
            padding + row * cellSize + 0.5,
            Math.max(1, cellSize - 1),
            Math.max(1, cellSize - 1)
          );
        }
      }
    }

    return canvas;
  }

  function truncateText(text, maxChars) {
    if (!text || text.length <= maxChars) return text || '';
    return text.substring(0, maxChars) + '...';
  }

  /**
   * 文本换行 — 返回每行的文本和绘制位置 y 坐标数组
   */
  function layoutText(ctx, text, maxWidth, fontSize, lineHeight) {
    ctx.font = fontSize + 'px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    var lines = [];
    var paragraphs = text.split('\n');

    for (var p = 0; p < paragraphs.length; p++) {
      var chars = paragraphs[p].split('');
      var line = '';

      for (var i = 0; i < chars.length; i++) {
        var testLine = line + chars[i];
        if (ctx.measureText(testLine).width > maxWidth && line !== '') {
          lines.push(line);
          line = chars[i];
        } else {
          line = testLine;
        }
      }
      if (line) lines.push(line);
    }
    return lines;
  }

  // ========== 主函数：生成分享图 ==========
  function generateShareImage(data) {
    var dateStr = data.date || getDateParam();
    var clues = data.clues || [];
    var stats = data.stats || {};

    var W = 750;

    /* ---- 第一遍：计算实际需要的画布高度 ---- */
    var tempCanvas = document.createElement('canvas');
    tempCanvas.width = W;
    tempCanvas.height = 1000;
    var tCtx = tempCanvas.getContext('2d');

    var PAD_X = 44;        // 左右内边距
    var CONTENT_W = W - PAD_X * 2; // 内容宽度

    // 各区块高度估算
    var headerH = 110;     // 蓝色头部
    var statsBlockH = 95;  // 数据统计区
    var dividerH = 16;     // 分隔线区
    var hotTitleH = 48;    // "今日热点"标题行
    var clueGap = 6;       // 线索间距
    var footerH = 130;     // 底部蓝条+内容

    var cluesTotalH = 0;
    var MAX_CLUES = Math.min(clues.length, 4); // 最多显示4条线索避免溢出

    for (var c = 0; c < MAX_CLUES; c++) {
      var clue = clues[c];
      if (!clue) continue;

      // 标题一行
      tCtx.font = 'bold 25px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
      var titleLines = layoutText(tCtx, truncateText((c + 1) + '. ' + clue.title, 22), CONTENT_W, 25, 34);

      // 摘要最多2行
      tCtx.font = '20px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
      var summaryLines = layoutText(tCtx, truncateText(clue.summary || '', 50), CONTENT_W, 20, 30);

      var clueH =
        8 +                              // 上留白
        titleLines.length * 34 +         // 标题行高
        4 +                              // 标题-摘要间隔
        Math.min(summaryLines.length, 2) * 30 +  // 摘要行高（最多2行）
        12;                             // 下留白

      cluesTotalH += clueH + clueGap;
    }

    // 还有更多提示
    if (clues.length > MAX_CLUES) {
      cluesTotalH += 36;
    }

    var H = headerH + 18 + statsBlockH + dividerH + hotTitleH + 10 + cluesTotalH + 24 + footerH;

    /* ---- 第二遍：正式绘制 ---- */
    var canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    var ctx = canvas.getContext('2d');

    // ===== 背景 =====
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, H);

    // 顶部蓝色渐变条
    var gradTop = ctx.createLinearGradient(0, 0, W, 0);
    gradTop.addColorStop(0, '#1664ff');
    gradTop.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradTop;
    roundRect(ctx, 0, 0, W, headerH, { br: 18, bl: 18 });
    ctx.fill();

    // 底部蓝色渐变条
    var gradBottom = ctx.createLinearGradient(0, H - footerH, W, H - footerH);
    gradBottom.addColorStop(0, '#1664ff');
    gradBottom.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradBottom;
    roundRect(ctx, 0, H - footerH, W, footerH, { tr: 18, tl: 18 });
    ctx.fill();

    // ===== 头部文字 =====
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 34px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('信息选题参考', W / 2, 40);

    ctx.font = '20px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillText(formatChineseDate(dateStr, data.weekday), W / 2, 78);

    // ===== 数据统计 =====
    var y = headerH + 26;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';

    ctx.font = 'bold 25px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('📊 本期数据', PAD_X, y);

    y += 42;
    ctx.font = '21px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#333333';

    var statParts = [];
    if (stats.total) statParts.push('筛选资讯 ' + stats.total + ' 条');
    if (stats.selected) statParts.push('相关内容 ' + stats.selected + ' 条');
    if (stats.clues) statParts.push('聚合线索 ' + stats.clues + ' 条');
    ctx.fillText(statParts.join('  |  '), PAD_X, y);

    // ===== 分隔线 =====
    y += 30;
    ctx.strokeStyle = '#e5e6eb';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PAD_X, y);
    ctx.lineTo(W - PAD_X, y);
    ctx.stroke();

    // ===== 今日热点 =====
    y += 32;
    ctx.font = 'bold 25px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('🔥 今日热点', PAD_X, y);

    y += 28;

    // 绘制线索列表
    for (var c2 = 0; c2 < MAX_CLUES; c2++) {
      var clue2 = clues[c2];
      if (!clue2) continue;

      // 标题
      y += 8;
      ctx.font = 'bold 23px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#1d2129';
      var fullTitle = (c2 + 1) + '. ' + truncateText(clue2.title, 22);
      ctx.fillText(fullTitle, PAD_X, y);

      // 摘要（最多2行）
      y += 32;
      ctx.font = '19px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#555555';
      var sumText = truncateText(clue2.summary || '', 50);
      var sumLines = layoutText(ctx, sumText, CONTENT_W, 19, 29);
      for (var sl = 0; sl < Math.min(sumLines.length, 2); sl++) {
        ctx.fillText(sumLines[sl], PAD_X + 14, y);
        y += 29;
      }

      y += 10;
    }

    // 更多提示
    if (clues.length > MAX_CLUES) {
      y += 8;
      ctx.font = '18px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#86909c';
      ctx.fillText(
        '... 还有 ' + (clues.length - MAX_CLUES) + ' 条线索，扫码查看完整版',
        PAD_X,
        y
      );
    }

    // ===== 底部区域 =====
    var bottomY = H - footerH;

    // 二维码 — 完全在底部蓝色区域内
    var qrSize = 108;
    var qrX = W - PAD_X - qrSize;
    var qrY = bottomY + 10;
    var qrCanvas = generateQRCode(currentUrl, qrSize);
    ctx.drawImage(qrCanvas, qrX, qrY, qrSize, qrSize);

    // 扫码提示
    ctx.font = '13px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.75)';
    ctx.textAlign = 'center';
    ctx.fillText('扫码查看完整', qrX + qrSize / 2, qrY + qrSize + 20);

    // 左侧网站信息
    ctx.textAlign = 'left';
    ctx.font = 'bold 21px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.fillText('信息选题日报', PAD_X, bottomY + 45);

    ctx.font = '16px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.fillText('dailyinfox.cn', PAD_X, bottomY + 72);

    return canvas.toDataURL('image/png', 1.0);
  }

  /** 圆角矩形路径辅助函数 */
  function roundRect(ctx, x, y, w, h, r) {
    r = r || {};
    var rtl = r.tl || 0, rtr = r.tr || 0,
        rbr = r.br || 0, rbl = r.bl || 0;
    ctx.beginPath();
    ctx.moveTo(x + rtl, y);
    ctx.lineTo(x + w - rtr, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + rtr);
    ctx.lineTo(x + w, y + h - rbr);
    ctx.quadraticCurveTo(x + w, y + h, x + w - rbr, y + h);
    ctx.lineTo(x + rbl, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - rbl);
    ctx.lineTo(x, y + rtl);
    ctx.quadraticCurveTo(x, y, x + rtl, y);
    ctx.closePath();
  }

  // 格式化中文日期
  function formatChineseDate(dateStr, weekday) {
    var parts = (dateStr || '').split('-');
    if (parts.length !== 3) return dateStr;
    var result = parts[0] + '年' + parseInt(parts[1]) + '月' + parseInt(parts[2]) + '日';
    if (weekday) result += ' ' + weekday;
    return result;
  }

  // ========== 弹窗逻辑 ==========
  function openShareModal() {
    var modal = document.getElementById('share-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'share-modal';
      modal.className = 'share-modal';
      modal.innerHTML =
        '<div class="share-modal-content">' +
        '<div class="share-modal-header">' +
        '<span class="share-modal-title">分享到微信</span>' +
        '<button class="share-modal-close" id="share-modal-close">&times;</button>' +
        '</div>' +
        '<div class="share-modal-body" id="share-modal-body">' +
        '<div class="share-loading"><span class="share-spinner"></span>正在生成图片...</div>' +
        '</div></div>';
      document.body.appendChild(modal);
      document.getElementById('share-modal-close').addEventListener('click', closeShareModal);
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeShareModal();
      });
    }

    modal.classList.add('active');
    var bodyEl = document.getElementById('share-modal-body');
    bodyEl.innerHTML = '<div class="share-loading"><span class="share-spinner"></span>正在生成图片...</div>';

    setTimeout(function () {
      try {
        if (!currentData) {
          bodyEl.innerHTML = '<p style="color:var(--text-weak)">数据加载中，请稍后重试</p>';
          return;
        }

        var imgDataUrl = generateShareImage(currentData);

        bodyEl.innerHTML =
          '<div class="share-preview-wrap">' +
          '<img src="' + imgDataUrl + '" alt="分享图片" />' +
          '</div>' +
          '<div class="share-actions">' +
          '<button class="share-action-btn share-save-btn" id="share-save-btn">💾 保存图片</button>' +
          '<button class="share-action-btn share-copy-btn" id="share-copy-link">🔗 复制链接</button>' +
          '</div>';

        document.getElementById('share-save-btn').addEventListener('click', function () {
          saveShareImage(imgDataUrl, (currentData.date || '') + '_信息选题.png');
        });
        document.getElementById('share-copy-link').addEventListener('click', copyLink);
      } catch (err) {
        console.error('生成分享图失败:', err);
        bodyEl.innerHTML = '<p style="color:#e0457b">生成失败：' + err.message + '</p>';
      }
    }, 300);
  }

  function closeShareModal() {
    var m = document.getElementById('share-modal');
    if (m) m.classList.remove('active');
  }

  function saveShareImage(dataUrl, filename) {
    var a = document.createElement('a');
    a.href = dataUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function copyLink() {
    var url = currentUrl || location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(function () {
        var btn = document.getElementById('share-copy-link');
        btn.textContent = '✅ 已复制';
        setTimeout(function () { btn.textContent = '🔗 复制链接'; }, 2000);
      });
    } else {
      prompt('复制链接：', url);
    }
  }

  // 初始化
  function init() {
    var shareBtn = document.getElementById('share-btn');
    if (shareBtn) {
      shareBtn.addEventListener('click', function (e) {
        e.preventDefault();
        // 首页：先加载最新一期数据再生成图片
        if (!getDateParam()) {
          loadLatestDataThenShare();
        } else if (currentData) {
          openShareModal();
        } else {
          openShareModal(); // 详情页等数据就绪
        }
      });
    }
    currentUrl = location.href;

    window._onShareDataReady = function (data) {
      currentData = data;
    };

    // 首页预加载最新数据（可选优化）
    if (!getDateParam()) {
      loadLatestDataSilently();
    }
  }

  /** 首页：静默加载最新一期数据 */
  function loadLatestDataSilently() {
    fetchWithTimeout('data/manifest.json', 8000)
      .then(function (r) { return r.json(); })
      .then(function (manifest) {
        var issues = manifest.issues || [];
        if (issues.length > 0) {
          var latestDate = issues[0].date || issues[0];
          return fetchWithTimeout('data/' + latestDate + '.json', 8000);
        }
        throw new Error('无可用期次');
      })
      .then(function (r) { return r.json(); })
      .then(function (data) { currentData = data; })
      .catch(function () {});
  }

  /** 首页：点击转发后加载最新数据并弹窗 */
  function loadLatestDataThenShare() {
    var bodyEl;
    var modal = document.getElementById('share-modal');

    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'share-modal';
      modal.className = 'share-modal';
      modal.innerHTML =
        '<div class="share-modal-content">' +
        '<div class="share-modal-header">' +
        '<span class="share-modal-title">分享到微信</span>' +
        '<button class="share-modal-close" id="share-modal-close">&times;</button>' +
        '</div>' +
        '<div class="share-modal-body" id="share-modal-body">' +
        '<div class="share-loading"><span class="share-spinner"></span>正在加载最新数据...</div>' +
        '</div></div>';
      document.body.appendChild(modal);
      document.getElementById('share-modal-close').addEventListener('click', closeShareModal);
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeShareModal();
      });
    }

    bodyEl = document.getElementById('share-modal-body');
    modal.classList.add('active');
    bodyEl.innerHTML = '<div class="share-loading"><span class="share-spinner"></span>正在加载最新数据...</div>';

    // 如果已有缓存数据，直接用
    if (currentData) {
      renderShareImage(bodyEl, currentData);
      return;
    }

    fetchWithTimeout('data/manifest.json', 10000)
      .then(function (r) { return r.json(); })
      .then(function (manifest) {
        var issues = manifest.issues || [];
        if (issues.length === 0) throw new Error('暂无期次数据');
        var latestDate = issues[0].date || issues[0];
        bodyEl.querySelector('.share-loading').innerHTML =
          '<span class="share-spinner"></span>正在生成分享图...';
        return fetchWithTimeout('data/' + latestDate + '.json', 10000);
      })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        currentData = data;
        renderShareImage(bodyEl, data);
      })
      .catch(function (err) {
        console.error('加载失败:', err);
        bodyEl.innerHTML = '<p style="color:#e0457b">加载失败：' + err.message + '</p>';
      });
  }

  /** 渲染分享图片到弹窗 */
  function renderShareImage(bodyEl, data) {
    try {
      var imgDataUrl = generateShareImage(data);

      bodyEl.innerHTML =
        '<div class="share-preview-wrap">' +
        '<img src="' + imgDataUrl + '" alt="分享图片" />' +
        '</div>' +
        '<div class="share-actions">' +
        '<button class="share-action-btn share-save-btn" id="share-save-btn">💾 保存图片</button>' +
        '<button class="share-action-btn share-copy-btn" id="share-copy-link">🔗 复制链接</button>' +
        '</div>';

      document.getElementById('share-save-btn').addEventListener('click', function () {
        saveShareImage(imgDataUrl, (data.date || '') + '_信息选题.png');
      });
      document.getElementById('share-copy-link').addEventListener('click', copyLink);
    } catch (err) {
      console.error('生成失败:', err);
      bodyEl.innerHTML = '<p style="color:#e0457b">生成失败：' + err.message + '</p>';
    }
  }

  /** 带超时的 fetch（复用） */
  function fetchWithTimeout(url, timeout) {
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () {
        reject(new Error('加载超时'));
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
