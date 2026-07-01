# GitHub Actions 部署说明（替代本地「每日自动运行.sh」）

本文件说明如何把每天的「爬取 → AI 摘要 → 构建网页 → 发布」流程，从**本地机器 cron / 手动跑 `每日自动运行.sh`**，迁移到 **GitHub Actions 定时任务**，实现零本地依赖、全自动。

工作流文件：`.github/workflows/daily-news.yml`

---

## 一、它做了什么（等价于 每日自动运行.sh 的三步）

1. 采集今日资讯：`每日资讯skill/run.py`（公众号 RSS + 监控源3 网站 → AI 摘要 → 生成 docx）
2. 构建网页数据：`信息日报/build/build_all.py`（AI 聚合 10 条线索 + 分类标签 + 跨期追踪线 + 全局索引）
3. 提交 `信息日报/web/data/` 并 `git push` → 触发 Vercel 自动部署

默认每天 **北京时间 07:00**（cron `0 23 * * *` 为 UTC）运行，也可在仓库 Actions 页面点「Run workflow」手动触发。

---

## 二、一次性配置（必须完成，否则无法运行）

### 1. 仓库结构：让整个平台成为 Git 仓库根
当前 `.git` 只在子目录 `信息日报/`（remote 指向 `daily_info`），而爬虫代码 `每日资讯skill/` 和 `公众号监测源.xlsx` 在它**之外**，Actions 检出后拿不到爬虫代码。因此需要让**平台根目录 `信息选题参考平台/` 成为仓库根**。二选一：

- **推荐（新建仓库）**：在 `信息选题参考平台/` 下 `git init`，把整个平台推到一个新的 GitHub 仓库；把 Vercel 项目的 **Root Directory 改为 `信息日报/web`**（Output 目录不变）。原 `信息日报/.git` 可保留作历史备份或删除。
- **保留原仓库**：把 `每日资讯skill/`、`每周资讯skill/`、`公众号监测源.xlsx`、`requirements.txt`、本 workflow 一并纳入原 `daily_info` 仓库（即把仓库根上移到平台根），Vercel Root Directory 同样指向 `信息日报/web`。

> 提示：`.gitignore` 已配置忽略 `系统备份/`、`每日资讯/**/*.docx` 等大体量中间产物，仓库只保留代码与 `信息日报/web/data` 发布数据，保持精简。

### 2. 配置密钥（GitHub Secrets）
仓库 → Settings → Secrets and variables → Actions → New repository secret：

| 名称 | 值 |
|------|----|
| `DEEPSEEK_API_KEY` | 你的 DeepSeek API Key（`sk-...`）|

代码已支持从环境变量 `DEEPSEEK_API_KEY` 直接读取（`auth.py` 的 CI 直通），无需授权码交互。

> `公众号监测源.xlsx` 里的 wechatrss token 已随文件入库，无需额外配置。

### 3. 打开 Actions 写权限
仓库 → Settings → Actions → General → Workflow permissions → 选 **Read and write permissions**（workflow 里也已声明 `permissions: contents: write`）。

---

## 三、常用操作

- 修改运行时间：编辑 `daily-news.yml` 的 `cron`（UTC 时区）。例：北京时间 08:00 → `0 0 * * *`。
- 临时关闭网站源（只保留公众号）：把 workflow 中 `ENABLE_WEB_SOURCES` 设为 `"0"`。
- 手动补跑：Actions 页面选择本工作流 → Run workflow。

---

## 四、与本地脚本的关系

- `每日自动运行.sh` 仍可在本地使用（逻辑不变）；上云后本地不再是必需。
- `每周自动运行.sh`（每周资讯）目前仍为本地脚本，如需上云可按本 workflow 同样方式新增一个 `weekly-news.yml`（`cron` 设为每周一次，步骤改为 `cd 每周资讯skill && python run.py --last-week`）。
