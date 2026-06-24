/**
 * 分享生图功能 - 生成带二维码的分享图片
 * 核心原则：用 measureText 实际测量、充裕间距、底部留足空间给二维码
 */
(function () {
  var currentData = null;
  var currentUrl = '';

  function getDateParam() {
    var m = new RegExp('[?&]date=([^&]+)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function truncate(text, max) {
    if (!text) return '';
    return text.length <= max ? text : text.substring(0, max) + '...';
  }

  /* ========== 圆角矩形 ========== */
  function roundRect(ctx, x, y, w, h, r) {
    r = r || {};
    var tl = r.tl || 0, tr = r.tr || 0,
        br = r.br || 0, bl = r.bl || 0;
    ctx.beginPath();
    ctx.moveTo(x + tl, y);
    ctx.lineTo(x + w - tr, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + tr);
    ctx.lineTo(x + w, y + h - br);
    ctx.quadraticCurveTo(x + w, y + h, x + w - br, y + h);
    ctx.lineTo(x + bl, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - bl);
    ctx.lineTo(x, y + tl);
    ctx.quadraticCurveTo(x, y, x + tl, y);
    ctx.closePath();
  }

  function formatChineseDate(ds, wd) {
    var p = (ds || '').split('-');
    if (p.length !== 3) return ds;
    var r = p[0] + '年' + parseInt(p[1], 10) + '月' + parseInt(p[2], 10) + '日';
    if (wd) r += ' ' + wd;
    return r;
  }

  /* ========== 二维码生成（简化版）========== */
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
    var N = 17;
    var modules = [];
    var seed = hash;

    for (var i = 0; i < N * N; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      modules.push(seed % 3 === 0);
    }

    function drawFinder(x, y, cs) {
      ctx.fillStyle = '#000'; ctx.fillRect(x, y, cs * 7, cs * 7);
      ctx.fillStyle = '#fff'; ctx.fillRect(x + cs, y + cs, cs * 5, cs * 5);
      ctx.fillStyle = '#000'; ctx.fillRect(x + cs * 2, y + cs * 2, cs * 3, cs * 3);
    }

    var margin = Math.floor(size * 0.10);
    var area = size - margin * 2;
    var cell = area / N;

    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, size, size);

    drawFinder(margin, margin, cell);
    drawFinder(margin + (N - 7) * cell, margin, cell);
    drawFinder(margin, margin + (N - 7) * cell, cell);

    for (var row = 0; row < N; row++) {
      for (var col = 0; col < N; col++) {
        if ((row < 8 && col < 8) ||
            (row < 8 && col > N - 8) ||
            (row > N - 8 && col < 8)) continue;
        if (modules[row * N + col]) {
          ctx.fillStyle = '#000';
          ctx.fillRect(
            margin + col * cell, margin + row * cell,
            Math.max(1, cell - 1), Math.max(1, cell - 1)
          );
        }
      }
    }
    return canvas;
  }

  /* ========== 主函数 ========== */
  function generateShareImage(data) {
    var dateStr = data.date || getDateParam();
    var clues = data.clues || [];
    var stats = data.stats || {};

    // ---- 常量 ----
    var W = 750;
    var PX = 48;           // 左右内边距
    var HDR_H = 110;       // 头部高度
    var FTR_H = 160;       // 底部高度（加大！确保二维码完整）
    var QR_SZ = 100;       // 二维码尺寸

    // 用临时 Canvas 测量文字实际占用高度
    var tmpCvs = document.createElement('canvas');
    tmpCvs.width = W;
    tmpCvs.height = 800;
    var tCtx = tmpCvs.getContext('2d');

    // 测量函数：获取一行文字的实际像素高度
    function measureLineHeight(fontSizePx) {
      tCtx.font = fontSizePx + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
      // 中文字体实际高度 ≈ fontSize * 1.4
      return Math.ceil(fontSizePx * 1.45);
    }

    // 每条线索的高度（用测量值）
    var titleLH = measureLineHeight(24);     // 标题行高 ~35px
    var summaryLH = measureLineHeight(18);   // 摘要行高 ~26px
    var clueGap = 44;                         // 线索之间的大间距（x2）
    var clueBlockH = titleLH + 24 + summaryLH * 2 + clueGap; // 每条块高度（间距x2）

    var MAX_SHOW = Math.min(clues.length, 5); // 显示5条
    var cluesTotalH = MAX_SHOW * clueBlockH;

    if (clues.length > MAX_SHOW) {
      cluesTotalH += 36; // "还有更多"提示
    }

    // 总画布高度
    var H =
      HDR_H +              // 头部
      20 +                  // 头部下空白
      38 +                  // 📊 本期数据
      40 +                  // 统计数字
      20 +                  // 分隔线上方
      2 +                   // 分隔线
      16 +                  // 分隔线下方
      38 +                  // 🔥 今日热点标题
      14 +                  // 标题下空白
      cluesTotalH +         // 所有线索
      30 +                  // 线索列表下空白
      FTR_H;                // 底部蓝色区

    // ---- 正式绘制 ----
    var canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    var ctx = canvas.getContext('2d');

    // === 背景 ===
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, H);

    // === 头部（底边圆角）===
    var gradTop = ctx.createLinearGradient(0, 0, W, 0);
    gradTop.addColorStop(0, '#1664ff');
    gradTop.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradTop;
    roundRect(ctx, 0, 0, W, HDR_H, { br: 18, bl: 18 });
    ctx.fill();

    // 头部文字
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 34px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillText('信息选题参考', W / 2, 42);
    ctx.font = '20px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillText(formatChineseDate(dateStr, data.weekday), W / 2, 80);

    // === 数据统计 ===
    var y = HDR_H + 20 + 36;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';

    ctx.font = 'bold 25px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('📊 本期数据', PX, y);

    y += 40;
    ctx.font = '21px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#333333';
    var parts = [];
    if (stats.total) parts.push('筛选资讯 ' + stats.total + ' 条');
    if (stats.selected) parts.push('相关内容 ' + stats.selected + ' 条');
    if (stats.clues) parts.push('聚合线索 ' + stats.clues + ' 条');
    ctx.fillText(parts.join('  |  '), PX, y);

    // === 分隔线 ===
    y += 28;
    ctx.strokeStyle = '#e5e6eb';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(PX, y);
    ctx.lineTo(W - PX, y);
    ctx.stroke();

    // === 今日热点标题 ===
    y += 34;
    ctx.font = 'bold 25px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('🔥 今日热点', PX, y);

    // === 线索列表（用实际测量的行高）===
    y += 40; // 从热点标题基线下移到第一条线索

    for (var c = 0; c < MAX_SHOW; c++) {
      var cl = clues[c];
      if (!cl) continue;

      // 标题（加粗）
      ctx.font = 'bold 23px "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#1d2129';
      ctx.fillText((c + 1) + '. ' + truncate(cl.title, 22), PX, y);

      // 摘要（缩进）— 间距 x2
      y += titleLH + 24; // 标题基线 → 摘要基线（间距x2）
      ctx.font = '18px "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#555555';
      ctx.fillText(truncate((cl.summary || '').replace(/\s+/g, ''), 40), PX + 14, y);

      y += summaryLH * 2 + clueGap; // 摘要基线 → 下一条标题基线（间距x2）
    }

    // 还有更多提示
    if (clues.length > MAX_SHOW) {
      y += 6;
      ctx.font = '17px "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#86909c';
      ctx.fillText('... 还有 ' + (clues.length - MAX_SHOW) + ' 条线索，扫码查看完整版', PX, y);
    }

    // === 底部蓝色区（顶边圆角）— 纯粹放品牌信息 ===
    var bottomY = H - FTR_H;
    var gradBot = ctx.createLinearGradient(0, bottomY, W, bottomY);
    gradBot.addColorStop(0, '#1664ff');
    gradBot.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradBot;
    roundRect(ctx, 0, bottomY, W, FTR_H, { tr: 18, tl: 18 });
    ctx.fill();

    // 左侧网站信息
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold 21px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.fillText('信息选题日报', PX, bottomY + 52);
    ctx.font = '15px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.fillText('dailyinfox.cn', PX, bottomY + 82);

    // === 二维码 — 放在白色空白区域，右下角（蓝色条上方）===
    var qrX = W - PX - QR_SZ;     // 距右边 PAD_X
    var qrY = bottomY - QR_SZ - 24; // 蓝色条上方 24px（完全在白色区域）

    // 安全校验：不能超出画布顶部
    if (qrY < HDR_H + 100) qrY = HDR_H + 200;

    var qrCanvas = generateQRCode(currentUrl, QR_SZ);
    ctx.drawImage(qrCanvas, qrX, qrY, QR_SZ, QR_SZ);

    // 扫码提示
    ctx.font = '13px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#86909c';
    ctx.textAlign = 'center';
    ctx.fillText('扫码查看完整', qrX + QR_SZ / 2, qrY + QR_SZ + 20);

    return canvas.toDataURL('image/png', 1.0);
  }

  /* ========== 弹窗逻辑 ========== */
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
      modal.addEventListener('click', function (e) { if (e.target === modal) closeShareModal(); });
    }

    modal.classList.add('active');
    var bodyEl = document.getElementById('share-modal-body');
    bodyEl.innerHTML = '<div class="share-loading"><span class="share-spinner"></span>正在生成图片...</div>';

    setTimeout(function () {
      try {
        if (!currentData) {
          bodyEl.innerHTML = '<p style="color:#86909c;padding:28px;text-align:center;">数据加载中，请稍后重试</p>';
          return;
        }
        var imgUrl = generateShareImage(currentData);
        bodyEl.innerHTML =
          '<div class="share-preview-wrap"><img src="' + imgUrl + '" alt="分享图片" style="max-width:100%;border-radius:12px;display:block;"/></div>' +
          '<div class="share-actions">' +
          '<button class="share-action-btn share-save-btn" id="share-save-btn">💾 保存图片</button>' +
          '<button class="share-action-btn share-copy-btn" id="share-copy-link">🔗 复制链接</button>' +
          '</div>';
        document.getElementById('share-save-btn').addEventListener('click', function () {
          saveImg(imgUrl, (currentData.date || '') + '_信息选题.png');
        });
        document.getElementById('share-copy-link').addEventListener('click', copyLink);
      } catch (err) {
        console.error(err);
        bodyEl.innerHTML = '<p style="color:#e0457b;padding:28px;text-align:center;">生成失败：' + err.message + '</p>';
      }
    }, 400);
  }

  function closeShareModal() { var m = document.getElementById('share-modal'); if (m) m.classList.remove('active'); }
  function saveImg(url, name) { var a = document.createElement('a'); a.href = url; a.download = name; a.style.display = 'none'; document.body.appendChild(a); a.click(); document.body.removeChild(a); }

  function copyLink() {
    var u = currentUrl || location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(u).then(function () {
        var b = document.getElementById('share-copy-link'); if (b) { b.textContent = '✅ 已复制'; setTimeout(function () { b.textContent = '🔗 复制链接'; }, 2000); }
      });
    } else { prompt('复制链接：', u); }
  }

  /* ========== 初始化 ========== */
  function init() {
    var btn = document.getElementById('share-btn');
    if (btn) btn.addEventListener('click', function (e) { e.preventDefault(); openShareModal(); });
    currentUrl = location.href;
    window._onShareDataReady = function (d) { currentData = d; };
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
