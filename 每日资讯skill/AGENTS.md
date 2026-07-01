# AGENTS.md — 每日资讯 Skill 项目导航（AI 优先阅读）

> 本文件是给 AI 编程助手的"项目说明书"。每次会话开头**只需读本文件 + `PROJECT_MAP.md`**，即可掌握项目全貌，**无需读取所有源码**。
> 配套地图：`PROJECT_MAP.md`（类/函数级别的符号索引）。
> **维护约定**：每次对源码做出会影响"功能/结构/字段/流水线"的修改后，请同步更新本文件与 `PROJECT_MAP.md` 的相关条目（详见文末"维护规则"）。

---

## 1. 项目目标

基于 **DeepSeek API + RSS** 的微信公众号每日资讯聚合工具：
1. 从 Excel 配置的多个 RSS 源**并发爬取**最近 1 天文章；
2. 用 AI 完成 **广告/水文过滤 → 摘要生成（300-500 字，带【标题】）→ MECE 分类 → 跨源去重 / 多视角整合**；
3. 生成排版精美的 **Word 日报**（按 MECE 分类排序）+ **筛选记录 Markdown**；
4. 文档生成后再调用 AI **自动验证并修复重复**，最多 5 轮；
5. 全流程缓存命中、断点续跑友好（已处理过的文章不会重复消耗 token）。

**目标用户**：个人 / 团队的每日信息整理工作流，要求"宁缺毋滥、不能误杀深度分析"。

---

## 2. 技术栈速查

| 维度 | 选择 |
|---|---|
| 语言 | Python 3.8+ |
| AI 服务 | DeepSeek（`deepseek-chat`，HTTP/JSON），自定义 TF-IDF + BM25 风格相似度（不依赖外部 embedding API） |
| 抓取 | `requests` 主路径 + `playwright` 兜底（403 反爬） |
| 文档 | `python-docx`（Word），`pandas/openpyxl`（Excel） |
| 配置 | `config/config.yaml` + `公众号监测源.xlsx`（运行时优先用上级目录的 `公众号监测源.xlsx`） |
| 并发 | `ThreadPoolExecutor`，AI 端用 `Semaphore(8)` 限并发 + 指数退避 |

---

## 3. 目录结构与职责

```
每日资讯skill/
├── AGENTS.md                  ← 你正在看的文件（AI 入口）
├── PROJECT_MAP.md             ← 符号级代码地图（按需读取）
├── README.md                  ← 给"人"看的使用说明
├── run.py                     ← 启动脚本（CLI 参数解析、stdout 行缓冲、调用 src/main.main）
├── test_similarity.py         ← Jaccard 相似度调试脚本（独立可运行，与生产去重无关）
├── requirements.txt           ← 依赖清单
├── config/
│   ├── config.yaml            ← 全局配置（过滤、摘要长度、文档样式、日志、调度）
│   └── 公众号列表.xlsx         ← 默认 RSS 源表（生产实际用上级目录的「公众号监测源.xlsx」）
├── src/                       ← 全部生产代码（修改 99% 集中在这里）
│   ├── main.py                ← 主流水线 + Article 数据类 + 爬虫 + 文档生成（4400+ 行，分块见 PROJECT_MAP）
│   ├── auth.py                ← 授权 / 凭证管理（本机指纹识别、授权码校验、API Key 加密读写）
│   ├── ai_client.py           ← DeepSeek 客户端：广告判定 / 摘要 / MECE 分类 / 去重 LLM / TF-IDF
│   ├── content_filter.py      ← 规则层广告过滤（5 层 + 综合评分），Article.is_noise_content 之外的另一道关
│   ├── ai_summarizer.py       ← 旧的本地（非 AI）摘要算法，作为兜底/参考，主流程未启用
│   └── utils.py               ← 配置加载 / 日志 / Excel 读取 / 路径辅助
├── .machine_fingerprint       ← 作者本机白名单 + 预置 API Key（**发布给他人前必须删除**）
├── .gitignore                 ← 打包/版本控制忽略清单
├── cache/                     ← 文章级缓存（按 link+title 的 md5），跨天复用 → 节省 token
├── logs/                      ← 运行日志（app.log，按大小轮转）
├── 筛选记录/                   ← 每日生成的 Markdown 筛选明细（噪音/去重/验证）
└── （运行时）../每日资讯/        ← Word 日报输出目录（在 skill 的上级目录）
```

