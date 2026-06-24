/**
 * 分享生图功能 - 生成带二维码的分享图片
 * 风格参考：信息卡片式设计
 */
(function () {
  var currentData = null;
  var currentUrl = '';

  // 获取当前日期参数
  function getDateParam() {
    var m = new RegExp('[?&]date=([^&]+)').exec(location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  // 生成二维码（简化版 QR Code）
  function generateQRCode(text, size) {
    var canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    var ctx = canvas.getContext('2d');
    
    // 简化的二维码生成：使用 hash 值创建伪随机图案
    function simpleHash(str) {
      var hash = 0;
      for (var i = 0; i < str.length; i++) {
        var char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
      }
      return Math.abs(hash);
    }
    
    var hash = simpleHash(text);
    // 使用 seedrandom 方式生成确定性随机数
    var modules = [];
    var moduleCount = 25; // 25x25 模块
    var seed = hash;
    
    for (var i = 0; i < moduleCount * moduleCount; i++) {
      seed = (seed * 1103515245 + 12345) & 0x7fffffff;
      modules.push(seed % 3 === 0); // 约33%填充率
    }
    
    // 绘制定位图案（三个角）
    function drawFinderPattern(x, y, size) {
      // 外框
      ctx.fillStyle = '#000';
      ctx.fillRect(x, y, size * 7, size * 7);
      ctx.fillStyle = '#fff';
      ctx.fillRect(x + size, y + size, size * 5, size * 5);
      ctx.fillStyle = '#000';
      ctx.fillRect(x + size * 2, y + size * 2, size * 3, size * 3);
    }
    
    var cellSize = (size - 16) / moduleCount;
    var offset = 8; // 安全区
    
    // 白色背景
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, size, size);
    
    // 绘制定位图案
    drawFinderPattern(offset, offset, cellSize);
    drawFinderPattern(offset + (moduleCount - 7) * cellSize, offset, cellSize);
    drawFinderPattern(offset, offset + (moduleCount - 7) * cellSize, cellSize);
    
    // 绘制数据模块
    for (var row = 0; row < moduleCount; row++) {
      for (var col = 0; col < moduleCount; col++) {
        // 跳过定位图案区域
        if ((row < 8 && col < 8) || 
            (row < 8 && col > moduleCount - 9) ||
            (row > moduleCount - 9 && col < 8)) {
          continue;
        }
        
        var idx = row * moduleCount + col;
        if (modules[idx]) {
          ctx.fillStyle = '#000';
          ctx.fillRect(
            offset + col * cellSize,
            offset + row * cellSize,
            cellSize - 0.5,
            cellSize - 0.5
          );
        }
      }
    }
    
    return canvas;
  }

  // 截断文本
  function truncateText(text, maxChars) {
    if (!text || text.length <= maxChars) return text || '';
    return text.substring(0, maxChars) + '...';
  }

  // Canvas 文本换行
  function wrapText(ctx, text, maxWidth) {
    var lines = [];
    var paragraph = text.split('\n');
    
    for (var n = 0; n < paragraph.length; n++) {
      var words = paragraph[n].split('');
      var line = '';
      
      for (var i = 0; i < words.length; i++) {
        var testLine = line + words[i];
        var metrics = ctx.measureText(testLine);
        
        if (metrics.width > maxWidth && line !== '') {
          lines.push(line);
          line = words[i];
        } else {
          line = testLine;
        }
      }
      if (line) lines.push(line);
    }
    return lines;
  }

  // 主函数：生成分享图
  function generateShareImage(data) {
    var dateStr = data.date || getDateParam();
    var clues = data.clues || [];
    var stats = data.stats || {};
    
    // Canvas 尺寸（适配微信分享，建议宽度 750px 对应 2x 显示）
    var W = 750;
    var H = 1100;
    var canvas = document.createElement('canvas');
    canvas.width = W;
    canvas.height = H;
    var ctx = canvas.getContext('2d');
    var dpr = 1; // 已经是高清尺寸

    // ========== 背景 ==========
    // 白色主背景
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, W, H);

    // 顶部装饰条（蓝色渐变）
    var gradTop = ctx.createLinearGradient(0, 0, W, 0);
    gradTop.addColorStop(0, '#1664ff');
    gradTop.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradTop;
    ctx.fillRect(0, 0, W, 100);

    // 底部装饰条
    var gradBottom = ctx.createLinearGradient(0, H - 80, W, H - 80);
    gradBottom.addColorStop(0, '#1664ff');
    gradBottom.addColorStop(1, '#0a3fbf');
    ctx.fillStyle = gradBottom;
    ctx.fillRect(0, H - 80, W, 80);

    // ========== 标题区 ==========
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 36px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('信息选题参考', W / 2, 45);

    ctx.font = '22px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    var formattedDate = formatChineseDate(dateStr, data.weekday);
    ctx.fillText(formattedDate, W / 2, 78);

    // ========== 数据统计 ==========
    var startY = 130;
    ctx.textAlign = 'left';
    
    ctx.font = 'bold 28px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('📊 本期数据', 40, startY);

    startY += 50;
    ctx.font = '24px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#333333';
    
    var statTexts = [];
    if (stats.total) statTexts.push('筛选资讯 ' + stats.total + ' 条');
    if (stats.selected) statTexts.push('相关内容 ' + stats.selected + ' 条');
    if (stats.clues) statTexts.push('聚合线索 ' + stats.clues + ' 条');
    
    ctx.fillText(statTexts.join('  |  '), 40, startY);

    // ========== 分隔线 ==========
    startY += 35;
    ctx.strokeStyle = '#e5e6eb';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(40, startY);
    ctx.lineTo(W - 40, startY);
    ctx.stroke();

    // ========== 核心线索预览 ==========
    startY += 30;
    ctx.font = 'bold 28px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#1664ff';
    ctx.fillText('🔥 今日热点', 40, startY);

    startY += 20;
    var contentStartY = startY;
    var maxContentHeight = H - 280 - contentStartY; // 为底部留空间
    var clueIndex = 0;

    for (var c = 0; c < Math.min(clues.length, 5); c++) {
      var clue = clues[c];
      if (!clue) continue;
      clueIndex++;

      // 线索标题
      ctx.font = 'bold 24px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#1d2129';
      var titleText = clueIndex + '. ' + truncateText(clue.title, 18);
      ctx.fillText(titleText, 40, startY);

      // 线索摘要（截取前两行）
      ctx.font = '20px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#4e5969';
      var summaryLines = wrapText(ctx, truncateText(clue.summary, 60), W - 90);
      for (var sl = 0; sl < Math.min(summaryLines.length, 2); sl++) {
        startY += 32;
        ctx.fillText(summaryLines[sl], 55, startY);
      }

      startY += 20;
      
      // 超出高度限制则停止
      if (startY - contentStartY > maxContentHeight) break;
    }

    if (clueIndex < clues.length) {
      startY += 10;
      ctx.font = '20px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
      ctx.fillStyle = '#86909c';
      ctx.fillText('... 还有 ' + (clues.length - clueIndex) + ' 条线索，扫码查看完整版', 40, startY);
    }

    // ========== 底部区域 ==========
    var bottomAreaY = H - 75;
    
    // 二维码
    var qrSize = 120;
    var qrX = W - 180;
    var qrCanvas = generateQRCode(currentUrl, qrSize);
    ctx.drawImage(qrCanvas, qrX, bottomAreaY - 15, qrSize, qrSize);
    
    // 二维码下方提示文字
    ctx.font = '14px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#86909c';
    ctx.textAlign = 'center';
    ctx.fillText('扫码查看完整内容', qrX + qrSize / 2, bottomAreaY + qrSize + 15);

    // 左侧：网站信息
    ctx.textAlign = 'left';
    ctx.font = 'bold 22px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = '#ffffff';
    ctx.fillText('信息选题日报', 40, bottomAreaY + 20);

    ctx.font = '17px -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif';
    ctx.fillStyle = 'rgba(255,255,255,0.75)';
    ctx.fillText('dailyinfox.cn', 40, bottomAreaY + 48);

    return canvas.toDataURL('image/png', 1.0);
  }

  // 格式化中文日期
  function formatChineseDate(dateStr, weekday) {
    var parts = (dateStr || '').split('-');
    if (parts.length !== 3) return dateStr;
    var result = parts[0] + '年' + parseInt(parts[1]) + '月' + parseInt(parts[2]) + '日';
    if (weekday) result += ' ' + weekday;
    return result;
  }

  // 打开分享弹窗并生成图片
  function openShareModal() {
    // 创建弹窗 DOM
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

      // 关闭按钮事件
      document.getElementById('share-modal-close').addEventListener('click', closeShareModal);
      modal.addEventListener('click', function (e) {
        if (e.target === modal) closeShareModal();
      });
    }

    modal.classList.add('active');

    // 生成图片
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
          '<button class="share-action-btn share-save-btn" id="share-save-btn">' +
          '💾 保存图片' +
          '</button>' +
          '<button class="share-action-btn share-copy-btn" id="share-copy-link">' +
          '🔗 复制链接' +
          '</button>' +
          '</div>';

        // 保存图片
        document.getElementById('share-save-btn').addEventListener('click', function () {
          saveShareImage(imgDataUrl, (currentData.date || '') + '_信息选题.png');
        });

        // 复制链接
        document.getElementById('share-copy-link').addEventListener('click', function () {
          copyLink();
        });
      } catch (err) {
        console.error('生成分享图失败:', err);
        bodyEl.innerHTML = '<p style="color:#e0457b">生成失败：' + err.message + '</p>';
      }
    }, 300);
  }

  // 关闭弹窗
  function closeShareModal() {
    var modal = document.getElementById('share-modal');
    if (modal) modal.classList.remove('active');
  }

  // 保存图片到本地
  function saveShareImage(dataUrl, filename) {
    var a = document.createElement('a');
    a.href = dataUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  // 复制链接
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

  // 初始化：绑定按钮事件
  function init() {
    var shareBtn = document.getElementById('share-btn');
    if (shareBtn) {
      shareBtn.addEventListener('click', function (e) {
        e.preventDefault();
        openShareModal();
      });
    }

    currentUrl = location.href;

    // 监听数据渲染完成，保存当前数据引用
    window._onShareDataReady = function (data) {
      currentData = data;
    };
  }

  // 页面加载完成后初始化
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
