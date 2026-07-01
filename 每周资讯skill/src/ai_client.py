#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DeepSeek AI客户端 - 用于内容去重、比较、分类和主题融合
升级版：TF-IDF去重、API稳定性、批量操作、标题优化
"""

import logging
import requests
import json
import numpy as np
import re
import time
import random
import threading
from collections import Counter
from typing import Optional, List, Tuple, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# ==================== DeepSeek 调用稳定性配置 ====================
API_TIMEOUT_SECONDS = 90
API_MAX_RETRIES = 4
API_BACKOFF_BASE = 1.0
API_BACKOFF_CAP = 30.0
API_MAX_CONCURRENCY = 8
_API_SEMAPHORE = threading.Semaphore(API_MAX_CONCURRENCY)
# =================================================================

# 相似度阈值（每周资讯场景：阈值适当放宽以捕捉同主题不同角度文章）
SIMILARITY_THRESHOLD = 0.15  # 旧Jaccard阈值，保留兼容
HIGH_SIM_THRESHOLD = 0.10    # 高相似度：直接去重（TF-IDF）
MEDIUM_SIM_THRESHOLD = 0.05  # 中相似度：需LLM判断
LOW_SIM_THRESHOLD = 0.02     # 低相似度：结合规则判断


class DeepSeekClient:
    """DeepSeek API客户端"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.api_base = "https://api.deepseek.com/v1/chat/completions"
        self.model = "deepseek-chat"
        self.chat_model = "deepseek-chat"

    # ==================== 广告/噪音判断 ====================

    def is_advertisement(self, title: str, content: str) -> tuple:
        """使用AI判断文章是否为广告、商业推广或无新闻价值的内容"""
        content_preview = content[:2000] if content else ""
        content_length = len(content.strip()) if content else 0
        placeholder_patterns = ['阅读全文', '预览时标签不可点', '展开全文', '点击展开', '更多精彩内容']
        has_placeholder = any(p in content_preview for p in placeholder_patterns)

        # 只有当内容极短(< 20字)且含占位符时才直接过滤
        # 不对摘要为空的文章一刀切，因为每周资讯场景下文章可能只有标题
        if content_length < 20 and has_placeholder:
            return True, "内容缺失或仅含占位符"

        prompt = f"""请判断以下文章是否应该被过滤（不收录到资讯中）。

文章标题：{title}
文章内容：{content_preview}

判断标准（符合任一即过滤）：
1. **广告推销类**：产品推销、商业宣传、购买引导、联系方式/二维码、明显商业软文
2. **鸡汤励志类**：空洞的人生哲理、励志名言、成功学内容、个人感悟心得体会
3. **医学案例水文类**：以罕见病例、医学案例为卖点，缺乏公共卫生意义和深度分析
4. **地方小新闻类**：地方性事务、地方院校/医院动态、区域性事件，缺乏全国性影响力
5. **综合集成水文类**：一篇文章杂糅多个不相关话题
6. **比赛/竞赛宣传类**：各类大赛启动公告、报名通知等宣传信息
7. **历史科普/考证类**：纯历史领域科普，缺乏当前新闻价值
8. **地方普通人事任免类**：地方政府常规人事任免公告
9. **正常收录**：新闻报道、深度分析、行业观察、政策解读等有新闻价值的信息

请严格按照以下格式回复（只回复JSON）：
{{"is_ad": true/false, "reason": "判断原因（简短说明）"}}

不要有任何其他内容，只回复JSON。"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            is_ad = result.get("is_ad", False)
            reason = result.get("reason", "")
            logger.info(f"AI广告判断: 标题='{title[:30]}...', 结果={is_ad}, 原因={reason}")
            return is_ad, reason
        except Exception as e:
            logger.error(f"AI广告判断失败: {e}")
            return False, "AI判断失败"

    def is_topic_mess(self, title: str, content: str, rule_reason: str = "") -> tuple:
        """AI复核：文章是否真的是主题杂糅/聚合快讯"""
        content_preview = content[:2000] if content else ""
        if len((content or "").strip()) < 30:
            return False, "内容过短，AI不判定为杂糅"

        prompt = f"""你是一位资深新闻编辑。请判断下面这篇文章是否属于"主题杂糅/聚合快讯型水文"。

文章标题：{title}
文章内容：{content_preview}

规则引擎给出的怀疑理由（供参考，可能误判）：{rule_reason or "无"}

