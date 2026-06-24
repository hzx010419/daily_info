/**
 * 分享生图 - 固定模板版（最简单、最可靠）
 * 方案：固定每线索 90px 高度，内容超长直接截断，二维码位置固定
 */
(function () {
  var currentData = null;
  var currentUrl = '';

  // 设计稿基准宽度 750，导出 1080（×1.44）
  var S = 1.44;
  var W = Math.round(750 * S);      // 1080
  var PX = Math.round(48 * S);     // 69
  var HDR = Math.round(108 * S);   // 155
  var FTR = Math.round(180 * S);   // 259（底部蓝色区）
  var QR = Math.round(110 * S);   // 158（二维码）

  var FS_T = Math.round(22 * S);  // 标题字号 32
  var FS_S = Math.round(17 * S);  // 摘要字号 24
  var FS_H = Math.round(24 * S);  // 区块标题 35
  var FS_ST = Math.round(20 * S); // 统计字号 29

  // 固定每线索块高度（标题 1 行 + 摘要 2 行 + 间距）
  var CLUE_BLOCK = Math.round(90 * S);  // 130px
  var MAX_CLUE = 4;  // 最多 4 条线索

  function getDateParam() {
    var m = new RegExp('[?&]date=([^&]+)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function truncate(text, max) {
    if (!text) return '';
    return text.length <= max ? text : text.substring(0, max) + '...';
  }

  function formatChineseDate(ds, wd) {
    var p = (ds || '').split('-');
    if (p.length !== 3) return ds;
    return p[0] + '年' + parseInt(p[1], 10) + '月' + parseInt(p[2], 10) + '日' + (wd ? ' ' + wd : '');
  }

  function roundRect(ctx, x, y, w, h, r) {
    r = r || {};
    var tl = r.tl || 0, tr = r.tr || 0, br = r.br || 0, bl = r.bl || 0;
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

  // 简化二维码（仅演示，生产建议用 qrcode.js）
  function genQR(text, size) {
    var c = document.createElement('canvas');
    c.width = size; c.height = size;
    var x = c.getContext('2d');
    // 用文本 hash 生成伪二维码图案
    var hash = 0;
    for (var i = 0; i < text.length; i++) {
      hash = ((hash << 5) - hash + text.charCodeAt(i)) & 0x7fffffff;
    }
    var N = 21, mods = [], seed = hash;
    for (var i = 0; i < N * N; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      mods.push(seed % 3 === 0);
    }
    function df(x, y, cs) {
      x.fillStyle = '#000'; x.fillRect(x, y, cs * 7, cs * 7);
      x.fillStyle = '#fff'; x.fillRect(x + cs, y + cs, cs * 5, cs * 5);
      x.fillStyle = '#000'; x.fillRect(x + cs * 2, y + cs * 2, cs * 3, cs * 3);
    }
    var mg = Math.floor(size * 0.08), area = size - mg * 2, cs = area / N;
    x.fillStyle = '#fff'; x.fillRect(0, 0, size, size);
    df(mg, mg, cs);
    df(mg + (N - 7) * cs, mg, cs);
    df(mg, mg + (N - 7) * cs, cs);
    for (var r = 0; r < N; r++) {
      for (var col = 0; col < N; col++) {
        if ((r < 8 && col < 8) || (r < 8 && col > N - 9) || (r > N - 9 && col < 8)) continue;
        if (mods[r * N + col]) {
          x.fillStyle = '#000';
          x.fillRect(mg + col * cs, mg + r * cs, Math.max(1, cs - 1), Math.max(1, cs - 1));
        }
      }
    }
    return c;
  }

  function generateImage(data) {
    var dateStr = data.date || getDateParam();
    var clues = data.clues || [];
    var stats = data.stats || {};

    // 固定高度计算
    var contentH = MAX_CLUE * CLUE_BLOCK;  // 线索区总高
    var H = HDR + 30 + 45 + 45 + 20 + 2 + 20 + 45 + 20 + contentH + 30 + QR + 40 + 30 + FTR;

    var canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext('2d');

    // 背景
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, W, H);

    // 头部
    var gTop = ctx.createLinearGradient(0, 0, W, 0);
    gTop.addColorStop(0, '#1664ff'); gTop.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gTop;
    roundRect(ctx, 0, 0, W, HDR, { br: 18, bl: 18 });
    ctx.fill();

    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#fff';
    ctx.font = 'bold ' + Math.round(32 * S) + 'px "PingFang SC"';
    ctx.fillText('信息选题参考', W / 2, HDR * 0.38);
    ctx.font = Math.round(20 * S) + 'px "PingFang SC"';
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillText(formatChineseDate(dateStr, data.weekday), W / 2, HDR * 0.72);

    // 数据统计
    var y = HDR + 30 + 45;
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold ' + FS_H + 'px "PingFang SC"';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('📊 本期数据', PX, y);

    y += 45;
    ctx.font = FS_ST + 'px "PingFang SC"';
    ctx.fillStyle = '#333';
    var parts = [];
    if (stats.total) parts.push('筛选资讯 ' + stats.total + ' 条');
    if (stats.selected) parts.push('相关内容 ' + stats.selected + ' 条');
    if (stats.clues) parts.push('聚合线索 ' + stats.clues + ' 条');
    ctx.fillText(parts.join('  |  '), PX, y);

    // 分隔线
    y += 30;
    ctx.strokeStyle = '#e5e6eb'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PX, y); ctx.lineTo(W - PX, y); ctx.stroke();

    // 今日热点
    y += 34;
    ctx.font = 'bold ' + FS_H + 'px "PingFang SC"';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('🔥 今日热点', PX, y);

    // 线索列表（固定每块 130px）
    y += 50;
    for (var i = 0; i < Math.min(clues.length, MAX_CLUE); i++) {
      var cl = clues[i];
      if (!cl) continue;

      // 标题（1 行，截断）
      ctx.font = 'bold ' + FS_T + 'px "PingFang SC"';
      ctx.fillStyle = '#1d2129';
      ctx.fillText((i + 1) + '. ' + truncate(cl.title, 20), PX, y);

      // 摘要（2 行，截断）
      y += Math.round(32 * S);
      ctx.font = FS_S + 'px "PingFang SC"';
      ctx.fillStyle = '#555';
      ctx.fillText(truncate(cl.summary || '', 26), PX + 20, y);
      y += Math.round(24 * S);
      ctx.fillText(truncate((cl.summary || '').slice(26), PX + 20, y);

      y += Math.round(44 * S);  // 下间距
    }

    // "还有更多"提示
    if (clues.length > MAX_CLUE) {
      y += 10;
      ctx.font = Math.round(16 * S) + 'px "PingFang SC"';
      ctx.fillStyle = '#86909c';
      ctx.fillText('... 还有 ' + (clues.length - MAX_CLUE) + ' 条线索，扫码查看完整版', PX, y);
      y += 36;
    }

    // 二维码（固定位置：蓝色区上方 40px）
    y += 30;
    var qrX = W - PX - QR;
    var qrY = y;
    // 安全校验：二维码不能进入底部蓝色区
    if (qrY + QR > H - FTR - 20) {
      qrY = H - FTR - QR - 40;
    }
    ctx.drawImage(genQR(currentUrl, QR), qrX, qrY, QR, QR);
    ctx.font = Math.round(13 * S) + 'px "PingFang SC"';
    ctx.fillStyle = '#86909c';
    ctx.textAlign = 'center';
    ctx.fillText('扫码查看完整', qrX + QR / 2, qrY + QR + 24);

    y = Math.max(y + QR + 40, qrY + QR + 40);

    // 底部蓝色区
    var botY = H - FTR;
    var gBot = ctx.createLinearGradient(0, botY, W, botY);
    gBot.addColorStop(0, '#1664ff'); gBot.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gBot;
    roundRect(ctx, 0, botY, W, FTR, { tr: 18, tl: 18 });
    ctx.fill();

    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold ' + Math.round(20 * S) + 'px "PingFang SC"';
    ctx.fillStyle = '#fff';
    ctx.fillText('信息选题日报', PX, botY + 56);
    ctx.font = Math.round(15 * S) + 'px "PingFang SC"';
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.fillText('dailyinfox.cn', PX, botY + 86);

    // 导出 540px 宽
    var out = document.createElement('canvas');
    out.width = 540; out.height = Math.round(H * 540 / W);
    out.getContext('2d').drawImage(canvas, 0, 0, out.width, out.height);
    return out.toDataURL('image/png', 1.0);
  }

  // 弹窗逻辑
  function openModal() {
    var modal = document.getElementById('share-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'share-modal'; modal.className = 'share-modal';
      modal.innerHTML = '<div class="share-modal-content">' +
        '<div class="share-modal-header"><span class="share-modal-title">分享到微信</span>' +
        '<button class="share-modal-close" id="share-modal-close">&times;</button></div>' +
        '<div class="share-modal-body" id="share-modal-body">' +
        '<div class="share-loading"><span class="share-spinner"></span>正在生成图片...</div></div></div>';
      document.body.appendChild(modal);
      document.getElementById('share-modal-close').onclick = closeModal;
      modal.onclick = function (e) { if (e.target === modal) closeModal(); };
    }
    modal.classList.add('active');
    document.getElementById('share-modal-body').innerHTML =
      '<div class="share-loading"><span class="share-spinner"></span>正在生成图片...</div>';

    setTimeout(function () {
      try {
        if (!currentData) {
          document.getElementById('share-modal-body').innerHTML =
            '<p style="color:#86909c;padding:20px;text-align:center">数据加载中，请稍后重试</p>';
          return;
        }
        var url = generateImage(currentData);
        document.getElementById('share-modal-body').innerHTML =
          '<div class="share-preview-wrap"><img src="' + url + '" style="width:100%;border-radius:12px"></div>' +
          '<div class="share-actions">' +
          '<button class="share-action-btn share-save-btn" id="share-save-btn">💾 保存图片</button>' +
          '<button class="share-action-btn share-copy-btn" id="share-copy-link">🔗 复制链接</button></div>';
        document.getElementById('share-save-btn').onclick = function () {
          var a = document.createElement('a');
          a.href = url; a.download = (currentData.date || '') + '_信息选题.png';
          a.click();
        };
        document.getElementById('share-copy-link').onclick = function () {
          if (navigator.clipboard) navigator.clipboard.writeText(location.href);
        };
      } catch (e) {
        console.error(e);
        document.getElementById('share-modal-body').innerHTML =
          '<p style="color:#e0457b;padding:20px;text-align:center">生成失败：' + e.message + '</p>';
      }
    }, 300);
  }

  function closeModal() {
    var m = document.getElementById('share-modal');
    if (m) m.classList.remove('active');
  }

  // 初始化
  function init() {
    var btn = document.getElementById('share-btn');
    if (btn) btn.onclick = function (e) { e.preventDefault(); openModal(); };
    currentUrl = location.href;
    window._onShareDataReady = function (d) { currentData = d; };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