> ⚠️ `cache/`、`logs/`、`筛选记录/` 是**运行时产物**，AI 修改代码时通常不需要读取它们。

---

## 4. 七步主流水线（最关键的认知）

入口：`run.py` → `src/main.py:main()` → `WeChatArticleCrawler.crawl_all_feeds()` → `DocumentGenerator.create_document()`

| 步骤 | 名称 | 关键函数 | 关键文件 |
|---|---|---|---|
| 1 | **RSS 爬取**（多线程） | `WeChatArticleCrawler.crawl_all_feeds` / `parse_rss_feed` / `_fetch_with_retry` | `src/main.py` |
| 2 | **AI 广告判断**（8 并发） | `DeepSeekClient.batch_classify_advertisement` → `is_advertisement` | `src/ai_client.py` |
| 3 | **AI 摘要生成**（含分段、长度收紧、标题优化二轮兜底） | `ParallelSummaryGenerator.generate_summaries`，`DeepSeekClient.generate_summary` / `_generate分段_summary` / `_condense_summary_if_too_long` / `batch_optimize_titles` | `src/main.py` + `src/ai_client.py` |
| 4 | **AI MECE 分类**（11 大类 / 子类，详见 `Article.MECE_CATEGORIES`） | `DeepSeekClient.batch_classify_mece` → `classify_article` | `src/ai_client.py` |
| 5 | **每日总结一句话** | `DeepSeekClient.generate_daily_summary` | `src/ai_client.py` |
| 6 | **规则噪音过滤 + AI 杂糅复核** | `Article.is_noise_content`（鸡汤/医学案例/院校动态/餐饮/杂糅/天气预报/主观非资讯 等 30+ 大类规则）+ `DeepSeekClient.is_topic_mess` 复核 | `src/main.py` + `src/ai_client.py` |
| 7 | **去重 / 多视角整合**（核心算法） | `WeChatArticleCrawler._deduplicate_articles`：TF-IDF 余弦 + Jaccard 补充 + 精确匹配 → 连通分量聚类 → 大簇(>5)走 `_merge_large_cluster` 整合，小簇走 `_select_best_article` 选优 | `src/main.py` + `src/ai_client.py` |
| 8 | **文档级 AI 重复验证 + 自动修复**（`main()` 内，最多 5 轮） | `DeepSeekClient.verify_document_duplicates` → `_auto_fix_duplicates` | `src/main.py` |

**最后**：保存 `cache/`、写入 `筛选记录/筛选记录_YYYY-MM-DD.md`、产出 `../每日资讯/每日资讯_YYYY-MM-DD.docx`。

---

## 5. 核心数据结构：`Article`（`src/main.py:122`）

```python
@dataclass-like
class Article:
    source_name: str              # 公众号名
    title: str                    # 原标题
    link: str
    pub_date: datetime            # 发布时间（带时区）
    full_content: str             # 正文（HTML 已清洗）
    ai_summary: str               # AI 生成的摘要（含【XX】前缀，后被剥离）
    is_advertisement: bool        # 兼容字段：广告或噪音都置 True
    rejection_reason: str         # 被过滤原因
    category_tag: str             # 摘要中提取并优化后的【新闻标题】，文档中显示的标题
    mece_category: str            # 例如 "4.1"（人工智能）
    is_merged: bool               # True = 多视角整合产物
    merged_sources: list          # 整合时的原始来源
    # 类常量：
    MECE_CATEGORIES               # 编号 → 名称
    HIGH_QUALITY_SOURCES          # 高质量白名单（财新/三联等放宽过滤）
    CROSS_DOMAIN_ANALYSIS_INDICATORS  # 标题含此类词不判杂糅
```

---

## 6. "改 X 该去哪"快速跳转表

