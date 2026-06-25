/**
 * 分享生图 - 每日金句卡片版（v2）
 * 风格：简洁引用 + 作者信息 + 可扫码二维码（类似每日一句/金句卡片）
 */
(function () {
  var currentData = null;
  var currentUrl = '';

  // 卡片尺寸基准
  var W = 750;
  var PAD = 56;
  var TOP_PAD = 100;
  var BOT_PAD = 50;

  // 字号
  var FS_QUOTE = 40;
  var FS_AUTHOR = 28;
  var FS_DESC = 24;
  var FS_DATE = 22;

  function wrapText(ctx, text, maxWidth) {
    if (!text) return [];
    var lines = [], paragraph = text.split(/\n/);
    for (var pi = 0; pi < paragraph.length; pi++) {
      var para = paragraph[pi];
      if (para === '') { lines.push(''); continue; }
      var current = '';
      for (var ci = 0; ci < para.length; ci++) {
        var ch = para[ci], test = current + ch;
        if (ctx.measureText(test).width > maxWidth && current !== '') {
          lines.push(current); current = ch;
        } else { current = test; }
      }
      if (current) lines.push(current);
    }
    return lines;
  }

  function truncateLines(lines, maxLines) {
    if (lines.length <= maxLines) return lines;
    var result = lines.slice(0, maxLines);
    var last = result[maxLines - 1];
    result[maxLines - 1] = last.length > 3 ? last.slice(0, -3) + '...' : '...';
    return result;
  }

  function formatChineseDate(ds) {
    var p = (ds || '').split('-');
    return p.length === 3 ? p[0] + '年' + parseInt(p[1], 10) + '月' + parseInt(p[2], 10) + '日' : ds;
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

  function drawAvatar(ctx, cx, cy, radius, name) {
    ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fillStyle = '#1664ff'; ctx.fill();
    ctx.font = 'bold ' + Math.round(radius * 1.1) + 'px "PingFang SC", sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#fff';
    ctx.fillText((name || '\u8D44').charAt(0), cx, cy + 1);
    ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  }

  /**
   * 异步生成二维码 Canvas，返回 Promise<Canvas>
   */
  function generateQRCanvas(text, size) {
    return new Promise(function (resolve, reject) {
      if (!window.QRCode) { resolve(null); return; }
      try {
        var container = document.createElement('div');
        document.body.appendChild(container);
        var qrcode = new QRCode(container, {
          text: text,
          width: size,
          height: size,
          colorDark: '#222',
          colorLight: '#ffffff',
          correctLevel: window.QRCode.CorrectLevel.M,
          useSVG: false
        });
        // 等待一帧确保渲染完成
        setTimeout(function () {
          var qrCanvas = container.querySelector('canvas') || null;
          if (qrCanvas) {
            // 克隆到独立 canvas 遲免被清理
            var clone = document.createElement('canvas');
            clone.width = size; clone.height = size;
            clone.getContext('2d').drawImage(qrCanvas, 0, 0);
            document.body.removeChild(container);
            resolve(clone);
          } else {
            var img = container.querySelector('img');
            if (img && img.complete) {
              var c2 = document.createElement('canvas');
              c2.width = size; c2.height = size;
              var ctx2 = c2.getContext('2d');
              ctx2.drawImage(img, 0, 0, size, size);
              document.body.removeChild(container);
              resolve(c2);
            } else {
              document.body.removeChild(container);
              resolve(null);
            }
          }
        }, 80);
      } catch (e) { resolve(null); }
    });
  }

  function extractQuote(data) {
    var clues = data.clues || [];
    if (!clues.length) {
      return { quote: '\u4ECA\u65E5\u6682\u65E0\u7EBF\u7D22\uFF0C\u656C\u8BF7\u671F\u5F85\u3002', author: '\u4FE1\u606F\u9009\u9898\u53C2\u8003', desc: '\u6BCF\u65E5\u70ED\u70B9\u4FE1\u606F\u805A\u5408', date: data.date || '', weekday: data.weekday || '' };
    }
    var fc = clues[0];
    var sources = fc.sources || [];
    return {
      quote: fc.summary || fc.title || '',
      author: (sources.length && sources[0].source) ? sources[0].source : '\u4FE1\u606F\u9009\u9898\u53C2\u8003',
      desc: fc.title || '',
      date: data.date || '',
      weekday: data.weekday || ''
    };
  }

  /**
   * 主绘图函数 - 返回 Promise<string> (dataURL)
   */
  function generateImage(data) {
    var info = extractQuote(data);
    var qrSize = 180;

    // 先测量文字布局以确定高度
    var measureCtx = document.createElement('canvas').getContext('2d');
    measureCtx.font = FS_QUOTE + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
    var allLines = wrapText(measureCtx, info.quote, W - PAD * 2);
    var quoteLines = truncateLines(allLines, 8);

    var avatarR = 36, footerH = 120;
    var contentH = TOP_PAD + quoteLines.length * (FS_QUOTE + 16) + 60 + footerH + BOT_PAD;

    // 先生成二维码
    return generateQRCanvas(currentUrl, qrSize).then(function (qrCanvas) {
      var canvas = document.createElement('canvas');
      canvas.width = W; canvas.height = contentH;
      var H = contentH;
      var ctx = canvas.getContext('2d');

      // ---- 背景 ----
      ctx.fillStyle = '#f7f5f0';
      ctx.fillRect(0, 0, W, H);

      // ---- 装饰性引号 ----
      ctx.font = 'bold 160px Georgia, serif';
      ctx.fillStyle = 'rgba(200,195,185,0.35)';
      ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      ctx.fillText('\u201C', PAD - 20, TOP_PAD - 30);

      // ---- 金句正文 ----
      ctx.font = FS_QUOTE + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#2c2c2c';
      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      var textY = TOP_PAD + 40;
      for (var i = 0; i < quoteLines.length; i++) {
        ctx.fillText(quoteLines[i], PAD, textY);
        textY += FS_QUOTE + 16;
      }

      // ---- 日期标签 ----
      ctx.font = FS_DATE + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#b8b0a0';
      ctx.textAlign = 'right'; ctx.textBaseline = 'alphabetic';
      ctx.fillText(formatChineseDate(info.date), W - PAD, TOP_PAD + 10);

      // ---- 分隔线 ----
      var sepY = textY + 40;
      ctx.beginPath(); ctx.moveTo(PAD, sepY); ctx.lineTo(W - PAD, sepY);
      ctx.strokeStyle = 'rgba(180,175,165,0.25)'; ctx.lineWidth = 1; ctx.stroke();

      // ---- 底部区域 ----
      var footerStartY = sepY + 24;

      // 头像
      drawAvatar(ctx, PAD + avatarR, footerStartY + avatarR, avatarR, info.author);

      // 作者名
      ctx.font = 'bold ' + FS_AUTHOR + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#3a3a3a'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      ctx.fillText(info.author, PAD + avatarR * 2 + 20, footerStartY + 12);

      // 描述语
      ctx.font = FS_DESC + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#777';
      var descMaxW = W - PAD - qrSize - 40 - (PAD + avatarR * 2 + 20);
      var descLine = wrapText(ctx, info.desc, descMaxW)[0];
      if (!descLine) descLine = info.desc;
      if (ctx.measureText(descLine || '').width > descMaxW) {
        descLine = descLine.slice(0, -3) + '...';
      }
      ctx.fillText(descLine || '', PAD + avatarR * 2 + 20, footerStartY + 52);

      // ---- 二维码 ----
      var qrX = W - PAD - qrSize;
      var qrY = footerStartY + (footerH - qrSize) / 2 - 10;

      roundRectPath(ctx, qrX - 6, qrY - 6, qrSize + 12, qrSize + 12, 12);
      ctx.fillStyle = '#fff'; ctx.fill();

      if (qrCanvas) {
        ctx.drawImage(qrCanvas, qrX, qrY, qrSize, qrSize);
      } else {
        drawPlaceholderQR(ctx, qrX, qrY, qrSize);
      }

      // 扫码提示
      ctx.font = '18px "PingFang SC", sans-serif';
      ctx.fillStyle = '#aaa'; ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText('\u626B\u7801\u67E5\u770B\u4ECA\u65E5\u8D44\u8BAF', qrX + qrSize / 2, qrY + qrSize + 14);

      // 导出 2x 高清
      var outW = Math.round(W / 2), outH = Math.round(H / 2);
      var out = document.createElement('canvas');
      out.width = outW; out.height = outH;
      out.getContext('2d').drawImage(canvas, 0, 0, outW, outH);
      return out.toDataURL('image/png', 0.95);
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
    cx.fillStyle = '#fff'; cx.fillRect(0,0,size,size);
    df(mg,mg,cs); df(mg+(N-7)*cs,mg,cs); df(mg,mg+(N-7)*cs,cs);
    for (var r = 0; r < N; r++) for (var col = 0; col < N; col++) {
      if ((r<8&&col<8)||(r<8&&col>N-9)||(r>N-9&&col<8)) continue;
      if (mods[r*N+col]) { cx.fillStyle='#222'; cx.fillRect(mg+col*cs,mg+r*cs,Math.max(1,cs-1),Math.max(1,cs-1)); }
    }
    ctx.drawImage(c, x, y, size, size);
  }

  // ==================== 弹窗逻辑 ====================

  function openModal() {
    var modal = document.getElementById('share-modal');
    if (!modal) {
      modal = document.createElement('div');
      modal.id = 'share-modal'; modal.className = 'share-modal';
      modal.innerHTML =
        '<div class="share-modal-content">' +
          '<div class="share-modal-header"><span class="share-modal-title">\u751F\u6210\u5206\u4EAB\u5361\u7247</span>' +
          '<button class="share-modal-close" id="share-modal-close">&times;</button></div>' +
          '<div class="share-modal-body" id="share-modal-body">' +
            '<div class="share-loading"><span class="share-spinner"></span>\u6B63\u5728\u751F\u6210\u5361\u7247...</div>' +
          '</div></div>';
      document.body.appendChild(modal);
      document.getElementById('share-modal-close').onclick = closeModal;
      modal.onclick = function (e) { if (e.target === modal) closeModal(); };
    }
    modal.classList.add('active');
    document.getElementById('share-modal-body').innerHTML =
      '<div class="share-loading"><span class="share-spinner"></span>\u6B63\u5728\u751F\u6210\u5361\u7247...</div>';

    setTimeout(function () {
      if (!currentData) {
        document.getElementById('share-modal-body').innerHTML =
          '<p style="color:#86909c;padding:40px 20px;text-align:center">\u6570\u636E\u52A0\u8F7D\u4E2D\uFF0C\u8BF7\u7A0D\u540E\u91CD\u8BD5</p>';
        return;
      }
      generateImage(currentData).then(function (url) {
        document.getElementById('share-modal-body').innerHTML =
          '<div class="share-preview-wrap"><img src="' + url + '" alt="\u5206\u4EAB\u5361\u7247" style="width:100%;border-radius:12px;display:block"></div>' +
          '<p style="color:#86909c;font-size:13px;margin-top:12px;text-align:center">\u957F\u630F\u4FDD\u5B56\u56FE\u7247\uFF0C\u6216\u70B9\u51FB\u4E0B\u65B9\u6309\u94AE</p>' +
          '<div class="share-actions">' +
            '<button class="share-action-btn share-save-btn" id="share-save-btn">\uD83D\uDCBE \u4FDD\u5B58\u56FE\u7247</button>' +
            '<button class="share-action-btn share-copy-btn" id="share-copy-link">\uD83D\uDD17 \u590D\u5236\u94FE\u63A5</button>' +
          '</div>';
        document.getElementById('share-save-btn').onclick = function () {
          var a = document.createElement('a');
          a.href = url; a.download = (currentData.date || '') + '_\u6BCF\u65E5\u91D1\u53E5.png';
          a.click();
        };
        document.getElementById('share-copy-link').onclick = function () {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(currentUrl).then(function () {
              var btn = document.getElementById('share-copy-link');
              btn.textContent = '\u2705 \u5DF2\u590D\u5236';
              setTimeout(function () { btn.textContent = '\uD83D\uDD17 \u590D\u5236\u94FE\u63A5'; }, 2000);
            });
          } else { prompt('\u590D\u5236\u94FE\u63A5\uFF1A', currentUrl); }
        };
      }).catch(function (e) {
        console.error('[ShareCard]', e);
        document.getElementById('share-modal-body').innerHTML =
          '<p style="color:#e0457b;padding:40px 20px;text-align:center">\u751F\u6210\u5931\u8D25\uFF1A' + e.message + '</p>';
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