判定口径（非常重要，请严格按此理解）：
- "主题杂糅/聚合快讯"指：文章用"与此同时""此外""另外"等连接词把3个及以上**彼此没有因果/论证关系**的独立新闻硬拼到一起，缺乏统一主题与论证主线。
- 以下情况**不是**杂糅，即便涉及多个领域也应保留（回答false）：
  1. 文章有一个明确的聚焦主题或核心事件，其它领域只是为说明/影响/背景服务。
  2. 跨领域因果/影响分析：A领域事件如何影响B领域。
  3. 深度解读、评论、专访、行业观察，围绕单一主线展开论述。

请严格按以下JSON格式回复（只回复JSON，不要任何其它内容）：
{{"is_mess": true/false, "reason": "一句话说明"}}"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            is_mess = bool(result.get("is_mess", False))
            reason = str(result.get("reason", ""))
            logger.info(f"AI杂糅复核: 标题='{title[:30]}...', 结果={is_mess}, 原因={reason}")
            return is_mess, reason
        except Exception as e:
            logger.error(f"AI杂糅复核失败: {e}")
            return False, f"AI判断失败（保守保留）：{e}"

    # ==================== 批量并发 ====================

    def batch_classify_advertisement(self, articles: List[dict]) -> List[dict]:
        """批量并发判断文章是否为广告/噪音（8线程）"""
        if not articles:
            return []

        results = [{'is_ad': False, 'reason': ''}] * len(articles)
        lock = threading.Lock()

        def _judge_single(idx, article):
            title = article.get('title', '')
            content = article.get('content', '')
            try:
                is_ad, reason = self.is_advertisement(title, content)
                with lock:
                    results[idx] = {'is_ad': is_ad, 'reason': reason}
            except Exception as e:
                logger.error(f"广告判断失败: {title[:30]}... 错误: {e}")

        with ThreadPoolExecutor(max_workers=API_MAX_CONCURRENCY) as executor:
            futures = []
            for i, article in enumerate(articles):
                future = executor.submit(_judge_single, i, article)
                futures.append(future)
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"广告判断异常: {e}")

        return results

    # ==================== 聚合新闻/社会评论过滤 ====================

    def is_aggregated_news(self, title: str, summary: str) -> bool:
        """判断是否是聚合新闻"""
        if re.search(r'\|', title) and len(title) < 100:
            before_bar = title.split('|')[0].strip()
            if '、' in before_bar and before_bar.count('、') >= 2:
                return True

        if re.search(r'.+和.+以及', title):
            return True

        prompt = f"""请判断以下文章是否是"聚合新闻"——即一条资讯包含多个完全不相关的主题。

文章标题：{title}
文章摘要：{summary[:800] if summary else "无"}

判断标准：
- 聚合新闻 = 一条资讯像新闻简报一样，汇总了多个完全不相关的主题
- 正常报道 = 整篇文章围绕一个主题深度展开

以下情况**不是**聚合新闻：
- 正常深度报道包含"另外"、"与此同时"等补充内容
- 一篇文章讨论同一事件的多个方面或时间线
- 同一主题下的多个人物/观点报道

请严格按照以下JSON格式回复（只回复JSON，不要有其他内容）：
{{"is_aggregated": true或false, "reason": "简要判断理由"}}"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            return result.get("is_aggregated", False)
        except Exception as e:
            logger.error(f"聚合新闻判断失败: {e}")
            return False

    def is_social_commentary(self, title: str, summary: str) -> bool:
        """判断是否是社会评论/外界误解分析类内容"""
        combined = title + " " + summary

        commentary_patterns = [
            r'误解', r'最大误解', r'误区', r'外界.*认为',
            r'并非.*只是', r'不是.*而是', r'真相是', r'现实是',
            r'熬出头', r'熬到.*岁',
        ]

        for pattern in commentary_patterns:
            if re.search(pattern, title):
                return True

        commentary_sentences = [
            r'外界认为', r'却不知道', r'要考一辈子试', r'卷一辈子',
            r'熬出头', r'越老越值钱', r'并非.*那么简单',
            r'不是.*那么容易', r'现实.*残酷', r'这种误解', r'善意安慰',
        ]

        match_count = sum(1 for p in commentary_sentences if re.search(p, summary))
        if match_count >= 2:
            return True

        prompt = f"""请判断以下文章是否是"社会评论/外界误解分析类"内容。

