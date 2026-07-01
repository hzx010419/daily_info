# 信息日报（网页端 · 部署仓库）

腾讯研究院信息选题参考 · 网页版。本目录是**唯一的网页构建 + 部署目录**
（已合并原「写作线索日报」的构建脚本，不再需要跨目录 cp 复制）。

## 目录结构

```
信息日报/
├── build/              # 数据生成脚本（Python）
│   ├── build_all.py    # 批量编排：扫描 docx → AI 聚合 → 写 web/data
│   ├── aggregate.py    # 单期 AI 聚合为 10 条写作线索（复用 每日资讯skill 的 DeepSeek 客户端）
│   └── docx_parser.py  # 解析每日资讯 docx（含超链接还原）
├── web/                # 静态网页（纯前端）
│   ├── index.html      # 首页（往期归档）
│   ├── issue.html      # 每期详情
│   ├── assets/         # CSS、JS（含分享 share.js、og-image）
│   └── data/           # 生成的 JSON 数据 + docs/（docx）
└── .github/            # GitHub Actions 配置
```

## 本地预览

```bash
cd web
python3 -m http.server 8765
# 浏览器打开 http://localhost:8765/index.html
```

## 数据构建

```bash
cd build
python3 build_all.py            # 增量：已生成期次自动跳过
python3 build_all.py --force     # 全量重建
python3 build_all.py --date 2026-06-30   # 只重建指定日期
```

`build_all.py` 会自动定位平台根目录下的 `每日资讯/`（读 docx）与本目录 `web/data/`（写 JSON），
并通过 `每日资讯skill/src` 复用 DeepSeek 客户端与授权模块。

## 自动更新流程（由平台根目录 `每日自动运行.sh` 编排）

1. `每日资讯skill/run.py` 爬取生成当日 Word 文档 → `每日资讯/`
2. `信息日报/build/build_all.py` 解析 + AI 聚合 → `web/data/*.json`
3. `git push origin main` → GitHub → Vercel 自动部署

## 部署

已连接 GitHub 远端 `daily_info`，push 后由 Vercel 自动部署。
