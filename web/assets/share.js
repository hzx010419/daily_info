/**
 * 分享生图 - 信息日报卡片版 v3
 * 内容：蓝色头部 + 数据统计 + 线索列表 + 真实二维码 + 蓝色底部
 * 风格：简洁现代卡片风格
 */
(function () {
  var currentData = null;
  var currentUrl = '';

  // 设计基准宽度 750，导出时缩放为高清
  var W = 750;
  var PX = 48;           // 左右内边距
  var HDR_H = 75;        // 蓝色头部高度
  var FTR_H = 75;        // 底部蓝色区高度
  var QR_SIZE = 170;     // 二维码尺寸
  var MAX_CLUE = 5;      // 最多显示几条线索

  // 字号定义
  var FS_TITLE = 32;     // 头部标题
  var FS_SUBTITLE = 20;  // 头部日期
  var FS_SECTION = 26;   // 区块标题（数据统计/今日热点）
  var FS_STATS = 24;     // 统计数字
  var FS_CLUE_T = 28;    // 线索标题
  var FS_CLUE_S = 22;    // 线索摘要
  var FS_HINT = 18;      // 提示文字
  var FS_FTR_TITLE = 22; // 底部标题
  var FS_FTR_URL = 16;   // 底部网址
  var FS_QR_TIP = 15;    // 二维码提示文字
  var CLUE_BLOCK_H = 100;// 每条线索固定区块高度

  function truncate(text, max) {
    if (!text) return '';
    return text.length <= max ? text : text.substring(0, max) + '...';
  }

  function formatChineseDate(ds, wd) {
    var p = (ds || '').split('-');
    if (p.length !== 3) return ds;
    return p[0] + '年' + parseInt(p[1], 10) + '月' + parseInt(p[2], 10) + '日' + (wd ? ' ' + wd : '');
  }

  /**
   * 文字自动换行，返回行数组
   */
  function wrapText(ctx, text, maxWidth) {
    if (!text) return [];
    var lines = [], paraList = text.split('\n');
    for (var pi = 0; pi < paraList.length; pi++) {
      var line = '', para = paraList[pi];
      if (para === '') { lines.push(''); continue; }
      for (var ci = 0; ci < para.length; ci++) {
        var ch = para[ci], test = line + ch;
        if (ctx.measureText(test).width > maxWidth && line !== '') { lines.push(line); line = ch; }
        else { line = test; }
      }
      if (line) lines.push(line);
    }
    return lines;
  }

  function roundRectPath(ctx, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y); ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  // ==================== 二维码生成 ====================

  function generateQRCanvas(text, size) {
    return new Promise(function (resolve) {
      if (!window.QRCode) { resolve(null); return; }
      try {
        var container = document.createElement('div');
        document.body.appendChild(container);
        var qrcode = new QRCode(container, {
          text: text,
          width: size, height: size,
          colorDark: '#111', colorLight: '#ffffff',
          correctLevel: window.QRCode.CorrectLevel.M,
          useSVG: false
        });
        setTimeout(function () {
          try {
            var qrEl = container.querySelector('canvas') || container.querySelector('img');
            if (!qrEl) { document.body.removeChild(container); resolve(null); return; }
            var clone = document.createElement('canvas');
            clone.width = size; clone.height = size;
            clone.getContext('2d').drawImage(qrEl, 0, 0, size, size);
            document.body.removeChild(container);
            resolve(clone);
          } catch (e) { document.body.removeChild(container); resolve(null); }
        }, 80);
      } catch (e) { resolve(null); }
    });
  }

  function drawPlaceholderQR(ctx, x, y, size) {
    var c = document.createElement('canvas'); c.width = size; c.height = size;
    var cx = c.getContext('2d'), hash = 0, txt = currentUrl || 'dailyinfox.cn';
    for (var i = 0; i < txt.length; i++) hash = ((hash << 5) - hash + txt.charCodeAt(i)) & 0x7fffffff;
    var N = 21, mods = [], seed = hash;
    for (var j = 0; j < N * N; j++) { seed = (seed * 1103515245 + 12345) & 0x7fffffff; mods.push(seed % 3 === 0); }
    function df(px, py, cs) { cx.fillStyle='#000';cx.fillRect(px,py,cs*7,cs*7);cx.fillStyle='#fff';cx.fillRect(px+cs,py+cs,cs*5,cs*5);cx.fillStyle='#000';cx.fillRect(px+cs*2,py+cs*2,cs*3,cs*3); }
    var mg = Math.floor(size * 0.08), area = size - mg * 2, cs = area / N;
    cx.fillStyle = '#fff'; cx.fillRect(0, 0, size, size);
    df(mg, mg, cs); df(mg + (N - 7) * cs, mg, cs); df(mg, mg + (N - 7) * cs, cs);
    for (var r = 0; r < N; r++)
      for (var col = 0; col < N; col++) {
        if ((r < 8 && col < 8) || (r < 8 && col > N - 9) || (r > N - 9 && col < 8)) continue;
        if (mods[r * N + col]) { cx.fillStyle = '#222'; cx.fillRect(mg + col * cs, mg + r * cs, Math.max(1, cs - 1), Math.max(1, cs - 1)); }
      }
    ctx.drawImage(c, x, y, size, size);
  }

  // ==================== 主绘图 ====================

  function generateImage(data) {
    var dateStr = data.date || '';
    var weekday = data.weekday || '';
    var clues = data.clues || [];
    var stats = data.stats || {};

    var qrSize = QR_SIZE;

    // 计算总高度（上下白边已缩小一半）
    var contentH = MAX_CLUE * CLUE_BLOCK_H;
    var extraHintH = (clues.length > MAX_CLUE) ? 50 : 20;
    var H = HDR_H + 15 + 45 + 40 + 34 + 50 + contentH + extraHintH + 15 + qrSize + 18 + FTR_H;

    // 先异步生成二维码
    return generateQRCanvas(currentUrl, qrSize).then(function (qrCanvas) {
      var canvas = document.createElement('canvas');
      canvas.width = W;
      canvas.height = H;
      var ctx = canvas.getContext('2d');

      // ===== 白色背景 =====
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, W, H);

      // ===== 蓝色渐变头部 =====
      var gTop = ctx.createLinearGradient(0, 0, W, 0);
      gTop.addColorStop(0, '#1664ff'); gTop.addColorStop(1, '#0a3fbf');
      ctx.fillStyle = gTop;
      roundRectPath(ctx, 0, 0, W, HDR_H, { br: 18, bl: 18 });
      ctx.fill();

      // 标题
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.font = 'bold ' + FS_TITLE + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#fff';
      ctx.fillText('信息选题参考', W / 2, HDR_H * 0.35);

      // 日期
      ctx.font = FS_SUBTITLE + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.85)';
      ctx.fillText(formatChineseDate(dateStr, weekday), W / 2, HDR_H * 0.68);

      var y = HDR_H + 15;

      // ===== 数据统计区块 =====
      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      ctx.font = 'bold ' + FS_SECTION + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#1664ff';
      ctx.fillText('\uD83D\uDCCA 本期信息', PX, y);

      y += 42;
      ctx.font = FS_STATS + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#333';
      var parts = [];
      if (stats.total) parts.push('筛选资讯 ' + stats.total + ' 条');
      if (stats.selected) parts.push('相关内容 ' + stats.selected + ' 条');
      if (stats.clues) parts.push('聚合线索 ' + stats.clues + ' 条');
      ctx.fillText(parts.join('   |   '), PX, y);

      // 分隔线
      y += 36;
      ctx.strokeStyle = '#e5e6eb'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(PX, y); ctx.lineTo(W - PX, y); ctx.stroke();

      // ===== 今日热点区块 =====
      y += 38;
      ctx.font = 'bold ' + FS_SECTION + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#1664ff';
      ctx.fillText('\uD83D\uDD25 今日热点', PX, y);

      // 线索列表
      y += 52;
      var showCount = Math.min(clues.length, MAX_CLUE);
      for (var i = 0; i < showCount; i++) {
        var cl = clues[i];
        if (!cl) continue;

        // 编号 + 标题（粗体）
        ctx.font = 'bold ' + FS_CLUE_T + 'px "PingFang SC", sans-serif';
        ctx.fillStyle = '#1d2129';
        ctx.fillText((i + 1) + '. ' + truncate(cl.title, 22), PX, y);

        // 摘要（最多 2 行截断）
        var sumText = cl.summary || '';
        var sumLine1 = truncate(sumText, 28);
        var sumLine2 = truncate((sumText || '').slice(28), 28);

        y += 36;
        ctx.font = FS_CLUE_S + 'px "PingFang SC", sans-serif';
        ctx.fillStyle = '#555';
        ctx.fillText(sumLine1, PX + 20, y);

        if (sumLine2) {
          y += 28;
          ctx.fillText(sumLine2, PX + 20, y);
          y += 36;
        } else {
          y += 64;
        }
      }

      // 还有更多提示
      if (clues.length > MAX_CLUE) {
        y += 12;
        ctx.font = FS_HINT + 'px "PingFang SC", sans-serif';
        ctx.fillStyle = '#86909c';
        ctx.fillText('... 还有 ' + (clues.length - MAX_CLUE) + ' 条线索，扫码查看完整版', PX, y);
        y += 44;
      } else {
        y += 14;
      }

      // ===== 二维码区域（右侧对齐） =====
      y += 15;
      var qrX = W - PX - qrSize;
      var qrY = y;
      // 安全校验：二维码不能进入底部蓝色区
      if (qrY + qrSize > H - FTR_H - 20) {
        qrY = H - FTR_H - qrSize - 40;
      }

      // 白底圆角容器
      roundRectPath(ctx, qrX - 6, qrY - 6, qrSize + 12, qrSize + 12, 12);
      ctx.fillStyle = '#f8f8f8'; ctx.fill();

      if (qrCanvas) {
        ctx.drawImage(qrCanvas, qrX, qrY, qrSize, qrSize);
      } else {
        drawPlaceholderQR(ctx, qrX, qrY, qrSize);
      }

      // 扫码提示文字
      ctx.font = FS_QR_TIP + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#86909c';
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText('扫码查看完整资讯', qrX + qrSize / 2, qrY + qrSize + 20);

      // ===== 底部蓝色渐变区 =====
      var botY = H - FTR_H;
      var gBot = ctx.createLinearGradient(0, botY, W, botY);
      gBot.addColorStop(0, '#1664ff'); gBot.addColorStop(1, '#0a3fbf');
      ctx.fillStyle = gBot;
      roundRectPath(ctx, 0, botY, W, FTR_H, { tr: 18, tl: 18 });
      ctx.fill();

      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      ctx.font = 'bold ' + FS_FTR_TITLE + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#fff';
      ctx.fillText('信息选题日报', PX, botY + 28);

      ctx.font = FS_FTR_URL + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.72)';
      ctx.fillText('dailyinfox.cn', PX, botY + 50);

      // 导出 2x 高清图
      var outW = Math.round(W * 0.72);
      var outH = Math.round(H * 0.72);
      var out = document.createElement('canvas');
      out.width = outW; out.height = outH;
      out.getContext('2d').drawImage(canvas, 0, 0, outW, outH);
      // 导出为 JPG（微信转发可直接显示图片预览）
      var jpgCanvas = document.createElement('canvas');
      jpgCanvas.width = outW; jpgCanvas.height = outH;
      var jpgCtx = jpgCanvas.getContext('2d');
      jpgCtx.fillStyle = '#fff';
      jpgCtx.fillRect(0, 0, outW, outH);
      jpgCtx.drawImage(out, 0, 0);
      return jpgCanvas.toDataURL('image/jpeg', 0.92);
    });
  }

  // ==================== 弹窗逻辑 ====================

  function openModal() {
    var modal = document.getElementById('share-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'share-modal'; modal.className = 'share-modal';
      modal.innerHTML =
        '<div class="share-modal-content">' +
          '<div class="share-modal-header"><span class="share-modal-title">生成分享卡片</span>' +
          '<button class="share-modal-close" id="share-modal-close">&times;</button></div>' +
          '<div class="share-modal-body" id="share-modal-body">' +
            '<div class="share-loading"><span class="share-spinner"></span>正在生成图片...</div>' +
          '</div></div>';
      document.body.appendChild(modal);
      document.getElementById('share-modal-close').onclick = closeModal;
      modal.onclick = function (e) { if (e.target === modal) closeModal(); };
    }
    modal.classList.add('active');
    document.getElementById('share-modal-body').innerHTML =
      '<div class="share-loading"><span class="share-spinner"></span>正在生成图片...</div>';

    setTimeout(function () {
      if (!currentData) {
        document.getElementById('share-modal-body').innerHTML =
          '<p style="color:#86909c;padding:40px 20px;text-align:center">数据加载中，请稍后重试</p>';
        return;
      }
      generateImage(currentData).then(function (url) {
        document.getElementById('share-modal-body').innerHTML =
          '<div class="share-preview-wrap"><img src="' + url + '" alt="分享卡片" style="width:100%;border-radius:12px;display:block"></div>' +
          '<div class="share-actions">' +
            '<button class="share-action-btn share-save-btn" id="share-save-btn">💾 保存图片</button>' +
            '<button class="share-action-btn share-copy-btn" id="share-copy-link">🔗 复制链接</button>' +
          '</div>';
        document.getElementById('share-save-btn').onclick = function () {
          var a = document.createElement('a');
          a.href = url;
          a.download = (currentData.date || '') + '_信息选题.jpg';
          a.click();
        };
        document.getElementById('share-copy-link').onclick = function () {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(currentUrl).then(function () {
              var btn = document.getElementById('share-copy-link');
              btn.textContent = '✅ 已复制';
              setTimeout(function () { btn.textContent = '🔗 复制链接'; }, 2000);
            });
          } else { prompt('复制链接：', currentUrl); }
        };
      }).catch(function (e) {
        console.error('[ShareCard]', e);
        document.getElementById('share-modal-body').innerHTML =
          '<p style="color:#e0457b;padding:40px 20px;text-align:center">生成失败：' + e.message + '</p>';
      });
    }, 150);
  }

  function closeModal() {
    var m = document.getElementById('share-modal');
    if (m) m.classList.remove('active');
  }

  // ==================== 初始化 ====================
  function init() {
    var btn = document.getElementById('share-btn');
    if (btn) btn.onclick = function (e) { e.preventDefault(); e.stopPropagation(); openModal(); };
    currentUrl = location.href;
    window._onShareDataReady = function (d) { currentData = d; };
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