文章标题：{title}
文章摘要：{summary[:800]}

这类内容的特征：
1. 揭示"外界对某职业/群体的误解"
2. 分析"现实与想象的差距"
3. 用"XX不是XX"、"XX并非XX"、"XX最大误解"的句式
4. 大量感慨性语言，如"太难了"、"太卷了"、"熬出头"、"越老越值钱"
5. 作者以"圈内人"视角向外行人解释行业真相

非此类内容：客观的新闻报道、政策解读、数据分析、深度调查报道

请严格按照以下JSON格式回复（只回复JSON，不要有其他内容）：
{{"is_commentary": true或false, "reason": "简要判断理由"}}"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            return result.get("is_commentary", False)
        except Exception as e:
            logger.error(f"社会评论判断失败: {e}")
            return False

    # ==================== 文章融合 ====================

    def merge_articles(self, articles: List[Dict[str, Any]]) -> Dict[str, Any]:
        """将同一题材的多篇文章进行AI融合"""
        if not articles:
            return {}
        if len(articles) == 1:
            return {
                "merged_title": articles[0].get('title', ''),
                "merged_content": articles[0].get('summary', ''),
                "timeline": [],
                "viewpoints": [],
                "links": [articles[0].get('link', '')],
                "sources": [articles[0].get('source_name', '')]
            }

        articles_text = []
        for i, art in enumerate(articles, 1):
            articles_text.append(f"""
--- 文章{i} ---
标题：{art.get('title', '')}
来源：{art.get('source_name', '')}
发布时间：{art.get('pub_date', '')}
链接：{art.get('link', '')}
摘要：{art.get('summary', '')}
""")

        articles_input = "\n".join(articles_text)

        prompt = f"""你是一个专业的内容整合专家。请将以下多篇关于同一题材的文章进行深度融合。

【融合要求】
1. **信息并集**：保留所有文章中的有价值信息，不遗漏
2. **时间线整理**：如果涉及事件发展，按时间顺序整理叙事
3. **观点分块**：将不同角度/不同立场的内容分别整理
4. **生成摘要标题**：基于融合内容生成一个简洁准确的标题
5. **汇总链接**：收集所有原文链接

【待融合文章】
{articles_input}

【输出格式】
请严格按照以下JSON格式回复（只回复JSON，不要有其他内容）：
{{
    "merged_title": "融合后的标题（简洁准确，15-30字）",
    "merged_content": "融合后的内容摘要（300-500字，保留关键信息点）",
    "timeline": [
        {{"time": "时间点1", "event": "事件描述1"}}
    ],
    "viewpoints": [
        {{"viewpoint": "观点类型1", "content": "该观点的具体内容"}}
    ],
    "links": ["链接1", "链接2", "链接3"],
    "sources": ["来源1", "来源2", "来源3"]
}}

注意事项：
- merged_content 应该是一个连贯的、逻辑清晰的摘要，而非简单拼接
- 如果各文章信息有冲突，保留不同说法并注明
- timeline 和 viewpoints 可以为空数组
- 链接必须是原始文章链接，不要虚构
"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            logger.info(f"文章融合完成: {len(articles)}篇文章 -> 标题'{result.get('merged_title', '')[:30]}...'")
            return result
        except Exception as e:
            logger.error(f"文章融合失败: {e}")
            return {
                "merged_title": articles[0].get('title', ''),
                "merged_content": articles[0].get('summary', ''),
                "timeline": [],
                "viewpoints": [],
                "links": [a.get('link', '') for a in articles],
                "sources": [a.get('source_name', '') for a in articles]
            }

    # ==================== 文章比较/事件判断 ====================

    def compare_articles(self, article1: dict, article2: dict) -> int:
        """比较两篇文章质量，返回1/-1/0"""
        content1 = article1.get('content', '')[:3000] if article1.get('content') else ""
        content2 = article2.get('content', '')[:3000] if article2.get('content') else ""

        prompt = f"""请比较以下两篇文章，判断哪个内容更全面、更客观、分析更透彻。

文章1:
标题：{article1.get('title', '')}
来源：{article1.get('source_name', '')}
内容：{content1}

文章2:
标题：{article2.get('title', '')}
来源：{article2.get('source_name', '')}
内容：{content2}

评判标准：信息全面性 > 分析深度 > 客观性 > 时效性

请严格按照以下格式回复（只回复JSON）：
{{"better": 1或-1或0, "reason": "简短原因"}}

