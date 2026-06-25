/**
 * 分享生图 - 信息日报卡片版 v4
 * 内容：蓝色头部 + 数据统计 + 线索列表 + 词云 + 真实二维码 + 蓝色底部
 */
(function () {
  var currentData = null;
  var currentUrl = '';

  // 设计基准：2x 高清绘制，导出时缩放到 750 宽
  var SCALE = 2;
  var W = 750;
  var DRAW_W = W * SCALE;
  var PX = 48 * SCALE;
  var HDR_H = 75 * SCALE;
  var FTR_H = 75 * SCALE;
  var QR_SIZE = 170 * SCALE;
  var MAX_CLUE = 5;

  // 词云尺寸：高度同二维码，宽度为二维码2倍
  var CLOUD_W = QR_SIZE * 2;
  var CLOUD_H = QR_SIZE;

  // 字号
  var FS_TITLE = 32 * SCALE;
  var FS_SUBTITLE = 20 * SCALE;
  var FS_SECTION = 26 * SCALE;
  var FS_STATS = 24 * SCALE;
  var FS_CLUE_T = 28 * SCALE;
  var FS_CLUE_S = 22 * SCALE;
  var FS_HINT = 18 * SCALE;
  var FS_FTR_TITLE = 22 * SCALE;
  var FS_FTR_URL = 16 * SCALE;
  var FS_QR_TIP = 15 * SCALE;
  var CLUE_BLOCK_H = 100 * SCALE;

  // 停用词（无意义常用语 + 通用商业/数字词汇）
  var STOP_WORDS = [
    '的','了','在','是','我','有','和','就','不','人','都','一','一个','上','也','很','到','说',
    '要','去','你','会','着','没有','看','好','自己','这','他','她','它','们','那','些','什么',
    '怎么','如何','为什么','可以','已经','还是','因为','所以','但是','如果','这个','那个','这些','那些',
    '被','把','从','对','与','及','等','或','以','为','于','中','其','将','及','与','和','等',
    '进行','实现','提供','基于','通过','包括','涉及','相关','主要','重要','关键','核心','整体',
    '研究','分析','显示','认为','表示','指出','报道','发布','透露','消息','资讯','信息','数据',
    '企业','公司','市场','行业','技术','产品','用户','客户','平台','系统','服务','业务','项目',
    '中国','国际','全球','国内','海外','国外','记者','编辑','来源','标题','内容','摘要','全文',
    '年','月','日','号','版','次','个','条','款','项','种','类','型','级','期','篇','份','本',
    'AI','ai','AIGC','aigc',
    // 新增：数字/金额类
    '亿元','亿美元','万亿','千亿','百亿','十亿','亿','万','万元','万美元',
    '收入','亿元收入','美元','人民币','融资','估值','市值','股价','亏损','盈利','净利润','营收',
    // 新增：通用动词/名词
    '动力','能力','趋势','影响','挑战','机遇','问题','情况','状态','水平','规模','速度','效率',
    '增长','下降','上升','下跌','增加','减少','提升','降低','扩大','缩小','加快','放缓',
    '时间','期间','计划','目标','方向','路径','方案','模式','机制','体系','环境','条件','因素',
    '推出','发布','宣布','表示','称','透露','回应','否认','确认','预计','计划','启动','完成',
    '报告','预测','估计','统计','调查','监测','评估','测试','试验','应用','落地','部署','运行'
  ];

  function truncate(text, max) {
    if (!text) return '';
    return text.length <= max ? text : text.substring(0, max) + '...';
  }

  function formatChineseDate(ds, wd) {
    var p = (ds || '').split('-');
    if (p.length !== 3) return ds;
    return p[0] + '年' + parseInt(p[1], 10) + '月' + parseInt(p[2], 10) + '日' + (wd ? ' ' + wd : '');
  }

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

  // ==================== 词云生成 ====================

  /**
   * 从线索数据中提取有意义的高频词
   * 返回 [{text, weight}]，按权重排序
   */
  function extractKeywords(data) {
    var clues = data.clues || [];
    var text = '';
    for (var i = 0; i < clues.length; i++) {
      var cl = clues[i];
      if (cl.title) text += cl.title + ' ';
      if (cl.summary) text += cl.summary + ' ';
      if (cl.topics) {
        for (var t = 0; t < cl.topics.length; t++) text += cl.topics[t] + ' ';
      }
      if (cl.sources) {
        for (var s = 0; s < cl.sources.length; s++) {
          if (cl.sources[s].title) text += cl.sources[s].title + ' ';
        }
      }
    }

    // 分词：提取2-4字的中文词组
    var words = {};
    var len = text.length;

    // 先提取英文词组（连续字母）
    var enRe = /[A-Za-z]{2,}/g;
    var enMatch;
    while ((enMatch = enRe.exec(text)) !== null) {
      var w = enMatch[0].toLowerCase();
      if (STOP_WORDS.indexOf(w) === -1 && w.length >= 2) {
        words[w] = (words[w] || 0) + 3; // 英文词权重更高
      }
    }

    // 中文：滑动窗口提取2-4字词
    for (var n = 2; n <= 4; n++) {
      for (var j = 0; j <= len - n; j++) {
        var seg = text.substring(j, j + n);
        // 检查是否全是中文字符
        if (!/^[\u4e00-\u9fff]+$/.test(seg)) continue;
        if (STOP_WORDS.indexOf(seg) !== -1) continue;
        // 检查是否包含标点
        if (/[，。！？、；：""''（）《》\s\d]/.test(seg)) continue;
        words[seg] = (words[seg] || 0) + 1;
      }
    }

    // 转成数组并排序
    var result = [];
    for (var w2 in words) {
      if (words[w2] >= 2) { // 至少出现2次
        result.push({ text: w2, weight: words[w2] });
      }
    }
    result.sort(function (a, b) { return b.weight - a.weight; });

    // 取前 20 个
    return result.slice(0, 20);
  }

  /**
   * 在 canvas 上绘制词云（随机排布，不重叠，大词居中，大小随频率变化）
   * 布局：大词优先放在中心区域，小词随机放在周围空隙
   * ctx: 目标 canvas context
   * x, y: 词云区域左上角坐标
   * cw, ch: 词云宽高
   * keywords: [{text, weight}] 按权重降序排列
   */
  function drawWordCloud(ctx, x, y, cw, ch, keywords) {
    if (!keywords || !keywords.length) return;

    var colors = [
      '#0a3fbf', '#0d4fcc', '#1664ff', '#1d6bff',
      '#2678ff', '#3d8bff', '#4986ff', '#5a9aff',
      '#6ba5ff', '#7eb4ff', '#90c0ff', '#a3ccff'
    ];

    var maxW = keywords[0].weight;
    var minW = keywords[keywords.length - 1].weight;
    // 字号翻倍：18-44px（2x放大后 36-88px 绘制，导出后 18-44px）
    var maxFont = Math.round(44 * SCALE);
    var minFont = Math.round(14 * SCALE);

    // 计算每个词的字号和尺寸
    var items = [];
    for (var k = 0; k < keywords.length; k++) {
      var kw = keywords[k];
      var ratio = (maxW === minW) ? 1 : ((kw.weight - minW) / (maxW - minW));
      var fontSize = Math.round(minFont + Math.pow(ratio, 0.6) * (maxFont - minFont));
      ctx.font = 'bold ' + fontSize + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
      var tw = ctx.measureText(kw.text).width;
      items.push({
        text: kw.text,
        fontSize: fontSize,
        textW: tw + 6 * SCALE,
        textH: fontSize + 4 * SCALE,
        color: colors[k % colors.length],
        weight: kw.weight
      });
    }

    // 排布策略：大词(前30%)放中心区域，其余随机放周围
    var placedBoxes = [];  // [{x, y, w, h}]
    var padX = 8 * SCALE;
    var padY = 8 * SCALE;
    var centerX = x + cw / 2;
    var centerY = y + ch / 2;
    var GAP = 5 * SCALE;  // 词之间最小间距

    // 把 items 分成两组：大词（前30%）放中心，小词放周围
    var bigCount = Math.max(1, Math.ceil(items.length * 0.3));
    var bigItems = items.slice(0, bigCount);
    var smallItems = items.slice(bigCount);

    // 辅助：在区域内随机找不重叠位置
    function findSpot(w, h, biasCenter) {
      var attempts = 0;
      var maxAttempts = 600;
      while (attempts < maxAttempts) {
        var rx, ry;
        if (biasCenter) {
          // 偏向中心：高斯分布
          var u1 = Math.random(), u2 = Math.random();
          var gauss = Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2);
          rx = centerX + gauss * (cw / 4) - w / 2;
          ry = centerY + gauss * (ch / 4) - h / 2;
        } else {
          rx = x + padX + Math.random() * (cw - w - padX * 2);
          ry = y + padY + Math.random() * (ch - h - padY * 2);
        }
        // 边界检查
        if (rx < x + padX) rx = x + padX;
        if (ry < y + padY) ry = y + padY;
        if (rx + w > x + cw - padX) rx = x + cw - w - padX;
        if (ry + h > y + ch - padY) ry = y + ch - h - padY;

        var collision = false;
        for (var b = 0; b < placedBoxes.length; b++) {
          var box = placedBoxes[b];
          if (rx < box.x + box.w + GAP && rx + w > box.x - GAP &&
              ry < box.y + box.h + GAP && ry + h > box.y - GAP) {
            collision = true;
            break;
          }
        }
        if (!collision) return { x: rx, y: ry };
        attempts++;
      }
      // 找不到位置就强制放左上角
      return { x: x + padX, y: y + padY };
    }

    // 先放大词（居中偏向）
    for (var bi = 0; bi < bigItems.length; bi++) {
      var bit = bigItems[bi];
      var spot = findSpot(bit.textW, bit.textH, true);
      placedBoxes.push({ x: spot.x, y: spot.y, w: bit.textW, h: bit.textH });
      bit.px = spot.x;
      bit.py = spot.y + bit.textH / 2;
    }

    // 再放小词（随机位置）
    for (var si = 0; si < smallItems.length; si++) {
      var sit = smallItems[si];
      var spot2 = findSpot(sit.textW, sit.textH, false);
      placedBoxes.push({ x: spot2.x, y: spot2.y, w: sit.textW, h: sit.textH });
      sit.px = spot2.x;
      sit.py = spot2.y + sit.textH / 2;
    }

    // 统一绘制
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    for (var di = 0; di < items.length; di++) {
      var it2 = items[di];
      ctx.font = 'bold ' + it2.fontSize + 'px "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = it2.color;
      ctx.fillText(it2.text, it2.px, it2.py);
    }

    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
  }

  // ==================== 二维码生成 ====================

  function generateQRCanvas(text, size) {
    return new Promise(function (resolve) {
      if (!window.QRCode) { resolve(null); return; }
      try {
        var container = document.createElement('div');
        document.body.appendChild(container);
        var qrcode = new QRCode(container, {
          text: text, width: size, height: size,
          colorDark: '#111', colorLight: '#ffffff',
          correctLevel: window.QRCode.CorrectLevel.M, useSVG: false
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
    var cloudW = CLOUD_W;
    var cloudH = CLOUD_H;

    // 提取关键词
    var keywords = extractKeywords(data);

    // 计算总高度
    var contentH = MAX_CLUE * CLUE_BLOCK_H;
    var extraHintH = (clues.length > MAX_CLUE) ? (50 * SCALE) : (20 * SCALE);
    var H = HDR_H + 15*SCALE + 45*SCALE + 40*SCALE + 34*SCALE + 50*SCALE + contentH + extraHintH + 15*SCALE + Math.max(qrSize, cloudH) + 18*SCALE + FTR_H;

    return generateQRCanvas(currentUrl, qrSize).then(function (qrCanvas) {
      var canvas = document.createElement('canvas');
      canvas.width = DRAW_W; canvas.height = H;
      var ctx = canvas.getContext('2d');

      // ===== 白色背景 =====
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, DRAW_W, H);

      // ===== 蓝色渐变头部 =====
      var gTop = ctx.createLinearGradient(0, 0, DRAW_W, 0);
      gTop.addColorStop(0, '#1664ff'); gTop.addColorStop(1, '#0a3fbf');
      ctx.fillStyle = gTop;
      roundRectPath(ctx, 0, 0, DRAW_W, HDR_H, { br: 18*SCALE, bl: 18*SCALE });
      ctx.fill();

      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.font = 'bold ' + FS_TITLE + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#fff';
      ctx.fillText('信息选题参考', DRAW_W / 2, HDR_H * 0.35);
      ctx.font = FS_SUBTITLE + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.85)';
      ctx.fillText(formatChineseDate(dateStr, weekday), DRAW_W / 2, HDR_H * 0.68);

      var y = HDR_H + 15 * SCALE;

      // ===== 数据统计区块 =====
      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      ctx.font = 'bold ' + FS_SECTION + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#1664ff';
      ctx.fillText('\uD83D\uDCCA 本期信息', PX, y);

      y += 42 * SCALE;
      ctx.font = FS_STATS + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#333';
      var parts = [];
      if (stats.total) parts.push('筛选资讯 ' + stats.total + ' 条');
      if (stats.selected) parts.push('相关内容 ' + stats.selected + ' 条');
      if (stats.clues) parts.push('聚合线索 ' + stats.clues + ' 条');
      ctx.fillText(parts.join('   |   '), PX, y);

      // 分隔线
      y += 36 * SCALE;
      ctx.strokeStyle = '#e5e6eb'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(PX, y); ctx.lineTo(DRAW_W - PX, y); ctx.stroke();

      // ===== 今日热点区块 =====
      y += 38 * SCALE;
      ctx.font = 'bold ' + FS_SECTION + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#1664ff';
      ctx.fillText('\uD83D\uDD25 今日热点', PX, y);

      // 线索列表
      y += 52 * SCALE;
      var showCount = Math.min(clues.length, MAX_CLUE);
      for (var i = 0; i < showCount; i++) {
        var cl = clues[i];
        if (!cl) continue;
        ctx.font = 'bold ' + FS_CLUE_T + 'px "PingFang SC", sans-serif';
        ctx.fillStyle = '#1d2129';
        ctx.fillText((i + 1) + '. ' + truncate(cl.title, 22), PX, y);
        var sumText = cl.summary || '';
        var sumLine1 = truncate(sumText, 28);
        var sumLine2 = truncate((sumText || '').slice(28), 28);
        y += 36 * SCALE;
        ctx.font = FS_CLUE_S + 'px "PingFang SC", sans-serif';
        ctx.fillStyle = '#555';
        ctx.fillText(sumLine1, PX + 20 * SCALE, y);
        if (sumLine2) {
          y += 28 * SCALE;
          ctx.fillText(sumLine2, PX + 20 * SCALE, y);
          y += 36 * SCALE;
        } else {
          y += 64 * SCALE;
        }
      }

      // 还有更多提示
      if (clues.length > MAX_CLUE) {
        y += 12 * SCALE;
        ctx.font = FS_HINT + 'px "PingFang SC", sans-serif';
        ctx.fillStyle = '#86909c';
        ctx.fillText('... 还有 ' + (clues.length - MAX_CLUE) + ' 条线索，扫码查看完整版', PX, y);
        y += 44 * SCALE;
      } else {
        y += 14 * SCALE;
      }

      // ===== 底部区域：左侧词云 + 右侧二维码 =====
      var botAreaY = y + 15 * SCALE;
      var botAreaH = Math.max(qrSize, cloudH) + 20 * SCALE;

      // 左侧词云（无背景）
      var cloudX = PX;
      var cloudY = botAreaY + (botAreaH - cloudH) / 2;

      drawWordCloud(ctx, cloudX, cloudY, cloudW, cloudH, keywords);

      // 右侧二维码
      var qrX = DRAW_W - PX - qrSize;
      var qrY = botAreaY + (botAreaH - qrSize) / 2;

      // 安全校验
      if (botAreaY + botAreaH > H - FTR_H - 10 * SCALE) {
        botAreaH = H - FTR_H - botAreaY - 10 * SCALE;
        qrY = botAreaY + (botAreaH - qrSize) / 2;
        cloudY = botAreaY + (botAreaH - cloudH) / 2;
      }

      roundRectPath(ctx, qrX - 6*SCALE, qrY - 6*SCALE, qrSize + 12*SCALE, qrSize + 12*SCALE, 12*SCALE);
      ctx.fillStyle = '#f8f8f8'; ctx.fill();

      if (qrCanvas) {
        ctx.drawImage(qrCanvas, qrX, qrY, qrSize, qrSize);
      } else {
        drawPlaceholderQR(ctx, qrX, qrY, qrSize);
      }

      ctx.font = FS_QR_TIP + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#86909c';
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      ctx.fillText('扫码查看完整资讯', qrX + qrSize / 2, qrY + qrSize + 20 * SCALE);

      // ===== 底部蓝色渐变区 =====
      var botY = H - FTR_H;
      var gBot = ctx.createLinearGradient(0, botY, DRAW_W, botY);
      gBot.addColorStop(0, '#1664ff'); gBot.addColorStop(1, '#0a3fbf');
      ctx.fillStyle = gBot;
      roundRectPath(ctx, 0, botY, DRAW_W, FTR_H, { tr: 18*SCALE, tl: 18*SCALE });
      ctx.fill();

      ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      ctx.font = 'bold ' + FS_FTR_TITLE + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = '#fff';
      ctx.fillText('信息选题日报', PX, botY + 28 * SCALE);
      ctx.font = FS_FTR_URL + 'px "PingFang SC", sans-serif';
      ctx.fillStyle = 'rgba(255,255,255,0.72)';
      ctx.fillText('dailyinfox.cn', PX, botY + 50 * SCALE);

      // ===== 导出 =====
      var outW = W;
      var outH = Math.round(H / SCALE);
      var out = document.createElement('canvas');
      out.width = outW; out.height = outH;
      var outCtx = out.getContext('2d');
      outCtx.imageSmoothingEnabled = true;
      outCtx.imageSmoothingQuality = 'high';
      outCtx.drawImage(canvas, 0, 0, outW, outH);
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
          a.href = url; a.download = (currentData.date || '') + '_信息选题.jpg';
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
