# PROJECT_MAP.md — 符号级代码地图

> 自动维护的"项目地图"：列出每个文件中的类、函数签名、关键常量及其行号定位（行号会随编辑漂移，可作粗略锚点）。
> **AI 工作约定**：先读本文件，按需用 `read_file(filePath, offset=行号, limit=...)` 只读相关片段，**避免全文件读取**。
> **维护规则**：详见 `AGENTS.md` §9。新增 / 删除 / 重命名公开符号时同步更新本文件相应条目。

---

## src/auth.py（授权与凭证管理，~280 行）

### 关键常量
- `AUTHORIZATION_CODE = "654321"` — 6 位固定授权码
- `_CRED_DIR = ~/.daily_news_skill/`、`_CRED_FILE = credentials.enc`
- `_FINGERPRINT_FILE = <skill_root>/.machine_fingerprint`
- `_MAX_CODE_ATTEMPTS = 5`，`_PBKDF2_ITERATIONS = 200_000`

### 本机指纹
- `_get_mac_fingerprint() -> str`
- `_get_hardware_uuid() -> str` — macOS `ioreg` / Linux `/etc/machine-id` / Windows 注册表 `MachineGuid`
- `_current_fingerprints() -> (mac, uuid)`
- `is_local_machine() -> bool` — 任一指纹命中 + `.machine_fingerprint` 含 `author_api_key` 才返回 True
- `_load_author_api_key() -> Optional[str]`

### 加解密（零依赖：PBKDF2 派生 + SHA256 keystream + HMAC-SHA256 完整性校验）
- `_derive_key(passcode, salt) -> bytes`
- `_encrypt(plaintext, passcode) -> bytes`：输出 `magic(4)|salt(16)|nonce(16)|hmac(32)|ciphertext`
- `_decrypt(blob, passcode) -> Optional[str]`：HMAC 不匹配返回 None

### 凭证文件
- `_save_credentials(api_key, passcode)` — 写到 `~/.daily_news_skill/credentials.enc`，权限 0o600
- `_load_credentials(passcode) -> Optional[str]`
- `_clear_credentials()`

### 交互流程
- `_print_banner()`、`_ask_authorization_code() -> bool`、`_ask_api_key() -> Optional[str]`
- `_interactive_setup() -> Optional[str]`

### 对外主接口（**模块外只用这两个**）
- `get_api_key(force_reauth: bool = False) -> Optional[str]`
  - 流程：force_reauth → 清凭证 → 本机直通 → 解密缓存 → 交互授权
- `is_local_machine() -> bool`

### 自检入口
- `python src/auth.py` 直接执行可打印当前指纹与识别结果

---

## src/main.py（主流水线，~4400 行）

### 模块顶部
- `class ParallelSummaryGenerator` *(L30)*：摘要并发生成器，8 线程
  - `__init__(ai_client, max_workers=8)` *(L33)*
  - `generate_summaries(articles: List) -> None` *(L37)*
- `class _FlushStreamHandler(logging.StreamHandler)` *(L83)*：实时刷新日志输出
- `def _p(msg: str) -> None` *(L108)*：带 flush 的 print 包装

### `class Article` *(L122)* — 核心数据类
- 字段：`source_name, title, link, pub_date, full_content, ai_summary, is_advertisement, rejection_reason, category_tag, mece_category, is_merged, merged_sources`
- 类常量：
  - `MECE_CATEGORIES: dict` *(L138)* — 11 大类 / 子类编号 → 名称
  - `HIGH_QUALITY_SOURCES: list` *(L194)* — 高质量来源白名单（财新/三联/虎嗅等）
  - `CROSS_DOMAIN_ANALYSIS_INDICATORS: list` *(L205)* — 标题含此词不判杂糅
- 方法：
  - `is_noise_content() -> tuple[bool, str]` *(L213)*：18 类规则（鸡汤/医学案例/院校/餐饮/职场水文/杂糅/历史科普/纯回顾/学术论文/学生事件/人事任免/微小地方等）