如果文章1更好返回better:1，文章2更好返回better:-1，差不多返回better:0"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            return result.get("better", 0)
        except Exception as e:
            logger.error(f"文章对比失败: {e}")
            return 0

    def is_same_event(self, article1: dict, article2: dict) -> bool:
        """判断两篇文章是否在讲同一事件"""
        title1, title2 = article1.get('title', ''), article2.get('title', '')
        summary1, summary2 = article1.get('ai_summary', ''), article2.get('ai_summary', '')

        names1 = set(re.findall(r'[\u4e00-\u9fa5]{2,4}(?=\s*(霸凌|事件|传闻|争议|回应|澄清|调查|热搜|舆情))', title1 + summary1))
        names2 = set(re.findall(r'[\u4e00-\u9fa5]{2,4}(?=\s*(霸凌|事件|传闻|争议|回应|澄清|调查|热搜|舆情))', title2 + summary2))

        if names1 and names2 and names1 == names2:
            return True

        prompt = f"""请判断以下两篇文章是否在讲同一事件或话题。

文章1: 标题：{title1}，摘要：{summary1}
文章2: 标题：{title2}，摘要：{summary2}

判断标准：
- 核心内容围绕同一个具体事件、话题或人物 → 同一事件
- 讨论完全不相关的内容 → 不同事件
- 特别注意：如果两篇文章都在讨论同一个人物，即使角度不同，也应认为是同一事件

请严格按照以下格式回复（只回复JSON）：
{{"is_same": true或false}}"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            return result.get("is_same", False)
        except Exception as e:
            logger.error(f"事件判断失败: {e}")
            return False

    # ==================== 分类 ====================

    def classify_article(self, title: str, summary: str) -> str:
        """使用AI判断文章的MECE分类编号"""
        content_preview = summary[:1000] if summary else ""

        prompt = f"""请根据以下文章内容，判断其最合适的MECE分类编号。

文章标题：{title}
文章摘要：{content_preview}

MECE分类体系（11个大类，每个大类下有子分类）：
1. 国际局势与地缘政治
   1.1 地区冲突与战争  1.2 国际关系与外交  1.3 全球安全与反恐
2. 宏观经济与金融
   2.1 国内宏观经济  2.2 宏观消费与零售  2.3 资本市场  2.4 房地产市场  2.5 全球金融
3. 文化娱乐内容
   3.1 文化产业  3.2 体育休闲  3.3 体验消费  3.4 网络与数字文化
4. 科技产业与创新
   4.1 人工智能  4.2 信息技术  4.3 智能制造与机器人  4.4 新能源与绿色科技
5. 医疗健康与生命科学
   5.1 医疗改革与政策  5.2 医学研究与突破  5.3 公共卫生
6. 教育发展与人才培养
   6.1 教育政策与改革  6.2 高等教育  6.3 教育科技  6.4 就业与人才
7. 社会民生与消费
   7.1 民生消费  7.2 就业与职场  7.3 人口与家庭  7.4 社会治理
8. 企业与商业
   8.1 企业经营  8.2 商业动态  8.3 电商与新零售  8.4 创业与创新
9. 政策法规与监管
   9.1 国家政策  9.2 行业监管  9.3 地方治理  9.4 反腐与廉政
10. 能源与资源
    10.1 传统能源  10.2 新能源  10.3 资源与环境
11. 社会热点与舆论动态
    11.1 热点事件  11.2 舆情分析  11.3 跨界热点

判断逻辑：
- AI相关内容统一归入4.1
- 涉及人物+丑闻/争议 → 11.1（涉及AI的除外→4.1）
- 国际冲突/战争 → 1.1
- 产品质量/虚假宣传/消费者权益 → 11.1
- 游戏版权/私服/娱乐产业纠纷 → 3.1
- 政策解读/监管分析 → 9类
- 交叉主题涉及AI的 → 4类