| 想做的修改 | 主要文件 / 函数 |
|---|---|
| **新增 RSS 源** | 编辑上级目录 `公众号监测源.xlsx`（列：`公众号名称`、`RSS链接`），无需改代码 |
| 改 DeepSeek API Key | **不再硬编码**：本机改 `.machine_fingerprint` 中的 `author_api_key`；他人通过 `python run.py --reauth` 重新输入 |
| 改授权码 | `src/auth.py` 顶部 `AUTHORIZATION_CODE = "654321"` |
| 改本机白名单 | `.machine_fingerprint` 中追加新的 `macs` 或 `uuids` |
| 改并发 / 超时 / 重试 | `src/ai_client.py` 顶部 `API_TIMEOUT_SECONDS / API_MAX_RETRIES / API_MAX_CONCURRENCY` |
| 改去重相似度阈值 | `src/ai_client.py:HIGH_SIM_THRESHOLD / MEDIUM_SIM_THRESHOLD / LOW_SIM_THRESHOLD` |
| 改 / 加 **广告 prompt** | `DeepSeekClient.is_advertisement`（`src/ai_client.py`） |
| 改 / 加 **MECE 分类规则** | `DeepSeekClient.classify_article`（prompt） + `Article.MECE_CATEGORIES`（命名） |
| 改 **摘要风格 / 禁词** | `DeepSeekClient.generate_summary` 的 `system_prompt`（`src/ai_client.py`）——已加"禁止口语化/煽情/夸张表述"规则 |
| 改 **标题逗号切分** | `DeepSeekClient.generate_summary` + `optimize_title` 的 prompt（`src/ai_client.py`）——已加"长标题必须用逗号切分"规则 |
| 改 **规则噪音过滤**（鸡汤、医学、院校等） | `Article.is_noise_content`（`src/main.py:213` 起，按编号 1-33+ 的小段添加/调整） |
| 改 **杂糅判断（误杀跨领域分析）** | `DeepSeekClient.is_topic_mess` + `Article.CROSS_DOMAIN_ANALYSIS_INDICATORS` |
| 改 **去重 / 整合算法** | `WeChatArticleCrawler._deduplicate_articles` / `_merge_large_cluster` / `_select_best_article` / `_find_exact_duplicates`（`src/main.py`） |
| 改 **高考主题特例整合** | `_deduplicate_articles` 中的 `gaokao_core_keywords` / `gaokao_extended_keywords` / `gaokao_exclude` 及 `is_gaokao_cluster` 判断（`src/main.py`） |
| 改 **Word 文档样式** | `DocumentGenerator`（`src/main.py:1545`）+ `config/config.yaml` 的 `document` 段 |
| 改 **正则层广告过滤** | `src/content_filter.py`（5 层关键词/模式表） |
| 改 **筛选记录格式** | `src/main.py:main()` 中 `record_path` 写入段（约 4290-4370 行） |
| 改 **缓存策略** | `WeChatArticleCrawler._load_cache / _save_cache / _is_article_in_cache`（`src/main.py`） |

---

## 7. 已知坑点 / 历史经验（避免踩雷）