### Word 文档辅助函数（L1356-1544）
- `_set_font(paragraph, font_name, size)` *(L1356)*
- `_add_internal_hyperlink(doc, text, anchor, ...)` *(L1376)*：文档内书签跳转
- `_add_external_hyperlink(paragraph, url, text, ...)` *(L1441)*：外链
- `_add_bookmark(paragraph, bookmark_id, bookmark_name)` *(L1508)*

### `class DocumentGenerator` *(L1545)* — Word 生成
- `MECE_MAIN_CATEGORIES: dict`（11 大类索引名）
- `_get_main_category_name(mece_category) -> str` *(L1579)*
- `create_document(articles, output_path, daily_summary="") -> bool` *(L1588)*：核心入口，含目录、按 MECE 分组、序号、链接、字体设置
- `_sort_by_mece_category(articles) -> List[Article]` *(L1877)*

### `class WeChatArticleCrawler` *(L1911)* — 主爬虫与流水线
- `__init__(excel_path, deepseek_api_key)` *(L1914)*：初始化客户端、缓存、`one_day_ago` 时间窗
- 时间 / 缓存：
  - `make_timezone_aware(dt) -> datetime` *(L1935)*
  - `_load_cache() -> dict` *(L1942)* / `_save_cache()` *(L1963)*
  - `_get_cache_key(link, title) -> str` *(L1972)*（md5）
  - `_is_article_in_cache(link, title, pub_date) -> bool` *(L1978)*
  - `_add_to_cache(link, title, article_data)` *(L1989)*
- RSS 抓取：
  - `load_rss_links() -> pd.DataFrame` *(L1995)*：读 Excel
  - `_get_rss_headers() -> dict` *(L2012)*：随机 UA / Referer
  - `_fetch_with_requests(url, source_name, max_retries=3)` *(L2033)*
  - `_fetch_with_playwright(url, source_name, max_retries=2)` *(L2073)*：反爬兜底
  - `_fetch_with_retry(url, source_name, max_retries=2)` *(L2139)*：requests → playwright 链
  - `_clean_xml_content(content) -> bytes` *(L2147)*
  - `_try_parse_xml(content) -> Optional[ET.Element]` *(L2179)*
  - `parse_rss_feed(url, source_name) -> List[Article]` *(L2232)*
  - `_extract_article(item, source_name) -> Optional[Article]` *(L2293)*
  - `_parse_date(date_str) -> Optional[datetime]` *(L2354)*
  - `_clean_html(html_text) -> str` *(L2380)*
- 去重 / 整合：
  - `_deduplicate_articles(articles) -> List[Article]` *(L2988)*：TF-IDF + Jaccard 补充 + 精确匹配 + 规则预匹配（外交/灾害/商业/国际事件/食品安全/高考）→ 连通分量 → 大簇整合 / 小簇选优
  - **高考特例**：`gaokao_core_keywords` + `gaokao_extended_keywords` 识别高考文章 → 强制连通 + `is_gaokao_cluster` 判断 → 无论簇大小均走 `_merge_large_cluster` 整合
  - `_merge_large_cluster(articles, indices) -> Optional[Article]` *(L3010)*：大簇(≥3)多视角 AI 整合
  - `_condense_merged_summary(original_content, max_length=500)` *(L3215)*
  - `_select_best_article(articles, indices) -> int` *(L3257)*：小簇选优
  - `_extract_core_entities(text) -> set` *(L3337)*
  - `_find_exact_duplicates(articles) -> List[Tuple[int, int]]` *(L3428)*：同源 + 高度相似
  - `_calculate_similarity(text1, text2) -> float` *(L3481)*
- 主流水线：
  - `crawl_all_feeds()` *(L3496)* — **七步主流程入口**
    - 步骤 1：多线程 RSS 爬取
    - 步骤 2：`batch_classify_advertisement`
    - 步骤 3：`ParallelSummaryGenerator` + 步骤 3.5 `batch_optimize_titles`（两轮，含占位标题重生）
    - 步骤 4：`batch_classify_mece`
    - 步骤 5：`generate_daily_summary`
    - 步骤 6：`is_noise_content` + AI 杂糅复核 `is_topic_mess`
    - 步骤 7：`_deduplicate_articles`

