/**
 * 分享生图功能 - 完全重构版
 * 策略：先纯测量（不绘制）算出精确高度，再二次绘制
 * 特性：measureText 自动换行、二维码纳入高度计算、1080px 高清导出
 */
(function () {
  var currentData = null;
  var currentUrl  = '';

  /* ============================================================
   *  工具函数
   * ============================================================ */

  function getDateParam() {
    var m = new RegExp('[?&]date=([^&]+)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function truncate(text, max) {
    if (!text) return '';
    return text.length <= max ? text : text.substring(0, max) + '...';
  }

  /** 圆角矩形路径 */
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

  /**
   * 用 measureText 将文本自动换行（逐字符测量，支持中文）
   * @param {CanvasRenderingContext2D} ctx - 已设置好 font 的 context
   * @param {string} text - 原文
   * @param {number} maxWidth - 最大行宽（px）
   * @returns {string[]} 各行文字
   */
  function autoWrap(ctx, text, maxWidth) {
    var lines = [];
    var paras = (text || '').split('\n');
    for (var p = 0; p < paras.length; p++) {
      var chars = paras[p].split('');
      var line  = '';
      for (var i = 0; i < chars.length; i++) {
        var test = line + chars[i];
        if (ctx.measureText(test).width > maxWidth && line !== '') {
          lines.push(line);
          line = chars[i];
        } else {
          line = test;
        }
      }
      if (line) lines.push(line);
    }
    return lines;
  }

  /* ============================================================
   *  二维码生成（简化版，仅用于演示；生产环境建议用 qrcode.js）
   * ============================================================ */
  function generateQRCode(text, size) {
    var canvas = document.createElement('canvas');
    canvas.width  = size;
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
    var N = 17;                       // 17×17 模块
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
    var area   = size - margin * 2;
    var cell   = area / N;

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
            margin + col * cell,
            margin + row * cell,
            Math.max(1, cell - 1),
            Math.max(1, cell - 1)
          );
        }
      }
    }
    return canvas;
  }

  /* ============================================================
   *  主函数：生成分享图（两遍渲染）
   * ============================================================ */
  function generateShareImage(data) {
    var dateStr = data.date || getDateParam();
    var clues  = data.clues || [];
    var stats  = data.stats || {};

    /* ---- 常量（高清 1080px，所有尺寸 ×1.44）---- */
    var SCALE = 1.44;                  // 750 → 1080
    var W      = Math.round(750 * SCALE);   // 1080
    var PX     = Math.round(48  * SCALE);   // ~69
    var CONTENT_W = W - PX * 2;

    var HDR_H  = Math.round(110 * SCALE);  // ~158
    var FTR_H  = Math.round(160 * SCALE);  // ~230（底部蓝色区高度）
    var QR_SZ = Math.round(100 * SCALE);  // ~144（二维码尺寸）

    /* ---- 临时 Canvas 用于测量 ---- */
    var measureCanvas = document.createElement('canvas');
    measureCanvas.width  = W;
    measureCanvas.height = 2000;
    var mctx = measureCanvas.getContext('2d');

    /* ---- 测量每类文字的行高（基于实际 font）---- */
    function getLineH(fontSize) {
      mctx.font = 'bold ' + fontSize + 'px "PingFang SC","Microsoft YaHei",sans-serif';
      // 中文字体实际像素高度 ≈ fontSize × 1.35
      return Math.ceil(fontSize * 1.38);
    }

    var lhTitle   = getLineH(Math.round(23 * SCALE)); // 标题行高
    var lhSummary = getLineH(Math.round(18 * SCALE)); // 摘要行高

    /* ---- 第一遍：纯测量，计算每条线索占用高度 & 总画布高度 ---- */
    var clueMeasurements = [];   // [{titleLines, summaryLines, blockH}, ...]
    var totalCluesH = 0;
    var MAX_SHOW = Math.min(clues.length, 5);

    for (var ci = 0; ci < MAX_SHOW; ci++) {
      var cl = clues[ci];
      if (!cl) continue;

      // 测量标题（加粗，最多2行）
      mctx.font = 'bold ' + Math.round(23 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
      var titleFull = (ci + 1) + '. ' + (cl.title || '');
      var titleLines = autoWrap(mctx, titleFull, CONTENT_W);
      if (titleLines.length > 2) titleLines = titleLines.slice(0, 2);

      // 测量摘要（普通，最多2行）
      mctx.font = Math.round(18 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
      var sumFull = truncate((cl.summary || '').replace(/\s+/g, ' '), 60);
      var summaryLines = autoWrap(mctx, sumFull, CONTENT_W - Math.round(14 * SCALE));
      if (summaryLines.length > 2) summaryLines = summaryLines.slice(0, 2);

      var blockH =
        titleLines.length * lhTitle +      // 标题总高
        Math.round(18 * SCALE) +             // 标题→摘要间距
        summaryLines.length * lhSummary +   // 摘要总高
        Math.round(56 * SCALE);             // 下间距（线索之间）

      clueMeasurements.push({
        titleLines:   titleLines,
        summaryLines: summaryLines,
        blockH:        blockH
      });
      totalCluesH += blockH;
    }

    // "还有更多"提示行高度
    var moreH = 0;
    if (clues.length > MAX_SHOW) {
      moreH = Math.round(20 * SCALE) + Math.round(36 * SCALE); // 上间距 + 文字行高
    }

    // 二维码区域实际占用高度（在白色内容区内，距蓝色条上方 32px）
    var qrAreaH = QR_SZ + Math.round(32 * SCALE) + Math.round(20 * SCALE); // 二维码 + 上间距 + 提示文字

    // ---- 总画布高度（动态计算！）----
    var H =
      HDR_H +                                   // 头部蓝色区
      Math.round(20  * SCALE) +                 // 头部下空白
      Math.round(38  * SCALE) +                 // "本期数据" 标题
      Math.round(44  * SCALE) +                 // 统计文字
      Math.round(20  * SCALE) +                 // 分隔线上方
      2 +                                        // 分隔线
      Math.round(18  * SCALE) +                 // 分隔线下方
      Math.round(36  * SCALE) +                 // "今日热点" 标题
      Math.round(16  * SCALE) +                 // 标题下空白
      totalCluesH +                             // 所有线索总高
      moreH +                                  // "还有更多"提示
      Math.round(32  * SCALE) +                 // 线索区→二维码区间距
      qrAreaH +                                // 二维码区域高度（纳入总高！）
      Math.round(24  * SCALE) +                 // 二维码→底部蓝色区间距
      FTR_H;                                   // 底部蓝色区

    /* ---- 第二遍：正式绘制 ---- */
    var canvas = document.createElement('canvas');
    canvas.width  = W;
    canvas.height = H;
    var ctx = canvas.getContext('2d');

    // === 白色背景 ===
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, H);

    // === 头部蓝色渐变（底边圆角）===
    var gradTop = ctx.createLinearGradient(0, 0, W, 0);
    gradTop.addColorStop(0, '#1664ff');
    gradTop.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradTop;
    roundRect(ctx, 0, 0, W, HDR_H, { br: Math.round(18 * SCALE), bl: Math.round(18 * SCALE) });
    ctx.fill();

    ctx.textAlign    = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold ' + Math.round(32 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillText('信息选题参考', W / 2, HDR_H * 0.38);
    ctx.font = Math.round(20 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillText(formatChineseDate(dateStr, data.weekday), W / 2, HDR_H * 0.72);

    // === 数据统计 ===
    var y = HDR_H + Math.round(20 * SCALE) + Math.round(36 * SCALE);
    ctx.textAlign    = 'left';
    ctx.textBaseline = 'alphabetic';

    ctx.font = 'bold ' + Math.round(24 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('📊 本期数据', PX, y);

    y += Math.round(42 * SCALE);
    ctx.font = Math.round(20 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = '#333333';
    var parts = [];
    if (stats.total)    parts.push('筛选资讯 ' + stats.total + ' 条');
    if (stats.selected) parts.push('相关内容 ' + stats.selected + ' 条');
    if (stats.clues)    parts.push('聚合线索 ' + stats.clues + ' 条');
    ctx.fillText(parts.join('  |  '), PX, y);

    // === 分隔线 ===
    y += Math.round(28 * SCALE);
    ctx.strokeStyle = '#e5e6eb';
    ctx.lineWidth   = 1;
    ctx.beginPath();
    ctx.moveTo(PX, y);
    ctx.lineTo(W - PX, y);
    ctx.stroke();

    // === 今日热点标题 ===
    y += Math.round(34 * SCALE);
    ctx.font = 'bold ' + Math.round(24 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('🔥 今日热点', PX, y);

    // === 线索列表（用测量好的 titleLines / summaryLines 绘制）===
    y += Math.round(42 * SCALE);

    for (var c = 0; c < clueMeasurements.length; c++) {
      var m = clueMeasurements[c];

      // 标题（自动换行，最多2行）
      ctx.font = 'bold ' + Math.round(23 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
      ctx.fillStyle = '#1d2129';
      for (var tl = 0; tl < m.titleLines.length; tl++) {
        ctx.fillText(m.titleLines[tl], PX, y);
        y += lhTitle;
      }

      // 摘要（自动换行，最多2行，缩进）
      y += Math.round(18 * SCALE); // 标题→摘要间距
      ctx.font = Math.round(18 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
      ctx.fillStyle = '#555555';
      for (var sl = 0; sl < m.summaryLines.length; sl++) {
        ctx.fillText(m.summaryLines[sl], PX + Math.round(14 * SCALE), y);
        y += lhSummary;
      }

      y += Math.round(56 * SCALE); // 下间距
    }

    // "还有更多"提示
    if (clues.length > MAX_SHOW) {
      y += Math.round(20 * SCALE);
      ctx.font = Math.round(17 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
      ctx.fillStyle = '#86909c';
      ctx.fillText(
        '... 还有 ' + (clues.length - MAX_SHOW) + ' 条线索，扫码查看完整版',
        PX, y
      );
      y += Math.round(36 * SCALE);
    }

    // === 二维码区域（纳入高度计算，绝不被裁切）===
    y += Math.round(32 * SCALE); // 线索区→二维码间距

    var qrX = W - PX - QR_SZ;
    var qrY = y;

    var qrCanvas = generateQRCode(currentUrl, QR_SZ);
    ctx.drawImage(qrCanvas, qrX, qrY, QR_SZ, QR_SZ);

    // 扫码提示
    ctx.font = Math.round(13 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = '#86909c';
    ctx.textAlign = 'center';
    ctx.fillText('扫码查看完整', qrX + QR_SZ / 2, qrY + QR_SZ + Math.round(20 * SCALE));

    y += qrAreaH;

    // === 底部蓝色区（顶边圆角）===
    var bottomY = H - FTR_H;
    var gradBot = ctx.createLinearGradient(0, bottomY, W, bottomY);
    gradBot.addColorStop(0, '#1664ff');
    gradBot.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradBot;
    roundRect(ctx, 0, bottomY, W, FTR_H, { tr: Math.round(18 * SCALE), tl: Math.round(18 * SCALE) });
    ctx.fill();

    // 底部左侧：网站信息
    ctx.textAlign    = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold ' + Math.round(20 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.fillText('信息选题日报', PX, bottomY + Math.round(52 * SCALE));
    ctx.font = Math.round(15 * SCALE) + 'px "PingFang SC","Microsoft YaHei",sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.fillText('dailyinfox.cn', PX, bottomY + Math.round(82 * SCALE));

    // 导出为高清 PNG（缩小到 540px 宽方便分享）
    var exportCanvas = document.createElement('canvas');
    exportCanvas.width  = 540;
    exportCanvas.height = Math.round(H * 540 / W);
    var ectx = exportCanvas.getContext('2d');
    ectx.drawImage(canvas, 0, 0, exportCanvas.width, exportCanvas.height);
    return exportCanvas.toDataURL('image/png', 1.0);
  }

  /* ============================================================
   *  弹窗逻辑
   * ============================================================ */
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
        console.error('生成分享图失败:', err);
        bodyEl.innerHTML = '<p style="color:#e0457b;padding:28px;text-align:center;">生成失败：' + err.message + '</p>';
      }
    }, 500);
  }

  function closeShareModal() {
    var m = document.getElementById('share-modal');
    if (m) m.classList.remove('active');
  }

  function saveImg(url, name) {
    var a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  function copyLink() {
    var u = currentUrl || location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(u).then(function () {
        var b = document.getElementById('share-copy-link');
        if (b) {
          b.textContent = '✅ 已复制';
          setTimeout(function () { b.textContent = '🔗 复制链接'; }, 2000);
        }
      });
    } else {
      prompt('复制链接：', u);
    }
  }

  /* ============================================================
   *  初始化
   * ============================================================ */
  function init() {
    var btn = document.getElementById('share-btn');
    if (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        openShareModal();
      });
    }
    currentUrl = location.href;
    window._onShareDataReady = function (d) {
      currentData = d;
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