请严格按照以下JSON格式回复（只回复JSON，不要有其他内容）：
{{"category": "分类编号", "reason": "简要判断理由"}}"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            category = result.get("category", "")
            valid_categories = [
                "1", "1.1", "1.2", "1.3",
                "2", "2.1", "2.2", "2.3", "2.4", "2.5",
                "3", "3.1", "3.2", "3.3", "3.4",
                "4", "4.1", "4.2", "4.3", "4.4",
                "5", "5.1", "5.2", "5.3",
                "6", "6.1", "6.2", "6.3", "6.4",
                "7", "7.1", "7.2", "7.3", "7.4",
                "8", "8.1", "8.2", "8.3", "8.4",
                "9", "9.1", "9.2", "9.3", "9.4",
                "10", "10.1", "10.2", "10.3",
                "11", "11.1", "11.2", "11.3"
            ]
            if category in valid_categories:
                return category
            return "11.3"
        except Exception as e:
            logger.error(f"AI分类判断失败: {e}")
            return "11.3"

    def batch_classify_mece(self, articles: List[dict]) -> List[str]:
        """批量并发判断文章MECE分类"""
        if not articles:
            return []

        results = ['11.3'] * len(articles)
        lock = threading.Lock()

        def _classify_single(idx, article):
            title = article.get('title', '')
            summary = article.get('summary', '')
            try:
                category = self.classify_article(title, summary)
                with lock:
                    results[idx] = category
            except Exception as e:
                logger.error(f"分类失败: {title[:30]}... 错误: {e}")

        with ThreadPoolExecutor(max_workers=API_MAX_CONCURRENCY) as executor:
            futures = []
            for i, article in enumerate(articles):
                future = executor.submit(_classify_single, i, article)
                futures.append(future)
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"分类异常: {e}")

        return results

    # ==================== 标题优化 ====================

    def optimize_title(self, original_title: str, content: str = "") -> str:
        """优化文章标题，使其更像新闻标题"""
        if not original_title.strip():
            return original_title

        if original_title.startswith("【") and "】" in original_title:
            title_content = original_title[original_title.find("【")+1:original_title.find("】")]
            if 15 <= len(title_content) <= 50:
                return original_title

        content_preview = content[:2000] if content else ""

        system_prompt = "你是一个专业的新闻标题优化专家，擅长将冗长的标题优化为简洁、聚焦、有信息量的新闻标题。"

        user_prompt = f"""请优化以下文章标题，使之更加简洁、聚焦、有信息量，像一个真正的新闻标题。

原标题：{original_title}
文章内容预览：{content_preview}

优化要求：
1. 结果必须是【优化后的标题】格式，包含【】符号
2. 标题要：简洁、聚焦、像新闻标题、有信息量
3. 长度控制在15-50字之间
4. 去除学术化、冗长、不够聚焦的表达
5. 直接输出优化后的标题，不要有任何解释说明

请输出优化后的标题："""

        try:
            response = self._call_api_with_system(system_prompt, user_prompt)
            optimized_title = response.strip()
            # 确保包含【】
            if not optimized_title.startswith("【"):
                optimized_title = f"【{optimized_title}】"
            # 移除markdown加粗
            optimized_title = re.sub(r'\*\*(.*?)\*\*', r'\1', optimized_title)
            if optimized_title:
                return optimized_title
            return original_title
        except Exception as e:
            logger.error(f"标题优化失败: {e}")
            return original_title

    def batch_optimize_titles(self, articles: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """批量并发优化文章标题"""
        if not articles:
            return articles

        results = [None] * len(articles)
        lock = threading.Lock()

        def _optimize_single(idx, article):
            original = article.get('title', '')
            content = article.get('content', '')
            try:
                optimized = self.optimize_title(original, content) if original else original
                with lock:
                    results[idx] = optimized
            except Exception as e:
                logger.error(f"标题优化失败: {original[:30]}... 错误: {e}")
                with lock:
                    results[idx] = original

        with ThreadPoolExecutor(max_workers=API_MAX_CONCURRENCY) as executor:
            futures = []
            for i, article in enumerate(articles):
                future = executor.submit(_optimize_single, i, article)
                futures.append(future)
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"标题优化异常: {e}")

        for i, optimized in enumerate(results):
            if optimized is not None:
                articles[i]['title'] = optimized

        return articles

    # ==================== AI二次验证 ====================

    def verify_same_topic(self, articles: List[Dict[str, Any]]) -> bool:
        """验证多篇文章是否属于同一主题/事件（适用于每周资讯整合场景）"""
        if not articles or len(articles) < 2:
            return False

        if len(articles) == 2:
            title1 = articles[0].get('title', '')
            summary1 = articles[0].get('summary', '')[:500]
            title2 = articles[1].get('title', '')
            summary2 = articles[1].get('summary', '')[:500]

            prompt = f"""请判断以下两篇文章是否属于【同一主题/事件】，可以合并为一条每周资讯。

文章1: 标题：{title1}，摘要：{summary1}
文章2: 标题：{title2}，摘要：{summary2}

判定为"同一主题"的情况（满足任一即可）：
1. 两篇文章讨论同一具体事件（如：同一事故、同一政策的不同报道）
2. 两篇文章讨论同一持续发展事件/冲突的不同阶段或方面（如：同一场战争的不同战役/进展、同一事件的因果链条）
3. 两篇文章围绕同一人物/组织/产品的同一相关事件（如：同一公司发布不同产品、同一人涉及的不同法律程序、同一冲突中不同方的行动）
4. 两篇文章的核心实体（国家、人物、组织、产品名）高度重叠，且讨论同一领域同一大事件的不同角度

不应判定为"同一主题"的情况：
1. 只是碰巧提到同一个国家/行业/领域，但具体事件完全不同
2. 只是共享一个泛泛概念（如"经济""科技""AI"），但具体事件无关

请严格按照以下JSON格式回复（只回复JSON，不要有其他内容）：
{{"is_same_topic": true或false, "reason": "简要判断理由"}}"""
        else:
            articles_text = []
            for i, art in enumerate(articles, 1):
                articles_text.append(f"文章{i}: 标题：{art.get('title', '')}，摘要：{art.get('summary', '')[:400]}")

            prompt = f"""请判断以下{len(articles)}篇文章是否属于【同一主题/事件系列】，可以合并为一条每周资讯。

{chr(10).join(articles_text)}

判定为"同一主题"的情况（满足任一即可）：
1. 这些文章讨论同一具体事件的不同报道
2. 这些文章讨论同一持续发展事件/冲突的不同阶段或方面（如：同一场战争的不同战役、同一事件的时间线进展）
3. 这些文章围绕同一人物/组织/产品的同一相关事件的不同角度
4. 这些文章的核心实体高度重叠，属于同一大事件的不同侧面

不应判定为"同一主题"的情况：
1. 只是碰巧提到同一个国家/行业/领域，但具体事件完全不同
2. 只是共享一个泛泛概念，但具体事件无关

请严格按照以下JSON格式回复（只回复JSON，不要有其他内容）：
{{"is_same_topic": true或false, "reason": "简要判断理由"}}"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            is_same = result.get("is_same_topic", False)
            if not is_same:
                logger.info(f"AI验证未通过: 这{len(articles)}篇文章不是同一主题")
            else:
                logger.info(f"AI验证通过: 这{len(articles)}篇文章是同一主题")
            return is_same
        except Exception as e:
            logger.error(f"AI验证失败: {e}")
            return False

    # ==================== TF-IDF 相似度计算 ====================

    @staticmethod
    def _tokenize_for_tfidf(text: str) -> List[str]:
        """对中文文本进行智能分词，用于TF-IDF计算"""
        if not text:
            return []

        stop_words_2 = {'的', '是', '在', '了', '和', '与', '或', '也', '都', '很',
                       '一个', '这个', '那个', '什么', '怎么', '如何', '怎样',
                       '可以', '已经', '可能', '需要', '我们', '他们', '自己',
                       '因为', '所以', '但是', '然而', '虽然', '如果', '就是',
                       '不是', '没有', '这样', '那样', '这些', '那些', '一些',
                       '很多', '不少', '部分', '多数', '少数', '基本', '主要',
                       '进行', '通过', '对于', '关于', '目前', '表示', '认为',
                       '成为', '引发', '关注', '情况', '问题', '原因', '影响',
                       '记者', '消息', '报道', '公开', '相关', '事件', '回应',
                       '处理', '调查', '官方', '说明', '全国', '各地', '社会',
                       '网络', '网友', '不断', '持续', '显著', '明显', '有效',
                       '同时', '此外', '另外', '然而', '不过', '因此', '此时',
                       '此前', '之后', '期间', '其中', '以后', '以来', '之际',
                       '包括', '以及', '还是', '又是', '而且', '还是', '之间',
                       '根据', '按照', '属于', '位于', '来自', '称为', '名为',
                       '同时', '不同', '其他', '所有', '各种', '每个', '这次',
                       '上次', '下次', '这次', '这次', '此次', '以上', '以下'}

        words = []

        # 提取英文词
        eng_words = re.findall(r'[a-zA-Z]{2,}', text)
        words.extend([w.lower() for w in eng_words])

        # 提取数字+单位组合
        num_units = re.findall(r'\d+(?:\.\d+)?(?:点|%|亿|万|千|元|美元|块|年|月|日|天|次|人|篇|对|组|岁|名|位|家|所|条|项|期|轮|批|起|宗|份|册|座|辆|架|艘|台|套|件)', text)
        words.extend(num_units)

        # 提取纯数字（2位以上）
        numbers = re.findall(r'\d+', text)
        words.extend([n for n in numbers if len(n) >= 2])

        # 对中文部分提取n-gram
        chinese_text = re.sub(r'[^\u4e00-\u9fa5]', '', text)

        # 4字n-gram
        for i in range(len(chinese_text) - 3):
            word = chinese_text[i:i+4]
            if len(set(word)) > 1:
                words.append(word)

        # 3字n-gram
        for i in range(len(chinese_text) - 2):
            word = chinese_text[i:i+3]
            if len(set(word)) > 1:
                words.append(word)

        # 2字n-gram
        for i in range(len(chinese_text) - 1):
            word = chinese_text[i:i+2]
            if word not in stop_words_2 and len(set(word)) > 1:
                words.append(word)

        return words

    @staticmethod
    def compute_tfidf_embeddings(texts: List[str]) -> np.ndarray:
        """基于TF-IDF计算文本向量（BM25风格IDF）"""
        if not texts:
            return np.array([])

        tokenized = []
        for text in texts:
            words = DeepSeekClient._tokenize_for_tfidf(text)
            tokenized.append(words)

        all_words = set()
        for words in tokenized:
            all_words.update(words)

        if not all_words:
            return np.zeros((len(texts), 1))

        vocab = sorted(all_words)
        word_to_idx = {w: i for i, w in enumerate(vocab)}
        n_features = len(vocab)

        n_docs = len(texts)

        # 文档频率
        df = np.zeros(n_features)
        for words in tokenized:
            seen = set()
            for w in words:
                if w in word_to_idx and w not in seen:
                    df[word_to_idx[w]] += 1
                    seen.add(w)

        # BM25风格IDF
        idf = np.log((n_docs - df + 0.5) / (df + 0.5) + 1)

        # TF-IDF矩阵
        k1 = 1.5
        b = 0.75
        doc_lengths = [len(words) for words in tokenized]
        avgdl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1

        tfidf_matrix = np.zeros((n_docs, n_features))
        for i, words in enumerate(tokenized):
            word_count = {}
            for w in words:
                if w in word_to_idx:
                    word_count[word_to_idx[w]] = word_count.get(word_to_idx[w], 0) + 1
            dl = doc_lengths[i]
            for idx, count in word_count.items():
                tf_norm = (count * (k1 + 1)) / (count + k1 * (1 - b + b * dl / avgdl))
                tfidf_matrix[i, idx] = tf_norm * idf[idx]

        # L2归一化
        norms = np.linalg.norm(tfidf_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        tfidf_matrix = tfidf_matrix / norms

        return tfidf_matrix

    @staticmethod
    def cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
        """计算余弦相似度矩阵"""
        if embeddings.size == 0:
            return np.array([])
        # 已L2归一化，余弦相似度=点积
        return embeddings @ embeddings.T

    def find_similar_groups_v2(self, articles: List[dict]) -> List[Tuple[int, int, float]]:
        """找出所有相似的文章对（使用TF-IDF+余弦相似度）"""
        if not articles:
            return []

        texts = []
        titles = []
        for art in articles:
            combined = f"{art.get('title', '')} {art.get('ai_summary', '')}"
            texts.append(combined)
            titles.append(art.get('title', '')[:50])

        n = len(texts)
        logger.info(f"开始TF-IDF+余弦相似度计算，共{n}篇文章...")

        embeddings = self.compute_tfidf_embeddings(texts)
        if embeddings.size == 0:
            logger.warning("TF-IDF向量为空，无法计算相似度")
            return []

        sim_matrix = self.cosine_similarity_matrix(embeddings)

        high_sim_pairs = []
        medium_sim_pairs = []
        low_sim_pairs = []

        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim >= HIGH_SIM_THRESHOLD:
                    high_sim_pairs.append((i, j, sim))
                elif sim >= MEDIUM_SIM_THRESHOLD:
                    medium_sim_pairs.append((i, j, sim))
                elif sim >= LOW_SIM_THRESHOLD:
                    low_sim_pairs.append((i, j, sim))

        logger.info(f"TF-IDF相似度筛选: 高相似{len(high_sim_pairs)}对, 中相似{len(medium_sim_pairs)}对, 低相似{len(low_sim_pairs)}对")

        return high_sim_pairs + medium_sim_pairs + low_sim_pairs

    # ==================== 关键词提取（兼容旧方法） ====================

    def _extract_keywords(self, text: str) -> set:
        """提取文本的关键词"""
        if not text:
            return set()

        keywords = set()
        english_words = re.findall(r'[a-zA-Z]{2,}', text)
        keywords.update([w.lower() for w in english_words])
        numbers = re.findall(r'\d+', text)
        keywords.update(numbers)

        person_names = re.findall(r'[\u4e00-\u9fa5]{2,4}(?:霸凌|传闻|事件|争议|回应|澄清|调查|热搜|舆情|风波|丑闻)', text)
        keywords.update(person_names)

        victim_patterns = re.findall(r'([\u4e00-\u9fa5]{2,4})(?:遭|被|陷|陷入)', text)
        keywords.update(victim_patterns)

        chinese_text = re.sub(r'[^\u4e00-\u9fa5]', '', text)
        for length in [2, 3]:
            for i in range(len(chinese_text) - length + 1):
                word = chinese_text[i:i+length]
                stop_words = ['的', '是', '在', '了', '和', '与', '或', '也', '都', '很',
                             '一个', '这个', '那个', '什么', '怎么', '如何', '怎样']
                if word not in stop_words and len(set(word)) > 1:
                    keywords.add(word)

        return keywords

    def _jaccard_similarity(self, set1: set, set2: set) -> float:
        """计算Jaccard相似度"""
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        if union == 0:
            return 0.0
        return intersection / union

    def find_similar_groups(self, articles: List[dict]) -> List[Tuple[int, int]]:
        """找出所有相似的文章对（使用关键词+Jaccard相似度，兼容旧方法）"""
        if not articles:
            return []

        texts = []
        for art in articles:
            combined = f"{art.get('title', '')} {art.get('ai_summary', '')}"
            texts.append(combined)

        all_keywords = [self._extract_keywords(text) for text in texts]
        similar_pairs = []
        n = len(texts)

        for i in range(n):
            for j in range(i + 1, n):
                similarity = self._jaccard_similarity(all_keywords[i], all_keywords[j])
                if similarity >= SIMILARITY_THRESHOLD:
                    similar_pairs.append((i, j))

        return similar_pairs

    # ==================== API调用 ====================

    def _call_api(self, prompt: str) -> str:
        """调用DeepSeek API"""
        return self._call_api_with_system("你是一个专业的内容分析师，擅长判断文章相似性和质量对比。", prompt)

    def _call_api_with_system(self, system_prompt: str, user_prompt: str) -> str:
        """调用DeepSeek API（支持自定义system prompt，含重试和并发控制）"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        data = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2000,
        }

        last_exc: Optional[Exception] = None

        with _API_SEMAPHORE:
            for attempt in range(API_MAX_RETRIES + 1):
                try:
                    response = requests.post(
                        self.api_base,
                        headers=headers,
                        json=data,
                        timeout=API_TIMEOUT_SECONDS,
                    )

                    if response.status_code == 429 or 500 <= response.status_code < 600:
                        raise requests.HTTPError(
                            f"Retryable HTTP {response.status_code}: {response.text[:200]}",
                            response=response,
                        )

                    response.raise_for_status()
                    result = response.json()
                    return result["choices"][0]["message"]["content"]

                except (
                    requests.Timeout,
                    requests.ConnectionError,
                    requests.HTTPError,
                ) as e:
                    last_exc = e
                    if attempt >= API_MAX_RETRIES:
                        break
                    backoff = min(
                        API_BACKOFF_BASE * (2 ** attempt),
                        API_BACKOFF_CAP,
                    )
                    backoff += random.uniform(0, 0.5)
                    logger.warning(
                        f"DeepSeek API 调用失败（第{attempt + 1}/{API_MAX_RETRIES + 1}次），"
                        f"{backoff:.1f}s 后重试: {type(e).__name__}: {str(e)[:150]}"
                    )
                    time.sleep(backoff)
                except Exception as e:
                    last_exc = e
                    break

        assert last_exc is not None
        raise last_exc
