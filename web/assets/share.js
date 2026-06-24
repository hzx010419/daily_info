/**
 * 分享生图 - 固定排版版（手机端 100% 不重叠）
 * 策略：固定每线索 3 行（标题 1 行 + 摘要 2 行），内容超长直接截断
 */
(function () {
  var currentData = null;
  var currentUrl  = '';

  /* ========== 设计常量（基于 1080px 宽，所有数值已换算）========== */
  var W       = 1080;            // 画布宽
  var PX      = 72;              // 左右内边距
  var HDR_H   = 156;             // 头部蓝色区高度
  var FTR_H   = 244;             // 底部蓝色区高度（加大，确保二维码不裁切）
  var QR_SZ  = 156;             // 二维码尺寸（加大，更清晰）
  var MAX_CLUE = 4;              // 最多显示 4 条线索（减少内容量，确保不重叠）

  // 字体大小（对应 1080px 宽）
  var FS_TITLE   = 32;   // 标题字号
  var FS_SUMMARY = 24;   // 摘要字号
  var FS_HEAD    = 36;   // 区块标题字号
  var FS_STATS   = 30;   // 统计字号
  var FS_MORE    = 24;   // "还有更多"字号

  // 固定行高（用经验值，不动态测量，杜绝手机端差异）
  var LH_TITLE   = Math.ceil(FS_TITLE   * 1.5); // 48px
  var LH_SUMMARY = Math.ceil(FS_SUMMARY * 1.5); // 36px

  // 固定间距（设计稿 px，直接写死）
  var GAP_TITLE_SUMMARY = 20;  // 标题→摘要间距
  var GAP_CLUE         = 80;  // 线索之间间距
  var GAP_HEAD_BODY     = 56;  // 区块标题→内容间距
  var GAP_QR           = 40;  // 二维码→蓝色条间距

  /* ========== 工具函数 ========== */
  function getDateParam() {
    var m = new RegExp('[?&]date=([^&]+)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  /** 截断文字（按字符数，中文=1 字符，英文=0.5） */
  function truncate(text, maxLen) {
    if (!text) return '';
    var len = 0, res = '';
    for (var i = 0; i < text.length; i++) {
      len += text.charCodeAt(i) > 255 ? 1 : 0.5;
      if (len > maxLen) return res + '...';
      res += text[i];
    }
    return res;
  }

  /** 圆角矩形路径 */
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

  function formatChineseDate(ds, wd) {
    var p = (ds || '').split('-');
    if (p.length !== 3) return ds;
    var r = p[0] + '年' + parseInt(p[1], 10) + '月' + parseInt(p[2], 10) + '日';
    if (wd) r += ' ' + wd;
    return r;
  }

  /** 二维码生成（简化版） */
  function generateQRCode(text, size) {
    var canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    var ctx = canvas.getContext('2d');

    function hash(str) {
      var h = 0;
      for (var i = 0; i < str.length; i++) {
        h = ((h << 5) - h + str.charCodeAt(i);
        h = h & h;
      }
      return Math.abs(h);
    }

    var h = hash(text);
    var N = 17;
    var mods = [];
    var seed = h;
    for (var i = 0; i < N * N; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      mods.push(seed % 3 === 0);
    }

    function df(x, y, cs) {
      ctx.fillStyle = '#000'; ctx.fillRect(x, y, cs * 7, cs * 7);
      ctx.fillStyle = '#fff'; ctx.fillRect(x + cs, y + cs, cs * 5, cs * 5);
      ctx.fillStyle = '#000'; ctx.fillRect(x + cs * 2, y + cs * 2, cs * 3, cs * 3);
    }

    var mg = Math.floor(size * 0.10);
    var area = size - mg * 2;
    var cs = area / N;

    ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, size, size);
    df(mg, mg, cs);
    df(mg + (N - 7) * cs, mg, cs);
    df(mg, mg + (N - 7) * cs, cs);

    for (var row = 0; row < N; row++) {
      for (var col = 0; col < N; col++) {
        if ((row < 8 && col < 8) || (row < 8 && col > N - 8) || (row > N - 8 && col < 8)) continue;
        if (mods[row * N + col]) {
          ctx.fillStyle = '#000';
          ctx.fillRect(mg + col * cs, mg + row * cs, Math.max(1, cs - 1), Math.max(1, cs - 1));
        }
      }
    }
    return canvas;
  }

  /* ========== 主函数：生成分享图 ========== */
  function generateShareImage(data) {
    var dateStr = data.date || getDateParam();
    var clues  = data.clues || [];
    var stats  = data.stats || {};

    // ---- 固定计算每个线索块高度 ----
    // 每块 = 标题 1 行 + 间距 + 摘要 2 行 + 下间距
    var CLUE_BLOCK_H =
      LH_TITLE +               // 标题 1 行
      GAP_TITLE_SUMMARY +      // 标题→摘要间距
      LH_SUMMARY * 2 +        // 摘要 2 行
      GAP_CLUE;               // 线索之间间距

    var showCount = Math.min(clues.length, MAX_CLUE);
    var cluesTotalH = showCount * CLUE_BLOCK_H;

    // "还有更多"提示高度
    var moreH = 0;
    if (clues.length > showCount) {
      moreH = LH_SUMMARY + GAP_HEAD_BODY;  // 1 行文字 + 上间距
    }

    // 二维码区域高度（在白色区域内）
    var qrAreaH = QR_SZ + 24 + 32;  // 二维码 + 上间距 + 提示文字

    // ---- 总画布高度（100% 固定计算，无动态测量）----
    var H =
      HDR_H +               // 头部
      32 +                  // 头部下空白
      LH_TITLE +           // "本期数据" 标题行高
      52 +                  // 统计文字 + 间距
      2 +                   // 分隔线
      20 +                  // 分隔线下空白
      LH_TITLE +           // "今日热点" 标题行高
      GAP_HEAD_BODY +       // 标题→线索间距
      cluesTotalH +         // 所有线索
      moreH +              // "还有更多"
      GAP_QR +              // 线索→二维码间距
      qrAreaH +            // 二维码区域
      GAP_QR +              // 二维码→底部间距
      FTR_H;               // 底部蓝色区

    // ---- 绘制 ----
    var canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext('2d');

    // 背景
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);

    // 头部蓝色渐变
    var gradTop = ctx.createLinearGradient(0, 0, W, 0);
    gradTop.addColorStop(0, '#1664ff'); gradTop.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradTop;
    roundRect(ctx, 0, 0, W, HDR_H, { br: 20, bl: 20 });
    ctx.fill();

    // 头部文字
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold ' + FS_HEAD + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillText('信息选题参考', W / 2, HDR_H * 0.38);
    ctx.font = FS_STATS + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillText(formatChineseDate(dateStr, data.weekday), W / 2, HDR_H * 0.72);

    // 数据统计
    var y = HDR_H + 32 + LH_TITLE;
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold ' + FS_STATS + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('📊 本期数据', PX, y);

    y += 52;
    ctx.font = FS_STATS + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#333333';
    var parts = [];
    if (stats.total)    parts.push('筛选资讯 ' + stats.total + ' 条');
    if (stats.selected) parts.push('相关内容 ' + stats.selected + ' 条');
    if (stats.clues)    parts.push('聚合线索 ' + stats.clues + ' 条');
    ctx.fillText(parts.join('  |  '), PX, y);

    // 分隔线
    y += 36;
    ctx.strokeStyle = '#e5e6eb'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PX, y); ctx.lineTo(W - PX, y); ctx.stroke();

    // 今日热点标题
    y += 46;
    ctx.font = 'bold ' + FS_HEAD + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('🔥 今日热点', PX, y);

    // 线索列表（固定排版：标题 1 行 + 摘要 2 行）
    y += GAP_HEAD_BODY;

    for (var c = 0; c < showCount; c++) {
      var cl = clues[c];
      if (!cl) continue;

      // 标题（1 行，超长直接截断）
      ctx.font = 'bold ' + FS_TITLE + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#1d2129';
      ctx.fillText(truncate((c + 1) + '. ' + (cl.title || ''), 22), PX, y);
      // 如果标题超长，直接截断到能放下为止
      while (ctx.measureText(ctx.fillText.toString()).width > W - PX * 2 && (c + 1) + '. ' + (cl.title || '').length > 5) {
        cl.title = (cl.title || '').slice(0, -1);
        ctx.fillText(truncate((c + 1) + '. ' + (cl.title || ''), 22), PX, y);
      }

      // 摘要（2 行，超长直接截断）
      y += LH_TITLE + GAP_TITLE_SUMMARY;
      ctx.font = FS_SUMMARY + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#555555';
      var sum = truncate((cl.summary || '').replace(/\s+/g, ' '), 40);
      // 第 1 行摘要
      ctx.fillText(sum, PX + 20, y);
      // 第 2 行摘要（如果有）
      if (sum.length > 20) {
        y += LH_SUMMARY;
        ctx.fillText(sum.slice(20), PX + 20, y);
      }

      y += LH_SUMMARY + GAP_CLUE;  // 下间距
    }

    // "还有更多"提示
    if (clues.length > showCount) {
      y += GAP_HEAD_BODY;
      ctx.font = FS_MORE + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#86909c';
      ctx.fillText('... 还有 ' + (clues.length - showCount) + ' 条线索，扫码查看完整版', PX, y);
      y += LH_SUMMARY;
    }

    // 二维码（在白色区域内，距蓝色条上方 GAP_QR）
    y += GAP_QR;
    var qrX = W - PX - QR_SZ;
    var qrY = y;

    // 安全校验：确保二维码不进入蓝色条
    var blueStart = H - FTR_H;
    if (qrY + QR_SZ > blueStart - 16) {
      qrY = blueStart - QR_SZ - 32;  // 强制移到蓝色条上方
    }

    var qrCanvas = generateQRCode(currentUrl, QR_SZ);
    ctx.drawImage(qrCanvas, qrX, qrY, QR_SZ, QR_SZ);

    // 扫码提示
    ctx.font = '14px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#86909c';
    ctx.textAlign = 'center';
    ctx.fillText('扫码查看完整', qrX + QR_SZ / 2, qrY + QR_SZ + 28);

    y += qrAreaH + GAP_QR;

    // 底部蓝色区
    var botY = H - FTR_H;
    var gradBot = ctx.createLinearGradient(0, botY, W, botY);
    gradBot.addColorStop(0, '#1664ff'); gradBot.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradBot;
    roundRect(ctx, 0, botY, W, FTR_H, { tr: 20, tl: 20 });
    ctx.fill();

    // 底部网站信息
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold ' + FS_STATS + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.fillText('信息选题日报', PX, botY + 72);
    ctx.font = (FS_STATS - 6) + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.fillText('dailyinfox.cn', PX, botY + 108);

    // 导出为 540px 宽（高清 @2x）
    var out = document.createElement('canvas');
    out.width = 540; out.height = Math.round(H * 540 / W);
    var oc = out.getContext('2d');
    oc.drawImage(canvas, 0, 0, out.width, out.height);
    return out.toDataURL('image/png', 1.0);
  }

  /* ========== 弹窗逻辑 ========== */
  function openShareModal() {
    var modal = document.getElementById('share-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'share-modal'; modal.className = 'share-modal';
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
    a.href = url; a.download = name;
    a.style.display = 'none';
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
  }

  function copyLink() {
    var u = currentUrl || location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(u).then(function () {
        var b = document.getElementById('share-copy-link');
        if (b) { b.textContent = '✅ 已复制'; setTimeout(function () { b.textContent = '🔗 复制链接'; }, 2000); }
      });
    } else {
      prompt('复制链接：', u);
    }
  }

  /* ========== 初始化 ========== */
  function init() {
    var btn = document.getElementById('share-btn');
    if (btn) btn.addEventListener('click', function (e) { e.preventDefault(); openShareModal(); });
    currentUrl = location.href;
    window._onShareDataReady = function (d) { currentData = d; };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