1. **`main.py` 是 4400+ 行的巨文件**，但**不要重构**——里面相互引用 `Article`/常量很密。修改请用 `replace_in_file` 精准定位。
2. `_generate分段_summary` 函数名带中文，是历史遗留，**不要改名**——会断调用链。
3. `SIMILARITY_THRESHOLD`（旧 Jaccard 阈值 0.15）和 `HIGH/MEDIUM/LOW_SIM_THRESHOLD`（新 TF-IDF 余弦阈值，0.04~0.12）**并存**。Jaccard 当前**仅作日志参考**，不再加入连通图（容易把"都提到联合国"的不相关文章错连）。
4. `Article.is_advertisement` 是兼容字段——**广告**和**噪音**都会把它置 True，靠 `rejection_reason` 区分。
5. 高质量来源（财新、三联、虎嗅等，见 `HIGH_QUALITY_SOURCES`）规则过滤时**自动放宽**，不要在 prompt 或规则里给它们加严。
6. AI 把杂糅文判错时，先看 `is_noise_content` 中"内容杂糅类/聚合快讯类/综合集成式"分支，再看 `is_topic_mess` 的 prompt——已加 **AI 复核** 兜底。
7. **Excel 真实文件名是 `公众号监测源.xlsx`，放在 skill 的上级目录**（不是 config 里的 `公众号列表.xlsx`）。配置文件是历史默认，运行时被 `main()` 覆盖。
8. DeepSeek 没有 embedding API，`get_embedding` 已写死返回 `None`，全部走 **TF-IDF + BM25 风格 IDF**（见 `compute_tfidf_embeddings`）。**不要恢复 embedding 调用**，会浪费 token 并失败。
9. `cache/` 命中后会跳过步骤 2/3/4，标记 `_from_cache=True`。如需强制重跑，先删 `cache/`。
10. `筛选记录/` 是历史快照，**只追加不修改**——不要让代码批量改写历史 md。
11. 天气预报/汛期/气候预测类文章由 `is_noise_content` 规则29.7过滤，**标题本身是天气主题时直接过滤，不受摘要中金融关键词保护**。
12. 主观非资讯类文章（如医生自述崩溃、职业日常吐槽）由 `is_noise_content` 规则33过滤，"制度/政策"等词仅在文章前半部分出现时才算有效保护。
13. 陪伴经济/情绪消费类文章归3.3体验消费；执法冲突/城管商贩冲突归11.1热点事件；医疗职业困境文章若只是个人吐槽也应过滤或归11.1。
14. **高考主题特例**：`_deduplicate_articles` 中通过 `gaokao_core_keywords` + `gaokao_extended_keywords` 识别高考文章，所有高考文章强制连通为同一簇，且簇内无论文章数量（含2篇）均走 `_merge_large_cluster` 整合路径，不走小簇去重。排除词（考研/中考/考公等）在标题中出现时跳过匹配。
11. **API Key 不在任何源码文件中**：本机靠 `.machine_fingerprint` 提供（已在 `.gitignore`、不入版本控制），他人靠交互授权后保存到 `~/.daily_news_skill/credentials.enc`（PBKDF2 + HMAC 加密）。**严禁** AI 在重构时把 Key 重新硬编码回 `src/main.py` 或 prompt 里。
12. 发布给他人的压缩包**必须删除** `.machine_fingerprint`，否则相当于把 API Key 明文外发。

---

## 8. 配置项速查（`config/config.yaml`）

- `rss.*`：RSS 拉取并发 / 超时
- `filter.*`：内置广告关键词、价格 / 联系方式正则、URL 阈值
- `summary.target_length / min_length / max_length`：摘要长度（注意 `ai_client.py` 中硬编码上限 500，与此处 max_length=300 不一致——以 `ai_client.py` 为准）
- `document.*`：字体、行距、分隔线、链接颜色
- `output.directory`（默认 `../output`，但 `main()` 强制改为 `../每日资讯`）
- `logging.*`：日志位置、级别、轮转
- 其余 `schedule / test`：当前未在主流程启用

---

## 9. 维护规则（**重要**）

每次完成一次"会影响下列内容之一"的修改后，**自动同步更新**本文件与 `PROJECT_MAP.md`：

| 改动类型 | 同步动作 |
|---|---|
| 新增 / 删除 / 重命名 文件、类、公开函数 | 更新 `PROJECT_MAP.md` 对应条目；如果属于"修改路径指引（§6）"也要更新 |
| 改变七步流水线（顺序/职责/新增步骤） | 更新本文件 §4 表格 |
| 修改 `Article` 字段或类常量 | 更新本文件 §5 |
| 增减 / 改名 配置项 | 更新本文件 §8 |
| 修改阈值 / API 并发 / 重试参数 | 更新本文件 §6 与 `PROJECT_MAP.md` 的"关键常量"段 |
| 引入新依赖 | 更新 `requirements.txt` 并在本文件 §2 中登记 |
| 发现新坑点 | 追加到本文件 §7 |

**同步原则**：增量编辑而非整篇重写；写完源码改动后，紧接着在同一次任务里更新这两份 md，避免漂移。如果只是修了一行实现细节、没改公开接口，**不必**更新地图。