### 模块级函数
- `_clean_summaries(articles)` *(L3828)*：清理摘要中的元信息 / 废话表述 / 标题首句重复
- `_auto_fix_duplicates(crawler, suggestions: str) -> bool` *(L3883)*：解析 AI 重复建议并合并文章
- `main(custom_excel_path: str = None) -> bool` *(L4123)*：**程序总入口**
  - **API Key 来源**：优先从环境变量 `DEEPSEEK_API_KEY` 读取（由 `run.py` 通过 `auth.get_api_key()` 注入）；若直跑 `src/main.py`，兜底动态导入 `auth` 模块走交互流程
  - 路径：上级目录 `公众号监测源.xlsx` → `../每日资讯/每日资讯_YYYY-MM-DD.docx` → `筛选记录/筛选记录_YYYY-MM-DD.md`
  - 第 8 步：`verify_document_duplicates` × 最多 5 轮 + `_auto_fix_duplicates`
  - 缓存写入、筛选记录写入

---

## src/ai_client.py（DeepSeek 客户端，~1900 行）

### 关键常量（L21-43）
- `API_TIMEOUT_SECONDS = 90`
- `API_MAX_RETRIES = 4`
- `API_BACKOFF_BASE = 1.0`，`API_BACKOFF_CAP = 30.0`
- `API_MAX_CONCURRENCY = 8`，`_API_SEMAPHORE = threading.Semaphore(8)`
- `SIMILARITY_THRESHOLD = 0.15`（旧 Jaccard，**仅日志兼容**）
- `HIGH_SIM_THRESHOLD = 0.12`（TF-IDF 余弦：直接去重）
- `MEDIUM_SIM_THRESHOLD = 0.07`（需 LLM 判断）
- `LOW_SIM_THRESHOLD = 0.04`（规则辅助）

### `class DeepSeekClient` *(L45)*
- `__init__(api_key)` *(L48)*：`api_base="https://api.deepseek.com/v1/chat/completions"`，`model="deepseek-chat"`
- **判定 / 生成（单次）**：
  - `is_advertisement(title, content) -> (bool, str)` *(L60)*：18 项过滤准则的 prompt
  - `is_topic_mess(title, content, rule_reason="") -> (bool, str)` *(L145)*：杂糅 / 聚合快讯 AI 复核
  - `generate_summary(title, content, target_length=500) -> str` *(L198)*：含 8000 字以下直生 / 8000+ 字分段
  - `_generate分段_summary(title, content, target_length=500) -> str` *(L359)* ⚠️ **函数名含中文，勿改**
  - `generate_summary_with_retry(title, content, max_retries=0) -> str` *(L473)*
  - `_condense_summary_if_too_long(title, content, summary) -> str` *(L496)*：>500 字时最多 2 轮 AI 精简 + 硬截断兜底
  - `_generate_condensed_summary(title, content, max_length=500) -> str` *(L565)*
  - `classify_article(title, summary) -> str` *(L616)*：返回 MECE 编号字符串，含 11 大类详尽规则
  - `compare_articles(article1, article2) -> int` *(L901)*：返回 1 / -1 / 0
  - `is_same_event(article1, article2) -> bool` *(L954)*：含人名快速匹配
  - `optimize_title(original_title, content="") -> str` *(L1513)*：单条标题优化
  - `generate_daily_summary(articles) -> str` *(L1466)*：每日一句话导读
  - `verify_document_duplicates(document_text) -> (bool, list, str)` *(L1750)*：文档级 AI 重复验证
- **底层 HTTP**：
  - `_call_api(prompt) -> str` *(L804)*
  - `_call_api_with_system(system_prompt, user_prompt) -> str` *(L816)*：超时 / 重试 / 退避 / 全局 Semaphore
