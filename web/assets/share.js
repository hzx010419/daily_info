/**
 * 分享生图 - 重构版 v2
 * 原则：测量和绘制用【同一套 font】，高度 100% 动态计算
 */
(function () {
  var currentData = null;
  var currentUrl  = '';

  /* ========================================================
   *  常量 & 工具
   * ======================================================== */

  var FONT_TITLE   = 'PingFang SC, "Microsoft YaHei", sans-serif';
  var FONT_SUMMARY = 'PingFang SC, "Microsoft YaHei", sans-serif';
  var FONT_STATS   = 'PingFang SC, "Microsoft YaHei", sans-serif';
  var FONT_MORE    = 'PingFang SC, "Microsoft YaHei", sans-serif';
  var FONT_QR_HINT = 'PingFang SC, "Microsoft YaHei", sans-serif';

  function getDateParam() {
    var m = new RegExp('[?&]date=([^&]+)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : '';
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
   * 用 measureText 逐字符自动换行
   * 返回每行文字数组（最多 maxLines 行）
   */
  function autoWrap(ctx, text, maxWidth, maxLines) {
    maxLines = maxLines || 2;
    var lines = [];
    var chars = (text || '').split('');
    var line  = '';
    for (var i = 0; i < chars.length; i++) {
      var test = line + chars[i];
      if (ctx.measureText(test).width > maxWidth && line !== '') {
        lines.push(line);
        line = chars[i];
        if (lines.length >= maxLines) break;
      } else {
        line = test;
      }
    }
    if (line && lines.length < maxLines) lines.push(line);
    return lines;
  }

  /* ========================================================
   *  二维码（简化版，仅演示；生产建议用 qrcode.js）
   * ======================================================== */
  function generateQRCode(text, size) {
    var cvs = document.createElement('canvas');
    cvs.width = size; cvs.height = size;
    var c = cvs.getContext('2d');

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
    var mods = []; var seed = h;
    for (var i = 0; i < N * N; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      mods.push(seed % 3 === 0);
    }

    function df(x, y, cs) {
      c.fillStyle = '#000'; c.fillRect(x, y, cs * 7, cs * 7);
      c.fillStyle = '#fff'; c.fillRect(x + cs, y + cs, cs * 5, cs * 5);
      c.fillStyle = '#000'; c.fillRect(x + cs * 2, y + cs * 2, cs * 3, cs * 3);
    }

    var mg = Math.floor(size * 0.10);
    var area = size - mg * 2;
    var cs = area / N;

    c.fillStyle = '#fff'; c.fillRect(0, 0, size, size);
    df(mg, mg, cs);
    df(mg + (N - 7) * cs, mg, cs);
    df(mg, mg + (N - 7) * cs, cs);

    for (var row = 0; row < N; row++) {
      for (var col = 0; col < N; col++) {
        if ((row < 8 && col < 8) ||
            (row < 8 && col > N - 8) ||
            (row > N - 8 && col < 8)) continue;
        if (mods[row * N + col]) {
          c.fillStyle = '#000';
          c.fillRect(mg + col * cs, mg + row * cs,
                     Math.max(1, cs - 1), Math.max(1, cs - 1));
        }
      }
    }
    return cvs;
  }

  /* ========================================================
   *  主函数：生成分享图（两遍渲染）
   * ======================================================== */
  function generateShareImage(data) {
    var dateStr = data.date || getDateParam();
    var clues  = data.clues || [];
    var stats  = data.stats || {};

    /* ---- 设计常量（基于 750px 设计稿，最终 ×1.44 → 1080px）---- */
    var SCALE   = 1.44;
    var W       = Math.round(750 * SCALE);   // 1080
    var PX      = Math.round(48  * SCALE);   // ~69
    var CONTENT = W - PX * 2;

    var HDR     = Math.round(108 * SCALE);   // 头部高度
    var FTR     = Math.round(170 * SCALE);   // 底部蓝色区高度（加大）
    var QR_SZ  = Math.round(108 * SCALE);   // 二维码尺寸

    // 字体大小（已放大 SCALE 倍）
    var FS_TITLE   = Math.round(22 * SCALE);
    var FS_SUMMARY = Math.round(17 * SCALE);
    var FS_STATS   = Math.round(20 * SCALE);
    var FS_MORE    = Math.round(16 * SCALE);
    var FS_HEAD    = Math.round(24 * SCALE);

    /* ---- 第 1 遍：纯测量（用临时 Canvas，font 设置和绘制时完全一致）---- */
    var mCvs = document.createElement('canvas');
    mCvs.width = W; mCvs.height = 3000;
    var mc = mCvs.getContext('2d');

    // 测量指定 font 下一段文字的实际像素高度
    function measureTextH(font, linesCount) {
      mc.font = font;
      // 用 measureText 只能测宽度，高度用经验值：fontSize × 1.38
      var fontSize = parseInt(font.match(/\d+/)[0], 10);
      return Math.ceil(fontSize * 1.25) * linesCount;
    }

    var clueMeas = [];   // [{titleLines, summaryLines, blockH}]
    var totalCluesH = 0;
    var MAX_SHOW = Math.min(clues.length, 5);

    for (var ci = 0; ci < MAX_SHOW; ci++) {
      var cl = clues[ci];
      if (!cl) continue;

      // ★ 测量标题（字体设置和绘制时完全一致）
      mc.font = 'bold ' + FS_TITLE + 'px "' + FONT_TITLE + '"';
      var tLines = autoWrap(mc, (ci + 1) + '. ' + (cl.title || ''), CONTENT, 2);

      // ★ 测量摘要（字体设置和绘制时完全一致）
      mc.font = FS_SUMMARY + 'px "' + FONT_SUMMARY + '"';
      var sLines = autoWrap(mc, (cl.summary || '').replace(/\s+/g, ' '), CONTENT - Math.round(12 * SCALE), 2);

      // 每块线索高度 = 标题行高 + 间距 + 摘要行高 + 下间距
      var titleH   = measureTextH('bold ' + FS_TITLE + 'px "' + FONT_TITLE + '"', tLines.length);
      var summaryH = measureTextH(FS_SUMMARY + 'px "' + FONT_SUMMARY + '"', sLines.length);
      var blockH   = titleH
                     + Math.round(25 * SCALE)   // 标题→摘要间距
                     + summaryH
                     + Math.round(80 * SCALE);  // 线索间大间距

      clueMeas.push({ titleLines: tLines, summaryLines: sLines, blockH: blockH });
      totalCluesH += blockH;
    }

    // "还有更多"提示高度
    var moreH = 0;
    if (clues.length > MAX_SHOW) {
      moreH = measureTextH(FS_MORE + 'px "' + FONT_MORE + '"', 1)
             + Math.round(28 * SCALE);
    }

    // 二维码区域高度（纳入总高！）
    var qrAreaH = QR_SZ + Math.round(20 * SCALE) + Math.round(24 * SCALE);

    // ---- 总画布高度（100% 动态计算）----
    var H =
      HDR +                                 // 头部
      Math.round(20  * SCALE) +             // 头部下空白
      measureTextH('bold ' + FS_HEAD + 'px "' + FONT_STATS + '"', 1) +
      Math.round(40  * SCALE) +             // 统计文字
      Math.round(24  * SCALE) +             // 分隔线区
      measureTextH('bold ' + FS_HEAD + 'px "' + FONT_STATS + '"', 1) +
      Math.round(16  * SCALE) +             // 热点标题下空白
      totalCluesH +                         // 所有线索
      moreH +                               // "还有更多"
      Math.round(36  * SCALE) +             // 线索区→二维码间距
      qrAreaH +                            // 二维码区域（★ 纳入总高）
      Math.round(28  * SCALE) +             // 二维码→底部间距
      FTR;                                 // 底部蓝色区

    /* ---- 第 2 遍：正式绘制 ---- */
    var canvas = document.createElement('canvas');
    canvas.width = W; canvas.height = H;
    var ctx = canvas.getContext('2d');

    // === 背景 ===
    ctx.fillStyle = '#ffffff'; ctx.fillRect(0, 0, W, H);

    // === 头部（底边圆角）===
    var gTop = ctx.createLinearGradient(0, 0, W, 0);
    gTop.addColorStop(0, '#1664ff'); gTop.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gTop;
    roundRect(ctx, 0, 0, W, HDR, { br: Math.round(16 * SCALE), bl: Math.round(16 * SCALE) });
    ctx.fill();

    ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold ' + Math.round(32 * SCALE) + 'px "' + FONT_TITLE + '"';
    ctx.fillText('信息选题参考', W / 2, HDR * 0.38);
    ctx.font = Math.round(20 * SCALE) + 'px "' + FONT_SUMMARY + '"';
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.fillText(formatChineseDate(dateStr, data.weekday), W / 2, HDR * 0.72);

    // === 数据统计 ===
    var y = HDR + Math.round(20 * SCALE);
    y += measureTextH('bold ' + FS_HEAD + 'px "' + FONT_STATS + '"', 1);
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold ' + FS_HEAD + 'px "' + FONT_STATS + '"';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('📊 本期数据', PX, y);

    y += Math.round(80 * SCALE);
    ctx.font = FS_STATS + 'px "' + FONT_STATS + '"';
    ctx.fillStyle = '#333333';
    var parts = [];
    if (stats.total)    parts.push('筛选资讯 ' + stats.total + ' 条');
    if (stats.selected) parts.push('相关内容 ' + stats.selected + ' 条');
    if (stats.clues)    parts.push('聚合线索 ' + stats.clues + ' 条');
    ctx.fillText(parts.join('  |  '), PX, y);

    // === 分隔线 ===
    y += Math.round(28 * SCALE);
    ctx.strokeStyle = '#e5e6eb'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(PX, y); ctx.lineTo(W - PX, y); ctx.stroke();

    // === 今日热点标题 ===
    y += Math.round(34 * SCALE);
    ctx.font = 'bold ' + FS_HEAD + 'px "' + FONT_STATS + '"';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('🔥 今日热点', PX, y);

    // === 线索列表（用测量好的 titleLines / summaryLines 绘制）===
    y += Math.round(42 * SCALE);

    for (var c = 0; c < clueMeas.length; c++) {
      var m = clueMeas[c];

      // 标题（加粗，自动换行最多2行）
      ctx.font = 'bold ' + FS_TITLE + 'px "' + FONT_TITLE + '"';
      ctx.fillStyle = '#1d2129';
      for (var tl = 0; tl < m.titleLines.length; tl++) {
        ctx.fillText(m.titleLines[tl], PX, y);
        y += measureTextH('bold ' + FS_TITLE + 'px "' + FONT_TITLE + '"', 1);
      }

      // 摘要（普通，自动换行最多2行，缩进）
      y += Math.round(16 * SCALE);
      ctx.font = FS_SUMMARY + 'px "' + FONT_SUMMARY + '"';
      ctx.fillStyle = '#555555';
      for (var sl = 0; sl < m.summaryLines.length; sl++) {
        ctx.fillText(m.summaryLines[sl], PX + Math.round(12 * SCALE), y);
        y += measureTextH(FS_SUMMARY + 'px "' + FONT_SUMMARY + '"', 1);
      }

      y += Math.round(56 * SCALE); // 下间距
    }

    // "还有更多"提示
    if (clues.length > MAX_SHOW) {
      y += Math.round(20 * SCALE);
      ctx.font = FS_MORE + 'px "' + FONT_MORE + '"';
      ctx.fillStyle = '#86909c';
      ctx.fillText(
        '... 还有 ' + (clues.length - MAX_SHOW) + ' 条线索，扫码查看完整版',
        PX, y
      );
      y += measureTextH(FS_MORE + 'px "' + FONT_MORE + '"', 1);
    }

    // === 二维码区域（在白色区域内，纳入总高所以绝不被裁切）===
    y += Math.round(36 * SCALE);
    var qrX = W - PX - QR_SZ;
    var qrY = y;

    var qrCvs = generateQRCode(currentUrl, QR_SZ);
    ctx.drawImage(qrCvs, qrX, qrY, QR_SZ, QR_SZ);

    // 扫码提示
    ctx.font = Math.round(13 * SCALE) + 'px "' + FONT_QR_HINT + '"';
    ctx.fillStyle = '#86909c';
    ctx.textAlign = 'center';
    ctx.fillText('扫码查看完整', qrX + QR_SZ / 2, qrY + QR_SZ + Math.round(24 * SCALE));

    y += qrAreaH;

    // === 底部蓝色区（顶边圆角）===
    var botY = H - FTR;
    var gBot = ctx.createLinearGradient(0, botY, W, botY);
    gBot.addColorStop(0, '#1664ff'); gBot.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gBot;
    roundRect(ctx, 0, botY, W, FTR, { tr: Math.round(16 * SCALE), tl: Math.round(16 * SCALE) });
    ctx.fill();

    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
    ctx.font = 'bold ' + Math.round(20 * SCALE) + 'px "' + FONT_TITLE + '"';
    ctx.fillStyle = '#ffffff';
    ctx.fillText('信息选题日报', PX, botY + Math.round(56 * SCALE));
    ctx.font = Math.round(15 * SCALE) + 'px "' + FONT_SUMMARY + '"';
    ctx.fillStyle = 'rgba(255,255,255,0.72)';
    ctx.fillText('dailyinfox.cn', PX, botY + Math.round(86 * SCALE));

    // === 导出：缩到 540px 宽（高清 @2x）===
    var outCvs = document.createElement('canvas');
    outCvs.width  = 540;
    outCvs.height = Math.round(H * 540 / W);
    var oc = outCvs.getContext('2d');
    oc.drawImage(canvas, 0, 0, outCvs.width, outCvs.height);
    return outCvs.toDataURL('image/png', 1.0);
  }

  /* ========================================================
   *  弹窗 / 保存 / 复制 / 初始化
   * ======================================================== */
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
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
  }

  function copyLink() {
    var u = currentUrl || location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(u).then(function () {
        var b = document.getElementById('share-copy-link');
        if (b) { b.textContent = '✅ 已复制'; setTimeout(function () { b.textContent = '🔗 复制链接'; }, 2000); }
      });
    } else { prompt('复制链接：', u); }
  }

  function init() {
    var btn = document.getElementById('share-btn');
    if (btn) btn.addEventListener('click', function (e) { e.preventDefault(); openShareModal(); });
    currentUrl = location.href;
    window._onShareDataReady = function (d) { currentData = d; };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else { init(); }
})();
