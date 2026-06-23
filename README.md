# 信息日报（写作线索日报）

腾讯研究院写作线索日报 · 网页版

## 目录结构

```
信息日报/
├── build/              # 数据生成脚本（Python）
├── web/                # 静态网页（纯前端）
│   ├── index.html      # 首页（往期归档）
│   ├── issue.html      # 每期详情
│   ├── assets/         # CSS、JS 文件
│   └── data/           # 生成的 JSON 数据
└── .github/            # GitHub Actions 配置
```

## 本地预览

```bash
cd web
python3 -m http.server 8765
# 浏览器打开 http://localhost:8765/index.html
```

## 自动更新流程

1. 本地运行 `每日资讯skill/run.py` 生成 Word 文档
2. 运行 `写作线索日报/build/build_all.py` 生成 JSON 数据
3. 推送到 GitHub
4. Vercel 自动部署

## 部署

已部署到 Vercel：[添加你的 Vercel 链接]