- **关键词 / TF-IDF**（L1022-1389）：
  - `_extract_keywords(text) -> set` *(L1022)*：人名 / 品牌 / 事件类型 / 学校 / 2-3 字 n-gram
  - `get_embedding(text)` *(L1095)*：⚠️ **当前直接 return None**（DeepSeek 无 embedding API，走 TF-IDF）
  - `_tokenize_for_tfidf(text) -> List[str]` *(L1122)*（@staticmethod）：英文 / 数字+单位 / 2-4 字中文 n-gram + 停用词
  - `compute_tfidf_embeddings(texts) -> np.ndarray` *(L1195)*（@staticmethod）：BM25 风格 TF + IDF + L2 归一化
  - `cosine_similarity_matrix(embeddings) -> np.ndarray` *(L1268)*（@staticmethod）
  - `find_similar_groups_v2(articles)` *(L1284)*：TF-IDF 三级阈值
  - `_jaccard_similarity(s1, s2) -> float` *(L1369)*
  - `find_similar_groups(articles)` *(L1391)*：旧 Jaccard，仅日志参考
- **批量并发 API（线程池 + Semaphore）**：
  - `batch_optimize_titles(articles)` *(L1580)*
  - `batch_dedup_review(article_groups)` *(L1627)* / `_dedup_review_single_group(...)` *(L1670)*
  - `batch_classify_advertisement(articles)` *(L1822)*
  - `batch_classify_mece(articles)` *(L1868)*

---

## src/content_filter.py（规则层广告过滤）

### `@dataclass FilterResult` *(L16)*
- `is_filtered: bool, reason: str, confidence: float`

### `class ContentFilter` *(L22)*
- 词表 / 模式表（类常量）：
  - `AD_KEYWORDS_LEVEL1`：促销 / 推广 / 电商 / 行动召唤 / 营销话术 等
  - `AD_PATTERNS_LEVEL2`：`price_patterns / contact_patterns / url_patterns / buy_patterns`
  - `TITLE_AD_INDICATORS`：标题级推广特征
  - `SOFT_ARTICLE_PATTERNS`：软文开头 / 过渡 / 结尾 模式
  - `HIGH_FREQUENCY_AD_WORDS`：高频营销词
  - `WHITELIST_KEYWORDS`：公益 / 学术 / 政策 / 新闻 / 科普
- 方法（全部 `@classmethod`）：
  - `is_advertisement(title, content) -> FilterResult` *(L163)*：依次跑五层 + 综合评分
  - `_check_whitelist(title, content) -> Set[str]` *(L228)*
  - `_check_level1_keywords(title, content) -> FilterResult` *(L238)*
  - `_check_level2_patterns(...)` *(L268)*
  - `_check_title_features(title)` *(L312)*
  - `_check_soft_article_features(...)` *(L325)*
  - `_check_high_frequency_words(...)` *(L358)*
  - `_comprehensive_score(...)` *(L381)*

> 注意：当前生产流水线主要使用 `Article.is_noise_content` 与 `DeepSeekClient.is_advertisement`；`ContentFilter` 作为可选的离线规则层保留，未在 `crawl_all_feeds` 中默认调用。

---

## src/ai_summarizer.py（旧的本地摘要算法 — 兜底/参考，主流程未启用）

### `class AISummarizer` *(L14)*（全部 `@classmethod / @staticmethod`）
- `generate_summary(content, target_length=250) -> str` *(L17)*
- `_clean_content(content) -> str` *(L47)*：HTML / 实体 / 空白 / 特殊字符清理
- `_split_sentences(content) -> List[str]` *(L72)*
- `_extract_key_sentences(sentences, target_length) -> List[(idx, str, score)]` *(L80)*：位置 / 长度 / 关键词 / 数字密度评分
- `_build_summary(key_sentences, target_length) -> str` *(L131)*
- `_supplement_content(summary, sentences, target_length) -> str` *(L146)*
- `_adjust_length(text, target_length) -> str` *(L173)*：200-300 字裁剪
- `generate_detailed_summary(title, content, target_length=250) -> str` *(L229)*

---

## src/utils.py（配置 / 日志 / IO 工具）

