# 每日资讯Skill

> **🤖 致 AI 助手**：本项目已配备专用导航文件，请优先阅读以下两个文件再进行任何修改，**避免全文件扫描浪费 token**：
> - [`AGENTS.md`](./AGENTS.md) — 项目高层认知地图（目标 / 流水线 / 修改路径指引 / 已知坑点）
> - [`PROJECT_MAP.md`](./PROJECT_MAP.md) — 符号级代码地图（类 / 函数签名 / 行号定位）
>
> 修改后请按 `AGENTS.md` §9 的维护规则同步更新这两份文件。

基于DeepSeek AI的微信公众号RSS内容聚合工具，自动抓取、过滤广告、生成摘要、去重整理。

## 功能特性

- **RSS订阅源管理**: 支持Excel配置多个公众号RSS链接
- **智能内容过滤**: AI判断并过滤广告内容
- **自动摘要生成**: DeepSeek AI生成400-500字内容摘要
- **智能去重**: Embedding相似度检测 + AI筛选，合并同一事件报道
- **反爬应对**: requests快速获取 + Playwright浏览器模拟兜底，100%解决403问题
- **Word文档输出**: 格式精美的每日资讯汇总文档

## 安装步骤

### 1. 克隆/复制项目

将整个`每日资讯skill`文件夹复制到目标机器。

### 2. 安装Python依赖

```bash
cd 每日资讯skill
pip install -r requirements.txt
```

### 3. 安装Playwright浏览器（可选但推荐）

```bash
pip install playwright
playwright install chromium --with-deps
```

> 不安装也可以使用，但部分被反爬的RSS源可能获取失败

### 4. 配置公众号RSS

编辑Excel文件，格式如下：

| 公众号名称 | RSS链接 |
|-----------|---------|
| 马江博说趋势 | http://rss.jintiankansha.me/rss/GEYDQMRYGN6DGODFGU4TMYRSHBSG4DGM |
| 吴晓波频道 | http://rss.jintiankansha.me/rss/GIZTG7BSGA4GMMTGHA2TSZJVGVSG |

> RSS链接可使用以下服务生成：
> - https://rss.jintiankansha.me
> - https://wechatrss.waytomaster.com
> - https://rsshub.app

### 5. 配置API密钥

本项目已经接入了授权与凭证模块（见 `src/auth.py`），**API 密钥不再写死在源码中**。

- **作者本机**（指纹白名单匹配）：直接 `python run.py`，无任何提示。
- **他人首次运行**：会要求输入
  1. 6 位授权码
  2. 自己的 DeepSeek API 密钥（以 `sk-` 开头）

  通过后凭证会被 PBKDF2 + HMAC-SHA256 加密保存到 `~/.daily_news_skill/credentials.enc`，下次运行自动加载。
- **重置 / 更换密钥**：`python run.py --reauth`

> 获取 DeepSeek API Key: https://platform.deepseek.com/

### 5.1 打包发布给他人时的安全清单（重要）

打包压缩前**务必**确认：

1. ✅ 删除根目录的 `.machine_fingerprint`（含作者本机指纹与预置 Key）
2. ✅ 删除 `cache/`、`logs/`、`筛选记录/` 等运行时产物（参见 `.gitignore`）
3. ✅ 检查源码中没有形如 `sk-xxxxx` 的字符串残留：
   ```bash
   grep -r "sk-[a-zA-Z0-9]\{20,\}" . --exclude-dir=cache --exclude-dir=logs
   ```
4. ✅ 告知接收方："运行时会要求输入授权码 654321（你来提供）+ 他自己的 DeepSeek API Key"

## 使用方法

### 命令行模式

```bash
# 正常模式（使用默认Excel）
python run.py

# 使用自定义Excel文件
python run.py --excel "D:/公众号列表.xlsx"

# 测试模式
python run.py --test

# 详细输出
python run.py --verbose
```

### Python调用模式

```python
import sys
sys.path.insert(0, '每日资讯skill/src')
from main import main

# 使用默认配置运行
success = main()

# 指定自定义Excel文件
success = main("D:/公众号列表.xlsx")
```

## 配置说明

### Excel格式要求

- 文件格式: `.xlsx`
- 必需列: `公众号名称`、`RSS链接`
- 第一行为表头

### RSS链接来源

推荐使用以下RSS生成服务：

| 服务 | 地址 | 备注 |
|-----|------|-----|
| 即刻订阅 | https://rss.jintiankansha.me | 免费，支持大部分公众号 |
| WeChat RSS | https://wechatrss.waytomaster.com | 需要申请 |
| RSSHub | https://rsshub.app | 可自建，支持微信外链 |

## 输出说明

运行后在上级目录生成 `每日资讯/每日资讯_YYYY-MM-DD.docx`：

- 按发布时间倒序排列
- 中文数字序号（一、二、三...）
- 包含：标题、来源、时间、摘要、链接
- 自动过滤广告文章

## 目录结构

```
每日资讯skill/
├── src/
│   ├── main.py          # 主程序
│   ├── auth.py          # 授权与凭证管理（本机识别 / 加密保存 / 交互授权）
│   ├── ai_client.py     # DeepSeek API客户端
│   ├── ai_summarizer.py # 摘要生成
│   ├── content_filter.py# 内容过滤
│   └── utils.py         # 工具函数
├── config/              # 配置文件目录
├── logs/                # 日志目录
├── .machine_fingerprint # 作者本机白名单（仅作者机器持有，发布前必须删除）
├── .gitignore           # 忽略清单
├── requirements.txt     # Python依赖
└── run.py              # 启动脚本（含授权流程）
```

## 常见问题

### Q: 部分RSS获取失败403？
A: 确保已安装Playwright，代码会自动切换浏览器模拟模式获取。

### Q: AI摘要生成失败？
A: 检查DeepSeek API密钥是否正确，网络是否正常。

### Q: 如何添加新的公众号？
A: 在Excel中添加新的公众号名称和RSS链接即可。

### Q: 可以定时自动运行吗？
A: 可以使用Windows任务计划程序或Linux cron定时执行run.py。

## 技术栈

- Python 3.8+
- DeepSeek API (文本生成/Embedding)
- Playwright (浏览器自动化)
- python-docx (Word文档生成)
- pandas (数据处理)
- requests (HTTP请求)
