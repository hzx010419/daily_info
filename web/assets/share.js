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
   * 高质量中文分词 + 高频词提取
   * 策略：
   *  1. 先提取英文专有名词（连续字母/数字，如 OpenAI、AI、Meta）
   *  2. 中文：优先提取 topics 里的标签（已有准确分词），再从 title/summary 里用滑动窗口补充
   *  3. 严格过滤：停用词 + 长度1的词 + 包含无意义片段的词
   *  4. 合并同词根（如「AI就业」和「AI」都出现时保留权重高的）
   * 返回 [{text, weight}]，按权重降序
   */
  function extractKeywords(data) {
    var clues = data.clues || [];
    var words = {};  // {word: weight}

    // ---- 1. 先把 topics 里的标签直接加入（最准确的分词来源）----
    for (var i = 0; i < clues.length; i++) {
      var topics = clues[i].topics || [];
      for (var t = 0; t < topics.length; t++) {
        var tp = topics[t];
        if (tp && STOP_WORDS.indexOf(tp) === -1) {
          words[tp] = (words[tp] || 0) + 5;  // topics 权重最高
        }
      }
    }

    // ---- 2. 从 title 和 summary 提取有意义的词组 ----
    // 先收集所有文本
    var allText = '';
    for (var i2 = 0; i2 < clues.length; i2++) {
      if (clues[i2].title) allText += clues[i2].title + ' ';
      if (clues[i2].summary) allText += clues[i2].summary + ' ';
      var srcs = clues[i2].sources || [];
      for (var s2 = 0; s2 < srcs.length; s2++) {
        if (srcs[s2].title) allText += srcs[s2].title + ' ';
      }
    }

    // 提取英文专有名词（连续字母，可能带数字）
    var enRe = /[A-Za-z][A-Za-z0-9]{1,}/g;
    var enMatch;
    while ((enMatch = enRe.exec(allText)) !== null) {
      var ew = enMatch[0];
      // 过滤纯数字开头或太短的
      if (ew.length < 2) continue;
      var ewl = ew.toLowerCase();
      if (STOP_WORDS.indexOf(ewl) === -1) {
        words[ew] = (words[ew] || 0) + 4;
      }
    }

    // 中文分词：用常见实体词表 + 滑动窗口
    // 先定义一批高质量实体词（这些词如果出现就直接计数，不做滑动窗口）
    var ENTITY_WORDS = [
      // AI/科技
      '人工智能','大模型','生成式AI','机器学习','深度学习','神经网络','自然语言处理',
      '智能体','Agent','多模态','算力','芯片','GPU','NPU','推理','训练',
      // 企业
      'OpenAI','Anthropic','谷歌','Google','微软','Microsoft','苹果','Apple',
      'Meta','亚马逊','Amazon','英伟达','NVIDIA','特斯拉','Tesla',
      '字节跳动','腾讯','阿里','阿里巴巴','百度','京东','美团','华为','小米',
      '智谱','MiniMax','月之暗面','Kimi','通义','文心','讯飞','商汤',
      // 经济/金融
      '通货膨胀','CPI','PPI','GDP','失业率','货币政策','美联储','央行',
      '股价','财报','IPO','融资','估值','市值','营收','净利润','毛利率',
      // 国际
      '美国','中国','欧盟','俄罗斯','乌克兰','以色列','伊朗','法国','德国','日本','印度',
      '达沃斯','硅谷','华尔街',
      // 政策/社会
      '监管','立法','审计','国务院','发改委','工信部',
      '就业','裁员','招聘','工资','社保','养老金',
      // 行业
      '新能源','电动汽车','光伏','电池','储能','医药','生物科技','芯片制造',
      '房地产','基建','消费','零售','物流','供应链'
    ];

    for (var e = 0; e < ENTITY_WORDS.length; e++) {
      var ent = ENTITY_WORDS[e];
      var entRegex = new RegExp(ent.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');
      var matches = allText.match(entRegex);
      if (matches) {
        words[ent] = (words[ent] || 0) + matches.length * 3;
      }
    }

    // 中文滑动窗口：只提取2字词和3字词，事后过滤
    var len = allText.length;
    for (var n = 2; n <= 3; n++) {
      for (var j = 0; j <= len - n; j++) {
        var seg = allText.substring(j, j + n);
        if (!/^[\u4e00-\u9fff]+$/.test(seg)) continue;
        if (STOP_WORDS.indexOf(seg) !== -1) continue;
        // 过滤包含数字或标点的
        if (/[\d，。！？、；：""''（）《》\s]/.test(seg)) continue;
        words[seg] = (words[seg] || 0) + 1;
      }
    }

    // ---- 3. 后过滤：去掉太短、无意义、或包含停用词片段的词 ----
    var filtered = {};
    for (var w3 in words) {
      var ww = w3;
      // 长度检查：中文至少2字，英文至少2字母
      if (/^[\u4e00-\u9fff]+$/.test(ww) && ww.length < 2) continue;
      if (/^[A-Za-z]+$/.test(ww) && ww.length < 2) continue;
      // 去掉纯数字
      if (/^\d+$/.test(ww)) continue;
      // 去掉包含停用词的2字词（大部分2字词如果是停用词已被过滤，这里是双重保险）
      if (ww.length === 2 && STOP_WORDS.indexOf(ww) !== -1) continue;
      // 去掉权重太低但长度很长的词（可能是乱切的）
      if (ww.length >= 4 && words[ww] < 2) continue;
      filtered[ww] = words[ww];
    }

    // ---- 4. 转数组、排序、去重（保留权重最高的） ----
    var result = [];
    for (var w4 in filtered) {
      result.push({ text: w4, weight: filtered[w4] });
    }
    result.sort(function (a, b) { return b.weight - a.weight; });

    // 取前 20 个
    return result.slice(0, 20);
  }

  /**
   * 在 canvas 上绘制词云（大词先排居中，小词插空，严格不重叠）
   * 排布顺序：按权重降序，大词优先放中心，小词在剩余空间找位置
   * ctx: 目标 canvas context
   * x, y: 词云区域左上角坐标
   * cw, ch: 词云宽高
   * keywords: [{text, weight}] 按权重降序排列（已取前N个）
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
    var maxFont = Math.round(44 * SCALE);
    var minFont = Math.round(14 * SCALE);

    // 预计算每词的字号和尺寸
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
        textW: tw + 8 * SCALE,
        textH: fontSize + 6 * SCALE,
        color: colors[k % colors.length]
      });
    }

    var placedBoxes = [];  // [{x, y, w, h}]
    var padX = 10 * SCALE;
    var padY = 10 * SCALE;
    var GAP = 6 * SCALE;  // 词之间最小间距
    var centerX = x + cw / 2;
    var centerY = y + ch / 2;

    /**
     * 在指定区域内找一个不重叠的位置
     * 优先在 centerArea 附近搜索，搜不到再到整个区域搜
     */
    function findPosition(w, h, preferX, preferY) {
      var maxAttempts = 800;
      // 先在以(preferX, preferY)为中心的范围内搜索
      for (var attempt = 0; attempt < maxAttempts; attempt++) {
        var rx, ry;
        if (attempt < 400) {
          // 高斯分布偏向偏好点
          var u1 = Math.random(), u2 = Math.random();
          var g = Math.sqrt(-2 * Math.log(u1 + 1e-10)) * Math.cos(2 * Math.PI * u2);
          rx = preferX + g * (cw / 3) - w / 2;
          ry = preferY + g * (ch / 3) - h / 2;
        } else {
          // 随机位置
          rx = x + padX + Math.random() * (cw - w - padX * 2);
          ry = y + padY + Math.random() * (ch - h - padY * 2);
        }
        // 边界约束
        rx = Math.max(x + padX, Math.min(rx, x + cw - w - padX));
        ry = Math.max(y + padY, Math.min(ry, y + ch - h - padY));

        var ok = true;
        for (var b = 0; b < placedBoxes.length; b++) {
          var box = placedBoxes[b];
          if (!(rx + w + GAP <= box.x || rx >= box.x + box.w + GAP ||
                ry + h + GAP <= box.y || ry >= box.y + box.h + GAP)) {
            ok = false; break;
          }
        }
        if (ok) return { x: rx, y: ry };
      }
      // 实在找不到就放左上角（会重叠但总比没有好）
      return { x: x + padX, y: y + padY };
    }

    // 第1步：把最大的词放在正中心
    if (items.length > 0) {
      var first = items[0];
      var fx = centerX - first.textW / 2;
      var fy = centerY - first.textH / 2;
      // 边界检查
      fx = Math.max(x + padX, Math.min(fx, x + cw - first.textW - padX));
      fy = Math.max(y + padY, Math.min(fy, y + ch - first.textH - padY));
      placedBoxes.push({ x: fx, y: fy, w: first.textW, h: first.textH });
      first.px = fx;
      first.py = fy + first.textH / 2;
    }

    // 第2步：按权重降序，依次放置剩余词
    // 大词偏向中心，小词在任何可用位置
    for (var idx = 1; idx < items.length; idx++) {
      var it = items[idx];
      // 前30%的词偏向中心放置，其余在任何位置
      var biasCenter = idx < Math.ceil(items.length * 0.3);
      var spot = findPosition(it.textW, it.textH,
        biasCenter ? centerX : x + padX + Math.random() * (cw - it.textW),
        biasCenter ? centerY : y + padY + Math.random() * (ch - it.textH)
      );
      placedBoxes.push({ x: spot.x, y: spot.y, w: it.textW, h: it.textH });
      it.px = spot.x;
      it.py = spot.y + it.textH / 2;
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