- `load_config(config_path=None) -> Dict` *(L16)*：加载 + 与默认深度合并
- `get_default_config() -> Dict` *(L52)*：内置默认配置
- `merge_dicts(default, custom) -> Dict` *(L128)*
- `setup_logging(config) -> None` *(L149)*：文件 + 控制台双 handler
- `format_timestamp(timestamp, format_str=...) -> str` *(L191)*
- `calculate_md5(content) -> str` *(L207)*
- `safe_filename(filename) -> str` *(L219)*
- `ensure_directory(path) -> bool` *(L242)*
- `read_excel_file(filepath, sheet_name=None) -> List[Dict]` *(L259)*
- `write_json_file(data, filepath, indent=2) -> bool` *(L289)*
- `read_json_file(filepath) -> Optional[Any]` *(L312)*
- `get_project_root() -> str` *(L337)*
- `get_resource_path(relative_path) -> str` *(L346)*

---

## run.py（启动脚本）

- 强制 stdout/stderr 行缓冲（Python 3.7+ `reconfigure`，否则 `TextIOWrapper`）+ `print` 默认 flush（L13-35）
- `setup_argparse() -> ArgumentParser`：参数 `--test / --verbose / --config / --output / --log-level / --excel / --reauth`
- `test_mode() -> bool`
- `setup_environment(args) -> config`
- `main()`：解析参数 → **`auth.get_api_key(force_reauth=args.reauth)` 注入 `DEEPSEEK_API_KEY` 环境变量** → `setup_environment` → `src/main.py:main(args.excel)`

---

## test_similarity.py（独立调试脚本，不进生产）

- 18 篇真实标题硬编码
- `extract_keywords_v2(text) -> set` *(L32)*：标题关键词提取改进版
- `jaccard(s1, s2) -> float` *(L61)*
- 输出所有标题对的 Jaccard 相似度表，验证阈值合理性

---

## config/config.yaml（关键键路径速查）

- `rss.excel_file / sheet_name / columns / max_concurrent / request_interval / timeout`
- `filter.enable_ad_filter / ad_keywords / price_patterns / contact_patterns / max_url_count / title_ad_indicators`
- `summary.target_length / min_length / max_length / method / preserve_key_info / max_sentences`
- `document.font / paragraph / separator / link_color`
- `output.directory / filename_format / keep_history / max_history_files`
- `logging.level / file / max_file_size / backup_count / format`
- `schedule.*`、`test.*`（当前未在主流程启用）

---

## 调用关系速览（粗）

```
run.py:main
  ├─ auth.get_api_key(force_reauth=args.reauth)    ← 本机直通 / 解密缓存 / 交互授权
  │    └─ 注入环境变量 DEEPSEEK_API_KEY
  └─ src/main.py:main
       ├─ os.environ['DEEPSEEK_API_KEY']           ← 从环境变量读取（兜底再走 auth）
       ├─ WeChatArticleCrawler(excel, api_key)
       │    └─ DeepSeekClient(api_key)
       ├─ crawler.crawl_all_feeds   ← 七步流水线
       │    ├─ load_rss_links / parse_rss_feed / _fetch_with_retry
       │    ├─ DeepSeekClient.batch_classify_advertisement
       │    ├─ ParallelSummaryGenerator → DeepSeekClient.generate_summary_with_retry
       │    ├─ DeepSeekClient.batch_optimize_titles（两轮）
       │    ├─ DeepSeekClient.batch_classify_mece
       │    ├─ DeepSeekClient.generate_daily_summary
       │    ├─ Article.is_noise_content + DeepSeekClient.is_topic_mess（复核）
       │    └─ _deduplicate_articles
       │         ├─ DeepSeekClient.compute_tfidf_embeddings / cosine_similarity_matrix
       │         ├─ DeepSeekClient.find_similar_groups（Jaccard 仅日志）
       │         ├─ _find_exact_duplicates
       │         ├─ _merge_large_cluster（大簇 >5）→ DeepSeekClient.generate_summary
       │         └─ _select_best_article（小簇 <=5）
       ├─ _clean_summaries
       ├─ DocumentGenerator.create_document → Word 输出
       ├─ DeepSeekClient.verify_document_duplicates × ≤5 轮
       │    └─ _auto_fix_duplicates
       ├─ crawler._save_cache
       └─ 写入 筛选记录_YYYY-MM-DD.md
```
