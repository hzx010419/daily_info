# 信息选题参考平台

腾讯研究院「每日 / 每周信息选题参考」一体化平台。
从公众号爬取 → AI 摘要去重 → 生成 Word 归档 → AI 聚合写作线索 → 静态网页发布，一条流水线打通。

---

## 一、目录结构

```
信息选题参考平台/
├── 公众号监测源.xlsx        # 唯一数据源（公众号名称 + RSS 链接）
├── requirements.txt         # 统一依赖
├── 每日自动运行.sh           # 主流程：爬取 → 构建网页 → 推送部署
├── 每周自动运行.sh           # 每周资讯生成（读周内每日资讯，去重整合）
│
├── 每日资讯skill/            # 【上游】爬取 + AI 摘要 + 生成每日 docx
│   ├── run.py               #   启动入口
│   ├── src/                 #   main.py / ai_client.py(DeepSeek) / auth.py(授权) ...
│   ├── config/              #   config.yaml（过滤/摘要/文档样式）
│   ├── cache/               #   文章缓存（命中即跳过重复处理）
│   └── 筛选记录/             #   每日筛选快照（只追加）
│
├── 每周资讯skill/            # 【周度】读每日 docx → 去重整合 → 每周 docx
│   ├── run.py
│   └── src/                 #   自带 ai_client/auth（独立于每日 skill）
│
├── 每日资讯/                 # 【数据中枢】每日 docx 归档（按 YYYY_MM/ 嵌套）
├── 每周资讯/                 # 每周 docx 归档
│
├── 信息日报/                 # 【下游/网页】唯一的构建 + 部署目录（连 GitHub/Vercel）
│   ├── build/               #   build_all.py / aggregate.py / docx_parser.py
│   ├── web/                 #   index.html / issue.html / assets / data(JSON+docx)
│   └── .github/workflows/
│
└── logs/                    # 运行日志
```

---

## 二、数据流

```
公众号监测源.xlsx
   │  ①每日资讯skill/run.py（爬取 + AI 摘要 + 去重）
   ▼
每日资讯/YYYY_MM/每日资讯_日期.docx   ← 数据中枢
   │
   ├─ ②每周资讯skill（读周内 docx，去重整合）→ 每周资讯/每周资讯_*.docx
   │
   └─ ③信息日报/build/build_all.py（解析 docx + DeepSeek 聚合 10 条线索）
          │
          ▼  直接写入（无需 cp 复制）
       信息日报/web/data/*.json + docs/*.docx + manifest.json
          │  ④git push
          ▼
       GitHub → Vercel 自动部署 → 公网网页（可微信分享）
```

关键复用关系：`信息日报/build/aggregate.py` 通过 `sys.path` 复用
`每日资讯skill/src` 的 `ai_client.py`（DeepSeek 客户端）与 `auth.py`（授权），
因此 **两个目录必须保持同级**。

---

## 三、快速开始

```bash
# 1. 安装依赖（建议虚拟环境）
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium        # 首次爬取需要

# 2. 一键跑主流程（爬取 → 构建 → 推送部署）
bash 每日自动运行.sh

# 3. 仅本地预览网页
cd 信息日报/web && python3 -m http.server 8765
# 打开 http://localhost:8765/index.html

# 4. 生成每周资讯（可选）
bash 每周自动运行.sh              # 上一整周
bash 每周自动运行.sh --date 2026-06-30
```

单步调试：
```bash
cd 每日资讯skill && python3 run.py           # 只爬取生成 docx
cd 信息日报/build && python3 build_all.py     # 只重建网页数据（增量）
cd 信息日报/build && python3 build_all.py --force   # 全量重建
```

---

## 四、本次整合做了什么（相对旧结构）

| 变更 | 说明 |
|------|------|
| 合并 `写作线索日报` + `信息日报` | 二者构建脚本字节级重复；现统一为 `信息日报/`（保留增强版 assets 与 .git 部署连接），采用带「历史 manifest 合并」的新版 `build_all.py` |
| 去掉 cp 复制步骤 | `build_all.py` 直接写入 `信息日报/web/data`，`每日自动运行.sh` 不再需要跨目录 `cp` |
| 剔除废弃组件 | 未纳入早期 Flask 方案 `每日热点更新/`（已被本流程取代）、无代码引用的 `公众号test.xlsx`/`TOP50公众号.xlsx`/`微信公众号来源汇总.xlsx`/`群聊_信息来源.xlsx` |
| 去除 venv/缓存 | 复制时剔除 `.venv`（339M）、`__pycache__`、`.DS_Store`；改用统一 `requirements.txt` |
| 路径健壮化 | `.sh` 用 `BASH_SOURCE` 自适应根目录（不再硬编码绝对路径）；`build/` 调试块改为基于 `__file__` 相对定位 |

> 备份说明：原有各文件夹保持不动，可作为回退备份；确认本平台运行无误后再手动删除旧目录。

---

## 五、注意事项

- **数据源**：只使用根目录 `公众号监测源.xlsx`；其列为「公众号名称 / RSS 链接」。
- **授权/API Key**：由 `每日资讯skill/src/auth.py` 管理（作者机免密，他人需授权码 + 自备 DeepSeek Key）。
- **目录同级约束**：`每日资讯skill` 与 `信息日报` 必须同在平台根目录下，否则 `aggregate.py` 的跨目录导入会失败。
- **每周 skill 独立**：`每周资讯skill` 自带 `ai_client/auth` 副本，与每日 skill 相互独立。
