#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DeepSeek AI客户端 - 用于内容摘要和广告判断
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
# 单次 HTTP 请求超时（秒）。原 30s 太紧，API 慢响应时容易直接 Read timed out。
API_TIMEOUT_SECONDS = 90
# 失败重试次数（不含首次调用）。总尝试 = 1 + MAX_RETRIES
API_MAX_RETRIES = 4
# 指数退避基数（秒）：第 n 次重试等待 BASE * 2**(n-1) + 抖动
API_BACKOFF_BASE = 1.0
API_BACKOFF_CAP = 30.0  # 单次退避最长等待
# 全局并发闸门：同一时刻最多允许多少个 DeepSeek 请求在飞行
# 即便以后用 ThreadPoolExecutor 并发调用，也不会一次打爆几十个连接
API_MAX_CONCURRENCY = 8
_API_SEMAPHORE = threading.Semaphore(API_MAX_CONCURRENCY)
# =================================================================

    # 相似度阈值：基于Embedding余弦相似度
# 三级阈值策略：
# - HIGH_SIM_THRESHOLD (>=0.85): 几乎确定是同一事件，直接去重，无需LLM
# - MEDIUM_SIM_THRESHOLD (>=0.65): 疑似同一事件，需要LLM二次确认
# - 低于MEDIUM_SIM_THRESHOLD: 不同事件，保留
SIMILARITY_THRESHOLD = 0.15  # 旧Jaccard阈值，保留兼容
HIGH_SIM_THRESHOLD = 0.12    # 高相似度：直接去重（TF-IDF n-gram相似度范围较低）
MEDIUM_SIM_THRESHOLD = 0.07  # 中相似度：需LLM判断
LOW_SIM_THRESHOLD = 0.04     # 低相似度：结合规则判断

class DeepSeekClient:
    """DeepSeek API客户端"""

    def __init__(self, api_key: str):
        """
        初始化DeepSeek客户端

        Args:
            api_key: DeepSeek API密钥
        """
        self.api_key = api_key
        self.api_base = "https://api.deepseek.com/v1/chat/completions"
        self.model = "deepseek-chat"
        self.chat_model = "deepseek-chat"

    def classify_ad_and_mece(self, title: str, content: str) -> dict:
        """
        合并广告判断+MECE分类为一次API调用，省token

        Args:
            title: 文章标题
            content: 文章内容（可以是正文或摘要）

        Returns:
            {"is_ad": bool, "reason": str, "category": str}
            非广告时category为MECE分类编号，广告时category为空
        """
        # 限制内容长度
        content_preview = content[:2000] if content else ""

        # 检测内容是否过短或仅有占位符
        content_length = len(content.strip()) if content else 0
        placeholder_patterns = ['阅读全文', '预览时标签不可点', '展开全文', '点击展开', '更多精彩内容']
        has_placeholder = any(p in content_preview for p in placeholder_patterns)

        # 如果内容过短或只有占位符，直接判断为无效
        if content_length < 50 or (has_placeholder and content_length < 200):
            logger.info(f"AI广告+分类: 标题='{title[:30]}...', 结果=广告(内容缺失)")
            return {"is_ad": True, "reason": "内容缺失或仅含占位符", "category": ""}

        prompt = f"""请对以下文章完成两项判断：①是否应过滤 ②如不过滤则归入MECE分类。

文章标题：{title}
文章内容：{content_preview}

=== 第一项：是否过滤 ===
过滤标准（符合任一即过滤）：
1. 广告推销类：产品推销、商业宣传、购买引导、联系方式/二维码、明显商业软文
2. 科普水文类：纯历史/植物/动物/食物起源科普、生活小妙招盘点，缺乏当前新闻性
3. 鸡汤励志类：空洞人生哲理、励志名言、成功学、个人感悟，缺乏新闻价值
4. 医学案例水文类：以罕见病例/医学案例为卖点，缺乏公共卫生意义
5. 地方小新闻类：地方院校/医院动态、区域性事件，缺乏全国性影响
6. 综合集成水文类：杂糅多个不相关话题、无聚焦的资讯汇总（如"8点1氪"类聚合快讯，一条文章同时包含外交、科技、金融等不相关话题）
7. 标题党/软文营销类：标题与内容不符、以"揭秘""震惊"开头但无实质分析
8. 比赛/竞赛宣传类：大赛启动公告、报名通知、赛程规程等
9. 地方天气预报/天气景观类：普通天气预报、七彩祥云/彩虹等市民拍照分享（极端天气灾害除外）
10. 纯历史回顾/历史考证类：全篇回顾历史事件或质疑历史记载，无当前事件关联
11. 普通学术论文类：结构方程模型、问卷调查等纯学术内容（Nature/Science级别除外）
12. 非重大学生个人事件类：个别学生退学/处分等（重大恶性事件除外）
13. 地方普通人事任免类：常规人事任免（副省级以上或反腐除外）
14. 微小地方事件类：缺乏全国性新闻价值的地方小事件（引发全国舆情除外）
15. 股市单日数据播报类：北向资金/龙虎榜等纯数据播报，缺乏分析
16. 考公考编备考建议类：备考策略、路线选择等指南类文章

注意：分析当前经济/社会/政治事件的文章即使引用历史背景也要保留。

17. 产品外观/审丑争议类：围绕某产品"丑不丑""好不好看"的讨论，本质是主观审美争议，缺乏客观新闻价值（如"匡威新鞋被群嘲丑"）。除非涉及收购/退市/破产等重大商业事件

18. 单部影视/电影/剧集介绍类：对单部电影、电视剧、综艺的介绍、选角、剧情解读、幕后花絮、制作细节等。这类文章只介绍某个作品，没有展开对行业/社会的论述。影视行业重大事件（票房纪录、行业政策、税务丑闻、重大收购等）除外

19. 日常医疗健康科普类：蚊子叮咬科普、感冒预防、防晒方法、饮水建议、睡眠改善、中暑预防等日常健康常识。这类文章提供通用健康知识，不是当日新闻。重大公共卫生事件（疫情、疫苗政策、药品审批、食品安全事件等）除外

20. 艺术流派/美术史研究类：分析历史画派风格变化、画中人物体态趋势、审美观念演变等纯学术研究。这类文章是对历史艺术的分析，不是当日新闻。重大文化事件（文物回归、天价拍卖、重大考古发现等）除外

21. 纯学术研究类（非顶级期刊）：普通学术研究（如"研究揭示某画作中人物体重指数下降趋势"），缺乏新闻价值。Nature/Science/Lancet级别突破除外
22. 主观非资讯类：以个人经历/主观感受为主，缺乏客观新闻价值的文章（如"医生自述崩溃瞬间：一人管80张床""疲劳行医成为标配"等职业日常吐槽）。除非涉及重大政策改革、官方回应等
23. 地方天气/防汛/汛期预测类：地方天气预报、汛期气候预测、防汛准备/形势/发布会等（如"北京汛期降水偏多2至4成""防汛办呼吁市民增强避险意识"）。极端灾害（地震、海啸、台风等）除外

22. 预测/前瞻性聚合新闻类：罗列未来一周/下周/本周将发生的多个不同领域的预测判断，如"下周宏观与科技事件密集：PCE数据影响降息预期，XX公司IPO上会"等。这类文章是对未来事件的预告和预测聚合，不是已发生的新闻。对单个已发生事件的前瞻分析（如"降息后市场走势展望"）除外

23. 宠物领养/寻主/流浪动物救助类：宠物寻找主人、流浪猫狗领养公告等琐碎信息（如"萌宠寻人启事：五只流浪狗等待领养"），缺乏全国性新闻价值。重大动物保护事件（大规模虐待动物案、野生动物保护立法等）除外

24. 多事件主观评论/政府批判类：将多个不相关事件拼凑在一起批判政府/体制公信力的文章（如将食品安全事件和矿难拼在一起说"监管失守""信任危机"），这类文章主观性强、不客观。对单一事件的客观监管分析除外

=== 第二项：MECE分类（仅非广告时填写） ===
MECE分类体系：
1. 国际局势与地缘政治: 1.1地区冲突与战争 1.2国际关系与外交 1.3全球安全与反恐
2. 宏观经济与金融: 2.1国内宏观经济 2.2宏观消费与零售 2.3资本市场 2.4房地产市场 2.5全球金融
3. 文体娱乐内容: 3.1文化产业 3.2体育休闲 3.3体验消费 3.4网络与数字文化
4. 科技产业与创新: 4.1人工智能 4.2信息技术 4.3智能制造与机器人 4.4新能源与绿色科技
5. 医疗健康与生命科学: 5.1医疗改革与政策 5.2医学研究与突破 5.3公共卫生
6. 教育发展与人才培养: 6.1教育政策与改革 6.2高等教育 6.3教育科技 6.4就业与人才
7. 社会民生与消费: 7.1民生消费 7.2就业与职场 7.3人口与家庭 7.4社会治理
8. 企业与商业: 8.1企业经营 8.2商业动态 8.3电商与新零售 8.4创业与创新
9. 政策法规与监管: 9.1国家政策 9.2行业监管 9.3地方治理 9.4反腐与廉政
10. 能源与资源: 10.1传统能源 10.2新能源 10.3资源与环境
11. 社会热点与舆论动态: 11.1热点事件 11.2舆情分析 11.3跨界热点

关键分类规则（按优先级从高到低）：
- **【最高优先级】涉及国际冲突/战争/停战/和平协议/谅解备忘录/外交谈判的国家间事件，必须归1类国际局势（1.1地区冲突与战争或1.2国际关系与外交）。如：美伊签署停战谅解备忘录、美伊和平协议达成、霍尔木兹海峡恢复通行等，绝对不是3类文体娱乐或4类科技产业**
- **【最高优先级】涉及影视行业/影视基地/影视产业的文章（如影视基地裁员、影视产业转型、影视行业AI冲击等），即使提及AI技术作为原因，也应归3.1文化产业。文章核心是影视行业本身的变化，AI只是影响因素。与短剧/小说/游戏同理，影视行业讨论归3类而非4类**
- AI相关内容统一归4.1（无论技术/应用/争议/伦理）——但影视/短剧/小说/游戏行业的AI应用例外，归3.1
- 涉及公众人物违法/丑闻/争议（不涉及AI的）归11.1
- 产品质量/虚假宣传/消费者权益争议归11.1
- 政府项目造假/资金滥用归11.1（非9.3）
- 动物保护/动物园事件归11.1（非5类）
- 国际冲突/战争归1.1
- 国际和平协议/停战协议/谅解备忘录/外交谈判归1.1或1.2
- 企业财报/经营数据/企业家事件归8类
- 游戏版权/影视产业归3.1
- 游戏IP版权和解/纠纷/诉讼归3.1（非8类企业商业）
- 影视/游戏IP相关的版权、知识产权纠纷、和解归3.1
- 网络流行消费品/玩具走红归3.4
- 交通便民服务归7.1
- 租房/住房保障政策（如毕业生专项租赁房源、公租房配租）归7.1民生消费（非8类企业商业）
- 政治人物的金融/证券交易行为（如总统炒股、内幕交易）归2.3资本市场或2.5全球金融（非11类社会热点）
- 政治人物的商业/经济行为归2类宏观经济与金融（非11类社会热点）
- **陪伴经济/情绪消费类文章（如付费陪爬、陪跑、陪吃、陪游、代排队等"陪伴服务"和"情绪价值消费"）归3.3体验消费（非7类社会民生或8类企业商业）**
- **执法冲突/暴力执法/城管商贩冲突等事件归11.1热点事件（非7.4社会治理），这类是社会热点舆情而非民生政策**
- **医生/护士等医疗行业职业困境（如疲劳行医、超负荷工作等），如果文章重点是体制/制度问题讨论则归5.1医疗改革与政策；如果只是个人职业日常吐槽则应归入11.1热点事件而非5类医疗健康（医疗健康类应聚焦疾病/公共卫生/医疗技术等客观信息）**
- **汛期气候预测、天气预报、防汛准备等地方天气新闻应归为过滤（is_ad=true），不应出现在分类中**

请严格按以下JSON格式回复（只回复JSON）：
{{"is_ad": true/false, "reason": "简短原因", "category": "分类编号或空字符串"}}

如果is_ad为true，category填空字符串""。
如果is_ad为false，category填分类编号（如"4.1"）。
不要有任何其他内容，只回复JSON。"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)

            is_ad = result.get("is_ad", False)
            reason = result.get("reason", "")
            category = result.get("category", "")

            # 非广告时验证分类编号
            if not is_ad and category:
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
                if category not in valid_categories:
                    logger.warning(f"AI分类无效: '{title[:30]}...' -> {category}，默认归入11.3")
                    category = "11.3"

            logger.info(f"AI广告+分类: 标题='{title[:30]}...', is_ad={is_ad}, category={category}, 原因={reason}")
            return {"is_ad": is_ad, "reason": reason, "category": category}

        except Exception as e:
            logger.error(f"AI广告+分类判断失败: {e}")
            return {"is_ad": False, "reason": "AI判断失败", "category": "11.3"}

    def is_topic_mess(self, title: str, content: str, rule_reason: str = "") -> tuple[bool, str]:
        """
        AI 复核：文章是否真的"主题杂糅 / 聚合快讯"。
        用于在规则噪音过滤把文章打成"聚合快讯类/内容杂糅类/综合集成式"时做二次确认，
        避免仅凭关键词出现次数误杀"跨领域深度分析"类文章（例如"美伊战争助推中国可再生能源战略"）。

        Args:
            title: 文章标题
            content: 文章正文 / 摘要
            rule_reason: 规则给出的过滤理由（可选，辅助 AI 参考）

        Returns:
            (is_mess, reason)
            - is_mess=True  表示确实是拼凑多话题的杂糅/聚合文章，应当过滤
            - is_mess=False 表示是围绕单一主题展开的合理分析，哪怕涉及多领域也应保留
        """
        content_preview = content[:2000] if content else ""
        if len((content or "").strip()) < 30:
            # 内容太少不足以判断，保守保留
            return False, "内容过短，AI 不判定为杂糅"

        prompt = f"""你是一位资深新闻编辑。请判断下面这篇文章是否属于"主题杂糅 / 聚合快讯型水文"。

文章标题：{title}
文章内容：{content_preview}

规则引擎给出的怀疑理由（供参考，可能误判）：{rule_reason or "无"}

判定口径（非常重要，请严格按此理解）：
- "主题杂糅/聚合快讯"指：文章用"与此同时""此外""另外"等连接词把 3 个及以上**彼此没有因果/论证关系**的独立新闻硬拼到一起，缺乏统一主题与论证主线。典型代表：股市早报、今日要闻、快讯汇总、城市发布（如"北京发布"类文章同时讲汛期天气、机器人比赛、电动自行车头盔率、退税商店、地铁线路、回迁等完全不相关话题）。
- **特别注意**：如果文章包含天气预报/汛期信息+其他不相关话题（如地铁线路、机器人比赛、头盔率等），即使只有2个不相关话题，也应判定为杂糅（天气预报本身就是噪音，不应出现在资讯中）。
- 以下情况**不是**杂糅，即便涉及多个领域也应保留（回答 false）：
  1. 文章有一个明确的聚焦主题或核心事件，其它领域只是为说明/影响/背景服务。
     例："美国对伊战争助推中国可再生能源战略" —— 聚焦"中国能源战略"，国际军事只是触发背景；
     例："教育部批准全国首个'商业人工智能'专业" —— 聚焦"新专业设立"，AI 与教育是同一主题的两个面。
  2. 跨领域因果/影响分析：A 领域事件如何影响 B 领域（"AI 冲击就业"、"加息如何影响楼市"等）。
  3. 深度解读、评论、专访、演讲全文、行业观察，围绕单一主线展开论述。
  4. 虽然摘要里出现多个领域关键词，但它们共同服务于同一个事件或同一个论点。

请严格按以下 JSON 格式回复（只回复 JSON，不要任何其它内容）：
{{"is_mess": true/false, "reason": "一句话说明"}}
"""
        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            is_mess = bool(result.get("is_mess", False))
            reason = str(result.get("reason", ""))
            logger.info(f"AI杂糅复核: 标题='{title[:30]}...', 结果={is_mess}, 原因={reason}")
            return is_mess, reason
        except Exception as e:
            logger.error(f"AI杂糅复核失败: {e}")
            # AI 失败时保守保留（即不认为是杂糅），避免把本来没问题的文章误杀
            return False, f"AI判断失败（保守保留）：{e}"

    def generate_summary(self, title: str, content: str, target_length: int = 500) -> tuple:
        """
        使用AI生成文章摘要和高标题（合并原摘要+标题优化为一次调用）

        Args:
            title: 文章标题
            content: 文章内容
            target_length: 目标摘要长度（字数）

        Returns:
            (摘要文本, 高标题文本) 的元组
        """
        # 如果内容本身很短，直接返回
        if not content:
            return "无内容", ""

        # 【修改】对于长文章，采用分段读取策略
        # 如果内容超过8000字，分段处理确保完整覆盖
        if len(content) > 8000:
            return self._generate分段_summary(title, content, target_length)
        
        # 限制输入长度（4000字已覆盖核心信息，对比实验验证质量无损，节省~47%输入token）
        content_preview = content[:4000]

        system_prompt = """你是一个专业的新闻摘要专家，擅长总结文章核心内容并生成高质量标题和摘要。

【核心原则】严格忠于原文，只总结文章中实际包含的信息，绝对不要添加自己的知识、推理或"合理补充"；即使某些背景信息是正确的，只要原文没提到就不能写进摘要。

【禁止使用的废话表述】
以下表述绝对禁止出现在摘要中：
- "原文未进一步说明""后续发展趋势尚不明朗""具体情况有待观察""相关方面尚未回应"
- 任何包含"未进一步""有待""尚不""尚未"的模糊敷衍表述
- 如果原文信息有限，也要尽可能把有限的信息写完整，不要用废话敷衍

【特别禁止】
- 禁止出现作者信息："作者自称""笔者认为""为读者介绍"等
- 禁止人物百科式背景：个人简历、毕业院校、出道经历等与核心事件无关的信息
- 禁止粗俗/网络用语："牛逼""炸裂""yyds"等
- 禁止元语言/文章结构描述："本文通过...""文章从...""文章首先...然后...""本文探讨了...""文章指出""文章分析了"等描述文章写作手法/结构的表述，摘要应直接陈述事实和观点
- 禁止"看似不相关""两个案例"等暗示文章写作技巧的表述
- **禁止口语化/煽情/夸张/煽动性表述**：如"别再惦记""赶紧""千万别""终于""竟然""没想到""原来""还在傻傻""醒醒吧""别怪我没提醒你""太意外了""重磅""炸了""沸腾了""刷屏了""出大事了""彻底慌了""坐不住了""不淡定了""忍不住了""看呆了""看傻了""吓傻了""被整破防了"等口语化、煽情、夸张、煽动性表达。摘要必须使用正式、客观、专业的新闻语体，用陈述句陈述事实。

摘要应使用正式、客观、专业的新闻语体。
"""

        user_prompt = f"""请仔细阅读以下文章的全部内容，然后同时生成一个高质量标题和精炼摘要。

文章标题：{title}
文章内容：
{content_preview}

【输出格式要求】（严格遵守）：
第1行：基于正文核心内容重新生成的简洁新闻标题，格式为【具体标题内容】
- **【绝对禁止】直接使用原文标题、原文标题的任何部分或原文标题的截取**。原文标题经常是标题党、比喻、悬念句，与文章实际内容完全无关。你必须完全基于文章正文内容提炼标题，绝不能偷懒照搬或截取原文标题
- 好的标题聚焦最重要的事实或观点：如【昔日硅谷宠儿Allbirds以2.68亿元被收购，市值大幅缩水】
- 避免笼统标题：如"农村经济爆了"→应改为【一季度农村消费增速8.5%超城镇3.2%】
- 标题长度15-50字
- **长标题必须用逗号切分**：当标题超过20字且包含两个及以上独立意群/分句时，用逗号分隔各意群，提高可读性。如"罗志恒建议开征超额利润调节税应对AI时代收入分配失衡"→"罗志恒建议开征超额利润调节税，应对AI时代收入分配失衡"。逗号应放在逻辑断点处（主谓之间、因果/目的/转折等关系词之前）
- **标题必须概括全文主旨**：读者只看标题就能知道文章的核心内容是什么
- **禁止在标题中使用比喻、修辞、俗语、谚语、古诗词**（如"怀念黄蓉""巧妇难为无米之炊""冰火两重天"等），必须用事实性语言描述
- **禁止使用原文标题中的比喻性表达**：如原文标题是"为什么今天我们如此怀念黄蓉？"但文章讲的是澳大利亚稀土矿业，标题应写【澳大利亚稀土矿业面临中国出口管制压力】而非保留"怀念黄蓉"
- **标题必须包含文章的核心事实**：涉及什么公司就写公司名，涉及什么事件就写事件名，涉及什么数据就写关键数据
- **禁止使用空洞的感叹句/疑问句作为标题**：如"谢谢所有来北京的朋友！"→应改为【五月天鸟巢演唱会12场吸引65万人次，掀起"跟着歌手游北京"新风潮】
- **禁止在标题中使用原文标题的前半部分/后半部分截取**：如原文标题"美国通知日本：数百枚战斧导弹严重延误"，绝不能生成【美国通知日本】或【数百枚战斧导弹严重延误】这种截取式标题，必须完全用自己的语言根据正文内容概括

第2行：空行

第3行起：极简摘要，用 4-6 句话概括，总字数严格不超过 100 字
- 用 4 到 6 个短句，覆盖原文最核心的事实、数据与结论，其余细节全部舍弃
- 每句话尽量短（十余字），只讲要点，不展开、不铺垫、不重复
- 第一句话直接讲正文核心事实，绝对不能照搬原文标题
- 总字数必须控制在 100 字以内（含标点），宁可少写也不要超
- 绝对不要出现发布元信息或"原文未进一步说明"等表述

不要有任何解释说明，直接输出标题+空行+摘要。"""

        try:
            response = self._call_api_with_system(system_prompt, user_prompt)
            raw = response.strip()
            # 移除**加粗**格式
            raw = re.sub(r'\*\*(.*?)\*\*', r'\1', raw)
            
            # 从响应中分离标题和摘要
            category_tag = ""
            summary = raw
            tag_match = re.search(r'【([^】]+)】', raw)
            if tag_match:
                category_tag = f"【{tag_match.group(1)}】"
                # 从raw中移除标题部分，只保留摘要
                summary = raw[tag_match.end():].strip()
            
            # 清理摘要中的换行
            summary = summary.replace('\n', ' ').replace('\r', ' ')
            
            logger.info(f"AI摘要生成: 标题='{title[:30]}...', 摘要长度={len(summary)}, 高标题='{category_tag}'")
            return summary, category_tag

        except Exception as e:
            logger.error(f"AI摘要生成失败: {e}")
            return "摘要生成失败", ""
    
    def _generate分段_summary(self, title: str, content: str, target_length: int = 500) -> tuple:
        """
        对长文章进行分段摘要处理（合并返回摘要+高标题）
        
        Args:
            title: 文章标题
            content: 文章内容
            target_length: 目标摘要长度
        
        Returns:
            (摘要文本, 高标题文本) 的元组
        """
        logger.info(f"长文章分段摘要处理: 标题='{title[:30]}...', 内容长度={len(content)}")
        
        # 将文章分成3段
        chunk_size = len(content) // 3
        chunks = [
            content[:chunk_size],
            content[chunk_size:chunk_size*2],
            content[chunk_size*2:]
        ]
        
        # 为每段生成摘要
        chunk_summaries = []
        for i, chunk in enumerate(chunks):
            system_prompt = """你是一个专业的新闻摘要专家。你的任务是从文章的一个段落中提取关键信息。禁止使用"本文通过""文章从""文章指出""文章分析了"等元语言表述，直接陈述事实和观点即可。"""
            
            user_prompt = f"""请阅读以下文章段落，提取该段落的核心信息和关键要点。

【要求】
- 只提取该段落中的事实、数据、观点
- 不要添加你自己的理解或外部知识
- 输出格式：用简洁的语言总结该段落的主要内容（50-100字）

文章标题：{title}
段落{i+1}：
{chunk}"""
            
            try:
                response = self._call_api_with_system(system_prompt, user_prompt)
                chunk_summaries.append(response.strip())
            except Exception as e:
                logger.warning(f"分段摘要失败: {e}")
                chunk_summaries.append("")
        
        # 合并所有段落的摘要，再生成最终摘要
        combined = "\n\n".join(chunk_summaries)
        
        system_prompt = """你是一个专业的新闻摘要专家，擅长总结文章核心内容并生成高质量标题和摘要。

【核心原则】严格忠于原文，只总结文章中实际包含的信息，不要生成、推理或补充文章中没有的内容。

【禁止使用的废话表述】
- "原文未进一步说明""后续发展趋势尚不明朗""具体情况有待观察"
- 任何包含"未进一步""有待""尚不""尚未"的模糊敷衍表述

【特别禁止】
- 禁止人物百科式背景信息
- 禁止出现作者信息
"""

        user_prompt = f"""请根据以下文章各段落的摘要，生成一篇完整、精炼的最终摘要。

文章标题：{title}

各段落摘要：
{combined}

【输出格式要求】（严格遵守）：
第1行：基于正文核心内容重新生成的简洁新闻标题，格式为【具体标题内容】
- **【绝对禁止】直接使用原文标题、原文标题的任何部分或原文标题的截取**。必须完全基于文章正文内容提炼标题
- 标题聚焦最重要的事实或观点，长度15-50字
- **长标题必须用逗号切分**：当标题超过20字且包含两个及以上独立意群/分句时，用逗号分隔各意群，提高可读性。如"罗志恒建议开征超额利润调节税应对AI时代收入分配失衡"→"罗志恒建议开征超额利润调节税，应对AI时代收入分配失衡"

第2行：空行

第3行起：极简摘要，用 4-6 句话概括，总字数严格不超过 100 字
- 用 4 到 6 个短句，覆盖各段落最核心的事实与结论，其余细节舍弃
- 摘要第一句话直接讲正文核心事实，绝对不能照搬原文标题
- 总字数必须控制在 100 字以内（含标点），宁可少写也不要超
- 绝对不要出现发布元信息或"原文未进一步说明"等表述

直接输出标题+空行+摘要，不要有任何解释说明。"""
        
        try:
            response = self._call_api_with_system(system_prompt, user_prompt)
            raw = response.strip()
            raw = re.sub(r'\*\*(.*?)\*\*', r'\1', raw)
            
            # 从响应中分离标题和摘要
            category_tag = ""
            summary = raw
            tag_match = re.search(r'【([^】]+)】', raw)
            if tag_match:
                category_tag = f"【{tag_match.group(1)}】"
                summary = raw[tag_match.end():].strip()
            
            summary = summary.replace('\n', ' ').replace('\r', ' ')
            
            logger.info(f"分段摘要生成完成: 标题='{title[:30]}...', 摘要长度={len(summary)}, 高标题='{category_tag}'")
            return summary, category_tag
        except Exception as e:
            logger.error(f"分段摘要生成失败: {e}")
            return "摘要生成失败", ""

    def generate_summary_with_retry(self, title: str, content: str, max_retries: int = 0) -> tuple:
        """
        使用AI生成文章摘要和高标题（合并原摘要+标题优化为一次调用）

        Args:
            title: 文章标题
            content: 文章内容
            max_retries: 保留参数，不再使用

        Returns:
            (摘要文本, 高标题文本) 的元组
        """
        if not content:
            return "无内容", ""

        # 直接生成摘要+高标题
        summary, category_tag = self.generate_summary(title, content)
        
        # 【新增】检查摘要字数，如果超过500字，重新生成精简版本
        summary, category_tag = self._condense_summary_if_too_long(title, content, summary, category_tag)
        
        return summary, category_tag
    
    def _condense_summary_if_too_long(self, title: str, content: str, summary: str, category_tag: str = "") -> tuple:
        """
        检查摘要字数，如果超过100字则重新生成精简版本（4-6句、≤100字）

        Args:
            title: 文章标题
            content: 文章内容
            summary: 原始摘要（不含标题）
            category_tag: 高标题
            
        Returns:
            (字数在100字以内的摘要, 高标题) 的元组
        """
        MAX_SUMMARY_LENGTH = 100
        
        current_length = len(summary)
        
        if current_length <= MAX_SUMMARY_LENGTH:
            logger.info(f"摘要字数检查: 标题='{title[:30]}...', 字数={current_length}，无需精简")
            return summary, category_tag
        
        # 先尝试最多2次AI精简
        for attempt in range(2):
            logger.info(f"摘要字数超限: 标题='{title[:30]}...', 当前字数={current_length}，第{attempt+1}次AI精简...")
            condensed, condensed_tag = self._generate_condensed_summary(title, content if content else summary, MAX_SUMMARY_LENGTH, category_tag)
            
            if len(condensed) <= MAX_SUMMARY_LENGTH:
                logger.info(f"摘要精简成功: 字数={len(condensed)}")
                return condensed, condensed_tag
            
            # 如果还是超长，继续尝试
            current_length = len(condensed)
            category_tag = condensed_tag
            summary = condensed
        
        # AI精简2次后仍然超长，执行硬截断
        logger.warning(f"摘要AI精简2次后仍超限({len(summary)}字)，执行硬截断至{MAX_SUMMARY_LENGTH}字")
        truncated = summary[:MAX_SUMMARY_LENGTH]
        last_punct = max(truncated.rfind('。'), truncated.rfind('！'), truncated.rfind('？'), truncated.rfind('；'))
        if last_punct > MAX_SUMMARY_LENGTH * 0.7:
            truncated = truncated[:last_punct+1]
        return truncated, category_tag
    
    def _generate_condensed_summary(self, title: str, content: str, max_length: int = 100, category_tag: str = "") -> tuple:
        """
        生成精简版摘要（4-6句、≤100字）
        
        Args:
            title: 文章标题
            content: 文章内容
            max_length: 最大字数
            category_tag: 原高标题
            
        Returns:
            (精简后的摘要, 高标题) 的元组
        """
        system_prompt = """你是一个专业的新闻摘要专家，擅长将长篇内容精简为极简、信息密度极高的摘要。"""

        user_prompt = f"""请将以下文章的摘要精简到 100 字以内，用 4-6 句短句表达。

【极其重要】你必须大幅精简：
- 用 4 到 6 个短句，只保留最核心的事实、数据和结论
- 去除一切重复表达、冗余信息和铺垫
- 总字数严格不超过 100 字（含标点），宁可少写也不要超
- 语言精炼，信息密度要高

文章标题：{title}
原始摘要：
{content[:5000]}

【输出格式要求】
第1行：保持或优化原标题，格式为【标题内容】
第2行：空行
第3行起：100字以内的极简摘要（4-6句）

直接输出，不要有任何解释说明。"""

        try:
            response = self._call_api_with_system(system_prompt, user_prompt)
            raw = response.strip()
            raw = raw.replace('\r', '')
            raw = re.sub(r'\*\*(.*?)\*\*', r'\1', raw)
            
            # 分离标题和摘要
            new_tag = category_tag
            condensed = raw
            tag_match = re.search(r'【([^】]+)】', raw)
            if tag_match:
                new_tag = f"【{tag_match.group(1)}】"
                condensed = raw[tag_match.end():].strip()
            
            condensed = condensed.replace('\n', ' ')
            
            logger.info(f"精简摘要生成完成: 标题='{title[:30]}...', 字数={len(condensed)}")
            return condensed, new_tag
        except Exception as e:
            logger.error(f"精简摘要生成失败: {e}，返回原始摘要")
            return content[:max_length] if len(content) > max_length else content, category_tag

    def classify_article(self, title: str, summary: str) -> str:
        """
        使用AI判断文章的MECE分类编号

        Args:
            title: 文章标题
            summary: 文章摘要

        Returns:
            MECE分类编号（如"1.1"、"2.3"等）
        """
        content_preview = summary[:1000] if summary else ""

        prompt = f"""请根据以下文章内容，判断其最合适的MECE分类编号。

文章标题：{title}
文章摘要：{content_preview}

MECE分类体系（11个大类，每个大类下有子分类）：
1. 国际局势与地缘政治
   1.1 地区冲突与战争
   1.2 国际关系与外交
   1.3 全球安全与反恐
2. 宏观经济与金融
   2.1 国内宏观经济
   2.2 宏观消费与零售
   2.3 资本市场
   2.4 房地产市场
   2.5 全球金融
3. 文体娱乐内容
   3.1 文化产业
   3.2 体育休闲
   3.3 体验消费
   3.4 网络与数字文化
4. 科技产业与创新
   4.1 人工智能
   4.2 信息技术
   4.3 智能制造与机器人
   4.4 新能源与绿色科技
5. 医疗健康与生命科学
   5.1 医疗改革与政策
   5.2 医学研究与突破
   5.3 公共卫生
6. 教育发展与人才培养
   6.1 教育政策与改革
   6.2 高等教育
   6.3 教育科技
   6.4 就业与人才
7. 社会民生与消费
   7.1 民生消费
   7.2 就业与职场
   7.3 人口与家庭
   7.4 社会治理
8. 企业与商业
   8.1 企业经营
   8.2 商业动态
   8.3 电商与新零售
   8.4 创业与创新
9. 政策法规与监管
   9.1 国家政策
   9.2 行业监管
   9.3 地方治理
   9.4 反腐与廉政
10. 能源与资源
    10.1 传统能源
    10.2 新能源
    10.3 资源与环境
11. 社会热点与舆论动态
    11.1 热点事件
    11.2 舆情分析
    11.3 跨界热点

重要判断规则：

【社会热点判断 - 11类】
以下情况优先归入【社会热点与舆论动态】（11类）：
- 涉及公众人物（如企业家、明星、网红等）违法、丑闻、争议事件（**不涉及AI的**）
- **不涉及AI技术的**社会伦理争议、突发事件、争议事件
- 涉及社会舆论广泛关注的突发事件、争议事件
- 涉及道德伦理讨论、公共道德争议
- 涉及名人丑闻、舆论风波、网络争议
- 涉及社会现象调查、灰色产业链曝光
- **涉及产品质量问题、虚假宣传、消费者权益争议（如：某饮料被指糖水、某产品成分造假）优先归入11.1热点事件**
- **涉及政府项目造假、工程质量问题、资金挪用等公共资源滥用丑闻，优先归入11.1热点事件，而非9.3地方治理**
- **涉及社会不公平现象、就业歧视、招聘歧视、职场偏见等公众关注的社会议题，归入11.1热点事件**
- **涉及动物保护、珍稀动物死亡/生病、动物园事件等（如大熊猫离世），优先归入11.1热点事件，而非5类医疗健康（医疗健康专指人类健康）**
- **涉及日常生活中的科技/物理现象引发公众关注和讨论的（如台灯导致WiFi网速骤降），归入11.1热点事件**
- **涉及消费者权益争议、产品安全质疑等社会热点话题的，归入11.1热点事件**

【国际局势判断 - 1类】（最高优先级之一）
以下情况优先归入【国际局势与地缘政治】（1类）：
- **涉及国际冲突、战争、地缘政治危机（如：美伊冲突、地区战争）优先归入1.1地区冲突与战争**
- **涉及国际和平协议、停战协议、谅解备忘录、外交谈判、国家间签署的协议（如：美伊签署停战谅解备忘录、美伊和平协议达成、霍尔木兹海峡恢复通行）优先归入1.1或1.2，绝对不是3类文体娱乐或4类科技产业**
- 涉及国际关系变化、外交事件、国家间博弈
- 涉及全球能源安全、能源危机与国际政治关联
- 涉及国际制裁、贸易争端背后的地缘政治因素

【政策法规判断 - 9类】
以下情况归入【政策法规与监管】（9类）：
- 重点在于解读国家政策本身（如：某政策的内容、意义、影响）
- 重点在于监管动作本身（如：某行业的监管新规、整治行动）
- 重点在于立法进程、执法过程
- 涉及司法程序但重点是政策解读或监管意义

【企业/商业判断 - 8类】
- 重点在于企业经营状况、财务数据、商业动态
- 涉及企业战略、市场竞争、商业模式
- **涉及企业/云厂商资本开支（如：四大云厂资本开支突破7200亿美元）应归入8类企业与商业**
- **涉及茅台等传统消费企业股价表现/估值分析的文章，优先归入8.2商业动态**
- **涉及谷歌、亚马逊、微软、Meta等科技巨头财报、资本开支、企业经营数据的，归入8.1企业经营或8.2商业动态**
- **涉及具体产品成分标注、食品安全合规问题，但文章重点在企业回应/监管介入的，归入9.2行业监管**
- **涉及企业家/创始人的个人重大事件（如自杀、被抓、离职等），应归入8类企业与商业而非2类经济金融**
- **涉及企业财报、季度业绩、收入结构变化等企业经营数据的文章（即使是AI公司如百度Q1财报），应归入8.1企业经营**
- **涉及企业倒闭、破产、被接管等商业事件的，应归入8.2商业动态**
- **涉及某企业营收/利润暴增并引申讨论城市经济对比的文章，核心仍是企业业绩，应归入8.1企业经营而非2类宏观经济**
- **涉及企业高管人事变动、晋升路径分析、管理层结构研究的文章（如标普500高管晋升路径、CEO任期分析等），归入8.1企业经营，而非6类教育发展与人才培养**
- **涉及企业安全管理、安全生产事故造成人员伤亡的（如工厂事故致人死亡），归入11.1热点事件（社会热点），而非8类企业与商业**
- **【重要】涉及企业IPO、上市、招股等资本运作事件，必须归入8类企业与商业（8.1企业经营或8.2商业动态）。SpaceX上市、SK海力士IPO等属于企业经营/商业动态，绝不是文体娱乐或科技产业**

【科技产业判断 - 4类】
- **AI相关内容（无论是技术进展、应用、争议、伦理讨论）统一归入4.1人工智能，归入科技产业动态与创新类别**
- **【关键例外】如果文章核心主题是短剧/微短剧/小说/游戏行业（如"AI脸引发厌恶，微短剧行业应转型"），即使提及AI技术，也应归入3类文体娱乐，而非4类科技产业。判断标准：文章是在讨论某个文娱行业的现状/趋势/问题，AI只是其中一个技术要素**
- 涉及AI技术本身的发展、创新、产业趋势
- 涉及AI应用（如：AI数字分身、AI名人模仿、AI职场应用、AI评估、AI裁员）
- 涉及AI争议、伦理讨论（如：AI复活、数字来生、AI侵权、AI水货等）
- 涉及AI技术被滥用、违法使用
- 涉及技术创新、研发突破、产品发布
- 涉及AI产品在市场中的表现、用户体验

【文化娱乐判断 - 3类】（短剧/小说/游戏/影视 最高优先级）
- **【最高优先级】涉及短剧/微短剧/网络剧的所有内容（播放量、制作争议、行业讨论、AI技术应用等），统一归入3.1文化产业。即使文章提及AI技术（如"AI脸"、"AI换脸"、"AI制作"），只要核心主题是短剧行业本身，就归入3类而非4类科技**
- **【最高优先级】涉及小说/网络文学的所有内容（行业动态、创作趋势、IP改编、AI写作等），统一归入3.1文化产业。即使提及AI写作/生成技术，只要核心是小说/网文行业，就归入3类**
- **【最高优先级】涉及游戏行业的所有内容（产业动态、游戏政策、游戏技术、AI在游戏中的应用等），统一归入3.1文化产业。即使提及AI技术，只要核心是游戏行业，就归入3类**
- **【最高优先级】涉及影视行业/影视基地/影视产业的所有内容（如影视基地裁员、影视产业AI冲击、影视行业转型、影视制作技术变革等），统一归入3.1文化产业。即使文章提及AI技术作为裁员/变革原因，只要核心是影视行业本身的变化，就归入3类而非4类科技产业。判断标准：文章讨论的是影视行业现状/趋势/问题，AI只是其中一个技术要素**
- **涉及游戏版权纠纷、游戏私服关停（如：暴雪胜诉关停魔兽私服），归入3.1文化产业**
- **涉及游戏IP版权和解/纠纷/诉讼（如：娱美德与恺英网络传奇IP和解、游戏版权费），归入3.1文化产业，而非8类企业商业**
- **涉及影视/游戏IP相关的版权、知识产权纠纷、和解，归入3.1文化产业**
- **涉及世界杯、奥运会、NBA等重大体育赛事转播权、转播费、版权谈判的，归入3.2体育休闲**
- **涉及央视拒购FIFA世界杯转播权、体育版权采购的，归入3.2体育休闲**
- 涉及电影票房、电视综艺、音乐娱乐
- 涉及文化产业发展、游戏产业动态
- **涉及演员/明星的电影/电视剧相关事件（如演员屏摄争议、电影票房等），归入3.1文化产业**
- **涉及影视作品评价、影视行业争议，归入3.1文化产业**
- **涉及娱乐产业（如演唱会、综艺节目、影视作品）相关新闻，归入3.1文化产业**
- **涉及网络热门玩具、潮流消费品的走红与争议（如"娜塔莎"丑萌解压玩具、盲盒等），归入3.4网络与数字文化**
- **涉及网络流行文化、网络热梗、网红现象等，归入3.4网络与数字文化**
- **【重要】地方性节庆/比赛（如西瓜节、擂台赛、美食节、花展等）不属于文体娱乐，应归入11.1社会热点或7类社会民生**

【教育类判断 - 6类】
- 重点在于教育改革政策、高校发展动态
- 涉及教育体制、教育政策、高考改革
- **涉及高校排名发布（如：软科中国大学排名），归入6.2高等教育**

【社会民生判断 - 7类】
- **涉及交通运输服务便民措施（如高铁推出自行车携带服务、地铁新线路开通），归入7.1民生消费**
- **涉及公共服务新举措、便民政策、消费体验改善等，归入7.1民生消费**
- 涉及就业、职场、人口、社会治理等社会民生议题
- **7类社会民生的核心特征是"政策/服务/民生福利"类内容，不是热点事件和舆情**
- **涉及租房/住房保障政策（如毕业生专项租赁房源、公租房配租、保障性租赁住房），归入7.1民生消费，而非8类企业商业**
- **涉及住房租赁市场政策/补贴/房源供给（如北京推出3500套毕业生专项房源），归入7.1民生消费**
- **涉及便民租房指南、租赁优惠政策的，归入7.1民生消费**
- **涉及交通基础设施规划/建设（如新建高铁线路、第二高铁、城际铁路规划、跨城地铁等），归入7.1民生消费，而非2类宏观经济与金融**
- **涉及城市交通规划、城市群交通网络优化等便民基建，归入7.1民生消费**
- **【重要】高温津贴/高温补贴/防暑降温费等劳动者福利补贴，归入7.1民生消费，而非9类政策法规。这类内容本质是劳动者权益保障和民生福利，不是国家级政策法规本身**
- **【重要】涉及劳动者权益保障、工资福利、社保缴费、公积金等民生福利性质的制度安排，归入7类社会民生，而非9类政策法规**

判断逻辑：
- **【最高优先级】如果文章涉及国际和平协议、停战协议、谅解备忘录、国家间签署的协议（如美伊停战谅解备忘录、美伊和平协议达成），必须归入1类国际局势（1.1地区冲突与战争或1.2国际关系与外交），绝对不是3类文体娱乐或4类科技产业**
- **【最高优先级】如果文章核心主题是短剧/微短剧/小说/游戏/影视行业（讨论行业现状、趋势、问题、争议等），即使提及AI技术，也统一归入3类文体娱乐（3.1文化产业），而非4类科技产业**
- **【最高优先级】如果文章核心主题是影视行业/影视基地/影视产业（如影视基地裁员、影视产业转型、影视行业AI冲击等），即使提及AI技术作为原因，也应归入3类文体娱乐（3.1文化产业），而非4类科技产业**
- **如果文章涉及AI相关内容（无论技术、应用还是争议伦理），统一归入4.1科技产业动态与创新**，而非11类社会热点（但短剧/小说/游戏行业文章除外，见上一条）
- 如果一篇文章同时涉及"人物+丑闻/争议"，优先归入"11.1 热点事件"（但涉及AI的除外）
- 如果一篇文章重点在"法院审理/司法程序"，但核心是社会舆论关注点，归入"11.1"
- **如果文章涉及国际冲突、战争、地缘政治危机（如美伊冲突），优先归入1.1地区冲突与战争**
- **如果文章涉及产品质量/虚假宣传争议、消费者权益，归入11.1热点事件**
- **如果文章涉及政府项目造假、资金滥用等公共资源丑闻，归入11.1热点事件**
- **如果文章涉及游戏版权/私服/娱乐产业纠纷，归入3.1文化产业**
- **如果文章涉及政治人物的金融/证券交易行为（如总统炒股、官员内幕交易），归入2.3资本市场或2.5全球金融，而非11类社会热点。核心是金融/证券市场行为，不是社会舆情事件**
- **如果文章涉及政治人物的商业/经济行为（如总统家族商业交易、官员财产申报），归入2类宏观经济与金融，而非11类社会热点**
- 如果文章主要是"政策解读/监管分析"，归入9类
- **交叉主题涉及AI的，优先归入4类（科技产业），而不是11类（社会热点）；但如果文章核心是短剧/小说/游戏行业，则优先归入3类（文体娱乐）**
- **如果文章重点是企业财报/经营数据/企业家事件，归入8类（企业与商业），而非2类（宏观经济）或4类（科技产业）**
- **【最高优先级】如果文章核心是企业IPO/上市/招股等资本运作事件（如SpaceX纳斯达克上市、SK海力士IPO），必须归入8类（企业与商业），而非3类（文体娱乐）或4类（科技产业）**
- **如果文章涉及交通便民服务、公共服务新举措，归入7类（社会民生），而非3类（文化娱乐）**
- **如果文章涉及交通基础设施规划/建设（如新建高铁线路、城际铁路），归入7类社会民生，而非2类宏观经济**
- **如果文章涉及高温津贴/高温补贴/防暑降温费等劳动者福利补贴，归入7.1民生消费（社会民生），而非9类政策法规。这是劳动者权益保障，属于民生福利范畴**
- **如果文章涉及企业高管晋升路径/管理层结构研究，归入8类企业与商业，而非6类教育发展**
- **如果文章涉及企业安全生产事故致人伤亡，归入11类社会热点，而非8类企业商业**
- **如果文章涉及日常科技/物理现象引发社会关注（非AI技术本身），归入11类（社会热点），而非3类（文化娱乐）或4类（科技产业）**
- **如果文章涉及网络流行消费品/玩具走红与争议，归入3类（文化娱乐），而非11类（社会热点）**
- **【重要】地方性节庆/赛事（如西瓜节擂台赛、美食节、花展等）应归入11.1社会热点或7类社会民生，而非3类文体娱乐**
- **【重要】陪伴经济/情绪消费类（如付费陪爬、陪跑、陪吃、陪游、代排队等"陪伴服务"和"情绪价值消费"）归3.3体验消费，而非7类社会民生或8类企业商业**
- **【重要】执法冲突/暴力执法/城管商贩冲突等归11.1热点事件（非7.4社会治理），这类是社会热点舆情而非民生政策**
- **【重要】医生/护士等医疗行业职业困境（如疲劳行医、超负荷工作等），重点在体制/制度问题则归5.1医疗改革与政策；只是职业日常吐槽归11.1热点事件（非5.2/5.3）**
- **【重要】社会热点事件 vs 社会民生的区分**：
  - 社会热点（11.1）= 引发舆论关注的**突发事件、争议事件、社会现象、社会舆情**（如：银行柜员遭遇奇葩存款、社会奇闻、职场歧视争议、社会不平等等）
  - 社会民生（7类）= **政策/服务/便民措施/消费体验/民生福利**（如：高铁新服务、医保政策、便民举措）
  - **判断标准**：文章是"引发关注的事件/现象/争议"→ 11.1热点事件；文章是"民生政策/服务/措施"→ 7类社会民生
  - **社会舆情类、奇闻轶事类、职业日常困境类（如银行柜员遭遇奇葩存款），归入11.1热点事件，不要归入7类社会民生**
  - **银行/金融行业基层员工的日常遭遇、工作困境等社会话题，归入11.1热点事件，不要归入7类社会民生或2类金融**

请严格按照以下JSON格式回复（只回复JSON，不要有其他内容）：
{{"category": "分类编号", "reason": "简要判断理由"}}

示例回复：
{{"category": "11.1", "reason": "涉及企业家许家印当庭认罪的社会热点事件"}}
{{"category": "4.1", "reason": "涉及AI复活/数字分身引发的科技伦理讨论，归入科技产业"}}
{{"category": "4.1", "reason": "涉及AI名人模仿/AI水货，归入科技产业动态与创新"}}
{{"category": "9.4", "reason": "文章重点在于反腐司法程序和政策意义"}}
{{"category": "4.1", "reason": "文章主要讨论AI大模型技术发展"}}
{{"category": "11.1", "reason": "银行柜员遭遇奇葩存款的社会话题，属于社会热点舆情，不是社会民生"}}
{{"category": "7.1", "reason": "高铁推出便民服务措施，属于民生政策福利，归入社会民生"}}
{{"category": "7.1", "reason": "新建高铁线路/城际铁路规划属于交通便民基建，归入社会民生，而非宏观经济"}}
{{"category": "8.1", "reason": "企业高管晋升路径分析属于企业经营研究，归入企业与商业，而非教育发展"}}
{{"category": "11.1", "reason": "企业安全事故致人员伤亡，属于社会热点舆情，归入社会热点而非企业商业"}}
{{"category": "11.1", "reason": "社会奇闻/职业困境引发舆论关注，归入热点事件而非社会民生"}}
{{"category": "7.1", "reason": "高温津贴/高温补贴属于劳动者权益保障和民生福利，归入社会民生而非政策法规"}}
{{"category": "3.1", "reason": "涉及微短剧行业讨论，AI脸只是技术要素，核心是短剧行业转型，归入文化产业而非科技产业"}}
{{"category": "3.1", "reason": "涉及游戏行业AI技术应用，核心是游戏产业发展，归入文化产业而非科技产业"}}
{{"category": "3.1", "reason": "涉及网络小说AI写作趋势，核心是网文行业动态，归入文化产业而非科技产业"}}
{{"category": "1.1", "reason": "涉及美伊签署停战谅解备忘录，属于国际冲突与外交事件，归入地区冲突与战争，绝非文体娱乐"}}
{{"category": "1.2", "reason": "涉及美伊和平协议达成、霍尔木兹海峡恢复通行，属于国际外交事件，归入国际关系与外交，绝非文体娱乐"}}
{{"category": "3.1", "reason": "涉及影视基地裁员/AI冲击影视行业，核心是影视产业变化，AI只是影响因素，归入文化产业而非科技产业"}}
"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            category = result.get("category", "")
            reason = result.get("reason", "")

            # 验证分类编号是否合法
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
                logger.info(f"AI分类判断: '{title[:30]}...' -> {category} ({reason})")
                return category
            else:
                logger.warning(f"AI分类无效: '{title[:30]}...' -> {category}，默认归入11.3")
                return "11.3"  # 默认归入跨界热点

        except Exception as e:
            logger.error(f"AI分类判断失败: {e}")
            return "11.3"  # 出错时默认归入跨界热点

    def _call_api(self, prompt: str) -> str:
        """
        调用DeepSeek API

        Args:
            prompt: 提示词

        Returns:
            AI响应内容
        """
        return self._call_api_with_system("你是一个专业的内容分析师，擅长判断广告性质和生成文章摘要。", prompt)

    def _call_api_with_system(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用 DeepSeek API（支持自定义 system prompt）

        改造要点：
          1. 单次请求超时从 30s 提升到 API_TIMEOUT_SECONDS（默认 90s），避开慢响应直接判死
          2. 对超时/连接错误/5xx/429 做指数退避重试（1s -> 2s -> 4s -> 8s ...，带随机抖动）
          3. 通过进程级 Semaphore 限制并发，最多同时 API_MAX_CONCURRENCY 个请求在飞
             —— 即使上层改成线程池并发，也不会一次性把连接打爆
          4. 4xx（除 429）为业务错误，不重试直接抛出

        Args:
            system_prompt: 系统提示词
            user_prompt: 用户提示词

        Returns:
            AI 响应内容
        """
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

        # 全局并发闸，保证同一时刻最多 API_MAX_CONCURRENCY 个请求
        with _API_SEMAPHORE:
            for attempt in range(API_MAX_RETRIES + 1):
                try:
                    response = requests.post(
                        self.api_base,
                        headers=headers,
                        json=data,
                        timeout=API_TIMEOUT_SECONDS,
                    )

                    # 429 / 5xx 可重试；其他 4xx 直接抛业务错
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
                    # 指数退避 + 抖动，避免所有失败请求同时重试撞墙
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
                    # 非网络类异常（如 JSON 解析失败、KeyError）不做重试
                    last_exc = e
                    break

        # 所有重试用尽，抛出最后一次异常给上层记录
        assert last_exc is not None
        raise last_exc

    def compare_articles(self, article1: dict, article2: dict) -> int:
        """
        比较两篇文章，判断哪个内容更好

        Args:
            article1: 包含title, content, source_name的字典
            article2: 包含title, content, source_name的字典

        Returns:
            1: 第一篇更好
            -1: 第二篇更好
            0: 两篇差不多
        """
        content1 = article1.get('content', '')[:3000] if article1.get('content') else ""
        content2 = article2.get('content', '')[:3000] if article2.get('content') else ""
        title1 = article1.get('title', '')
        title2 = article2.get('title', '')
        source1 = article1.get('source_name', '')
        source2 = article2.get('source_name', '')

        prompt = f"""请比较以下两篇文章，判断哪个内容更好、信息更完整、分析更深入。

文章1:
标题：{title1}
来源：{source1}
内容：{content1}

文章2:
标题：{title2}
来源：{source2}
内容：{content2}

请严格按照以下格式回复（只回复JSON）：
{{"better": 1或-1或0, "reason": "简短的原因说明"}}

如果文章1更好，返回better: 1
如果文章2更好，返回better: -1
如果两篇差不多，返回better: 0

只回复JSON，不要有其他内容。"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            better = result.get("better", 0)
            reason = result.get("reason", "")
            logger.info(f"文章对比: '{title1[:15]}...' vs '{title2[:15]}...' -> {'第一篇' if better == 1 else '第二篇' if better == -1 else '差不多'}({reason})")
            return better

        except Exception as e:
            logger.error(f"文章对比失败: {e}")
            return 0  # 出错时默认保留两篇

    def is_same_event(self, article1: dict, article2: dict) -> bool:
        """
        判断两篇文章是否在讲同一事件（基于标题+AI摘要）

        Args:
            article1: 包含title, ai_summary, source_name的字典
            article2: 包含title, ai_summary, source_name的字典

        Returns:
            True: 是同一事件
            False: 不是同一事件
        """
        title1 = article1.get('title', '')
        title2 = article2.get('title', '')
        summary1 = article1.get('ai_summary', '')
        summary2 = article2.get('ai_summary', '')
        source1 = article1.get('source_name', '')
        source2 = article2.get('source_name', '')

        # 提取人名/专有名词用于快速匹配
        names1 = set(re.findall(r'[\u4e00-\u9fa5]{2,4}(?=\s*(霸凌|事件|传闻|争议|回应|澄清|调查|热搜|舆情))', title1 + summary1))
        names2 = set(re.findall(r'[\u4e00-\u9fa5]{2,4}(?=\s*(霸凌|事件|传闻|争议|回应|澄清|调查|热搜|舆情))', title2 + summary2))
        
        # 如果发现两篇文章都在讨论同一个人（相同的人名），认为是同一事件
        if names1 and names2 and names1 == names2:
            logger.info(f"事件判断（人名快速匹配）: '{title1[:15]}...' vs '{title2[:15]}...' -> 同一人物事件")
            return True

        # 【新增】重大外交/政治事件快速匹配：同一人物+同一外交动作 → 同一事件
        # 注意：实际文本中人物和外交动作之间可能有其他词（如"普京对中国进行国事访问"）
        # 【修复】仅共享政治人物名不够，必须两篇文章的核心事件都直接围绕该人物的外交动作，
        # 而非仅仅在文中提及该人物。例如：一篇讲"普京访华"，另一篇讲"日韩首脑联系特朗普"
        # 虽然两篇都提到"特朗普"，但核心事件完全不同，不应判为同一事件。
        diplomatic_actions = ['访华', '访美', '访日', '访韩', '访俄', '访欧', '出访', '到访',
                              '国事访问', '正式访问', '抵达北京']
        # 提取文本中出现的知名政治人物
        political_figures = ['普京', '特朗普', '拜登', '习近平', '马克龙', '朔尔茨', '岸田',
                            '尹锡悦', '莫迪', '苏纳克', '泽连斯基', '内塔尼亚胡', '金正恩',
                            '拉马福萨', '卢拉', '米莱']
        figures1 = {f for f in political_figures if f in (title1 + summary1)}
        figures2 = {f for f in political_figures if f in (title2 + summary2)}
        has_diplomatic1 = any(a in (title1 + summary1) for a in diplomatic_actions)
        has_diplomatic2 = any(a in (title2 + summary2) for a in diplomatic_actions)
        common_figures = figures1 & figures2
        # 两篇都提到了同一政治人物 + 都涉及外交动作
        if common_figures and has_diplomatic1 and has_diplomatic2:
            # 【关键约束】同一政治人物必须同时出现在两篇文章的标题中（而非仅在摘要中提及）
            # 且该人物的外交动作必须是两篇文章标题的核心主题
            title_figures1 = {f for f in political_figures if f in title1}
            title_figures2 = {f for f in political_figures if f in title2}
            title_diplomatic1 = any(a in title1 for a in diplomatic_actions)
            title_diplomatic2 = any(a in title2 for a in diplomatic_actions)
            common_title_figures = title_figures1 & title_figures2
            
            if common_title_figures and title_diplomatic1 and title_diplomatic2:
                logger.info(f"事件判断（外交事件快速匹配）: '{title1[:15]}...' vs '{title2[:15]}...' -> 同一外交事件({common_title_figures})")
                return True
            # 如果不满足标题级约束，继续走AI判断（不再直接返回True）

        # 【新增】重大灾害事件快速匹配：同一地点+同一灾害类型 → 同一事件
        # 注意：实际文本中地点和灾害类型之间可能有其他词（如"广西柳州发生4.5级地震"）
        disaster_types = ['地震', '海啸', '洪灾', '洪涝', '泥石流', '山体滑坡', '龙卷风', '台风', '暴雨', '火灾', '爆炸',
                          '煤矿', '矿难', '瓦斯', '矿井', '坍塌', '塌方', '踩踏', '坠机', '空难', '翻船', '沉船']
        # 提取地点词（省/市/区/县名 + 灾害类型在同一文本中出现）
        disaster_locations1 = set()
        disaster_locations2 = set()
        combined1 = title1 + summary1
        combined2 = title2 + summary2
        for dtype in disaster_types:
            if dtype in combined1:
                # 提取灾害前的地名（最多6个中文字符，允许中间有数字和"发生"等词）
                locs1 = re.findall(r'([\u4e00-\u9fa5]{2,6})(?:.{0,10})' + dtype, combined1)
                disaster_locations1.update(locs1)
            if dtype in combined2:
                locs2 = re.findall(r'([\u4e00-\u9fa5]{2,6})(?:.{0,10})' + dtype, combined2)
                disaster_locations2.update(locs2)
        # 地点匹配：使用子串包含而非精确匹配（"广西"是"广西柳州"的子串）
        if disaster_locations1 and disaster_locations2:
            location_overlap = False
            for loc1 in disaster_locations1:
                for loc2 in disaster_locations2:
                    # 检查是否一方是另一方的子串，或前2-3字相同（同省/市）
                    clean1 = re.sub(r'[发生等级0-9.]', '', loc1)[:4]  # 取前4个有效字
                    clean2 = re.sub(r'[发生等级0-9.]', '', loc2)[:4]
                    if clean1 and clean2 and (clean1 in clean2 or clean2 in clean1 or clean1[:2] == clean2[:2]):
                        location_overlap = True
                        break
                if location_overlap:
                    break
            if location_overlap:
                logger.info(f"事件判断（灾害事件快速匹配）: '{title1[:15]}...' vs '{title2[:15]}...' -> 同一灾害事件({disaster_locations1} & {disaster_locations2})")
                return True

        # 【新增】影视/文化作品名快速匹配：同一作品名+相关事件词 → 同一事件
        # 解决同一电影的多篇报道因TF-IDF相似度不够而未被去重的问题
        movie_names1 = set(re.findall(r'《([\u4e00-\u9fa5A-Za-z0-9·\-]{2,20})》', title1 + summary1))
        movie_names2 = set(re.findall(r'《([\u4e00-\u9fa5A-Za-z0-9·\-]{2,20})》', title2 + summary2))
        movie_event_words = ['票房', '上映', '首映', '口碑', '破亿', '破十亿', '夺冠', '获奖', '下架', '延期',
                             '版权', '和解', '纠纷', '败诉', '胜诉', '侵权', '续集', '翻拍']
        common_movie_names = movie_names1 & movie_names2
        if common_movie_names:
            # 两篇文章都提到了同一影视/文化作品名
            has_movie_event1 = any(w in (title1 + summary1) for w in movie_event_words)
            has_movie_event2 = any(w in (title2 + summary2) for w in movie_event_words)
            if has_movie_event1 and has_movie_event2:
                logger.info(f"事件判断（影视作品快速匹配）: '{title1[:15]}...' vs '{title2[:15]}...' -> 同一影视事件({common_movie_names})")
                return True

        # 【2026-06新增】重大国际事件快速匹配：两篇文章都命中同一重大事件关键词组 → 同一事件
        # 解决"伊朗军事打击"+"霍尔木兹海峡关闭"+"美伊和谈"等不同角度报道被误判为不同事件的问题
        # 这些文章虽然侧重不同（军事/外交/经济），但都围绕同一重大事件
        # 【关键修复】增加锚定关键词约束：要求两篇文章在锚定关键词上有至少1个重叠，
        # 避免仅因共享'战争''制裁'等泛化冲突词而误判不同事件为同一事件
        major_event_groups = [
            {
                'name': '美伊战争/冲突/和谈',
                'keywords': ['美伊', '伊朗', '霍尔木兹', '海峡', '鲁比奥', '停火', '和谈', '特朗普', '核问题', '制裁', '解冻',
                             '美伊战争', '空袭', '轰炸', '美军', '打击伊朗', '伊朗反击', '伊朗导弹', '伊朗报复',
                             '德黑兰', '波斯湾', '伊核', '伊朗核', '军事打击', '军事行动', '战争', '开战',
                             '革命卫队', '石油', '导弹', '约旦', '商船', '谈判', '袭击',
                             '摧毁', '毁灭性', '代价', '重建', '援助', '关闭海峡', '通行',
                             '运出', '港口', '基地', '报复性', '反击', '进攻', '撤军',
                             '以伊', '以色列伊朗', '以军', '空防', '防空', '拦截',
                             # 【修复】补充外交/和平/协议相关关键词
                             '谅解', '备忘录', '和平协议', '浓缩铀', '护航', '稀释', '赔偿', '撤出',
                             '伊美', '草案', '圣城旅', '幽灵', '封锁', '突破封锁', '原油',
                             '和平', '协议', '14点', '最终文本', '航运', '经济议题'],
                'anchor_keywords': ['美伊', '伊朗', '霍尔木兹', '鲁比奥', '德黑兰', '波斯湾', '伊核', '伊朗核',
                                   '打击伊朗', '伊朗反击', '伊朗导弹', '伊朗报复', '革命卫队', '以伊', '以色列伊朗',
                                   # 【修复】补充外交/和平特有锚定词
                                   '谅解', '备忘录', '浓缩铀', '护航', '圣城旅', '和平协议', '伊美'],
                'min_per_article': 2,  # 每篇文章至少命中2个关键词
            },
        ]
        for _meg in major_event_groups:
            _meg_kw = _meg['keywords']
            _meg_min = _meg['min_per_article']
            _meg_anchor = _meg.get('anchor_keywords', None)
            _hits1 = {kw for kw in _meg_kw if kw in (title1 + summary1)}
            _hits2 = {kw for kw in _meg_kw if kw in (title2 + summary2)}
            if len(_hits1) >= _meg_min and len(_hits2) >= _meg_min:
                # 额外验证：至少有1个共同关键词，或者两边都命中了>=3个关键词（确保不是巧合）
                _overlap = _hits1 & _hits2
                # 【关键修复】锚定关键词校验：两篇文章必须在锚定关键词上有至少1个重叠
                _anchor_matched = True
                if _meg_anchor:
                    _anchor_hits1 = {kw for kw in _meg_anchor if kw in (title1 + summary1)}
                    _anchor_hits2 = {kw for kw in _meg_anchor if kw in (title2 + summary2)}
                    _anchor_overlap = _anchor_hits1 & _anchor_hits2
                    if not _anchor_overlap:
                        _anchor_matched = False
                        logger.info(f"事件判断（重大国际事件跳过:{_meg['name']}）: "
                                    f"'{title1[:15]}...' vs '{title2[:15]}...' 关键词命中但无锚定关键词重叠"
                                    f"(anchor_hits1={list(_anchor_hits1)[:3]}, anchor_hits2={list(_anchor_hits2)[:3]})")
                if _anchor_matched and (len(_overlap) >= 1 or (len(_hits1) >= 3 and len(_hits2) >= 3)):
                    logger.info(f"事件判断（重大国际事件快速匹配:{_meg['name']}）: "
                                f"'{title1[:15]}...' vs '{title2[:15]}...' -> 同一重大事件(hits1={list(_hits1)[:4]}, hits2={list(_hits2)[:4]})")
                    return True

        prompt = f"""请判断以下两篇文章是否在讲同一事件或话题。

文章1:
标题：{title1}
来源：{source1}
摘要：{summary1}

文章2:
标题：{title2}
来源：{source2}
摘要：{summary2}

判断标准：
- 两篇文章是否在报道**同一个具体事件**（不是泛化的领域或主题）
- "同一事件"的严格定义：核心新闻事实完全一致——**同一个人+同一件事+同一个动作**
- 正确的同一事件判断：
  - 两篇都在报道"普京访华"的具体行程/成果 → 同一事件
  - 一篇报道"普京将访华"的公告、另一篇报道"普京访华签署协议"的结果 → 同一事件（都是关于普京访华这一具体事件的不同进展）
  - 两篇都在报道"广西柳州地震" → 同一事件（即使关注不同方面如震级、救援、伤亡等）
  - 两篇都在报道"张雪机车WSBK夺冠" → 同一事件
  - 两篇都在报道"DeepSeek回应对话泄露疑虑" → 同一事件
- **错误的同一事件判断（极易犯的错，务必避免）**：
  - 一篇讲"普京访华"、另一篇讲"DeepSeek回应对话泄露" → **不是同一事件**（虽然可能出现在同一篇聚合文章中，但核心事件完全不同：一个是外交政治事件，一个是AI科技事件）
  - 一篇讲"普京访华"、另一篇讲"日韩首脑联系特朗普了解中美会谈" → **不是同一事件**（虽然都涉及外交，但核心事件完全不同：一个是普京访华，一个是日韩外交动态）
  - 一篇讲"特朗普访华"、另一篇讲"阿根廷续签中阿本币互换协议" → **不是同一事件**（虽然都是中国外交相关，但核心事件完全不同）
- **绝对不能因为两篇文章属于同一泛化领域（如"都是外交新闻"、"都是科技新闻"）就认为是同一事件**
- **绝对不能因为两篇文章可能被同一篇聚合快讯同时提及就认为是同一事件**
- **绝对不能仅因为两篇文章的摘要中都提及了某个相同的人名/组织名就认为是同一事件**——必须聚焦到核心新闻事件本身
- 同一具体事件的不同角度报道（公告+结果+后续反应）应判断为同一事件，但前提是核心新闻事实（人物+事件+动作）必须一致
- 同一灾害事件的不同方面报道（震情+救援+伤亡）应判断为同一事件
- 同一矿难/工业事故的不同方面报道（事故经过+伤亡人数+救援进展+安全管理问题+矿工反映）应判断为同一事件
- 同一安全事故的不同角度（如：一篇讲"山西煤矿瓦斯爆炸致82死"、另一篇讲"山西煤矿矿工未佩戴定位卡"、第三篇讲"煤矿安全措施执行漏洞"）都是同一事件的不同方面，应判断为同一事件
- 同一影视作品的不同方面报道（如：一篇讲"某电影票房破10亿"、另一篇讲"该电影引发年轻观众情感共鸣"）应判断为同一事件
- 如果两篇文章的核心事件完全不同，即使提到了相同的人名或领域，必须判断为不是同一事件
- 特别注意：如果两篇文章都在讨论同一个人物（如"全红婵"、"贾浅浅"等），即使报道角度不同（如一篇是传闻本身，一篇是官方回应），也应认为是同一事件
- 如果两篇文章标题中都提到同一个人名，且都在讨论与该人物相关的同一事件，应认为是同一事件

请严格按照以下格式回复（只回复JSON）：
{{"is_same": true或false}}

只回复JSON，不要有其他内容。"""

        try:
            response = self._call_api(prompt)
            result = json.loads(response)
            is_same = result.get("is_same", False)
            logger.info(f"事件判断: '{title1[:15]}...' vs '{title2[:15]}...' -> {'同一事件' if is_same else '不同事件'}")
            return is_same

        except Exception as e:
            logger.error(f"事件判断失败: {e}")
            return False  # 出错时默认认为不是同一事件

    def _extract_keywords(self, text: str) -> set:
        """
        提取文本的关键词（人名、地名、专有名词、重要词组）
        增强对人名和专有名词的提取，提高去重准确性

        Args:
            text: 文本

        Returns:
            关键词集合
        """
        if not text:
            return set()

        keywords = set()

        # 提取英文词
        english_words = re.findall(r'[a-zA-Z]{2,}', text)
        keywords.update([w.lower() for w in english_words])

        # 提取数字
        numbers = re.findall(r'\d+', text)
        keywords.update(numbers)

        # 【增强】提取人名（2-4字的中文人名）
        person_names = re.findall(r'[\u4e00-\u9fa5]{2,4}(?:某|霸凌|传闻|事件|争议|回应|澄清|调查|热搜|舆情|风波|丑闻)', text)
        keywords.update(person_names)
        
        # 提取常见人名模式（如"XX霸凌"中的XX）
        common_name_patterns = re.findall(r'([\u4e00-\u9fa5]{2,4})(?:霸凌传闻?|传闻?|事件|争议|回应|澄清|调查|热搜)', text)
        keywords.update(common_name_patterns)
        
        # 提取被讨论的人物名（常见模式：人名+被/遭/陷）
        victim_patterns = re.findall(r'([\u4e00-\u9fa5]{2,4})(?:遭|被|陷|陷于|陷入)', text)
        keywords.update(victim_patterns)

        # 【新增】提取品牌名/公司名
        brand_patterns = re.findall(r'(?:OPPO|小米|华为|苹果|腾讯|阿里|京东|抖音|美团|滴滴|百度|网易|腾讯|阿里|字节)', text)
        keywords.update(brand_patterns)
        
        # 【新增】提取事件类型关键词
        event_keywords = re.findall(r'(?:翻车|争议|道歉|切割|声明|舆情|危机|公关|回应|下架|问责|降级|双标)', text)
        keywords.update(event_keywords)
        
        # 【新增】提取话题类型关键词
        topic_keywords = re.findall(r'(?:母亲节|文案|品牌|营销|广告|热点|热搜|话题)', text)
        keywords.update(topic_keywords)
        
        # 【新增】提取学校/机构名
        school_patterns = re.findall(r'(?:武汉大学|武大|清华|北大|复旦|上交|浙大|高校|大学|母校|校友)', text)
        keywords.update(school_patterns)
        
        # 【新增】提取两字重要特征词
        feature_words = re.findall(r'(?:老公|文案|母亲|节日|道歉|声明|切割|品牌|文宣|公关)', text)
        keywords.update(feature_words)

        # 清理后的中文文本
        chinese_text = re.sub(r'[^\u4e00-\u9fa5]', '', text)

        # 提取2-3字词组
        for length in [2, 3]:
            for i in range(len(chinese_text) - length + 1):
                word = chinese_text[i:i+length]
                # 过滤停用词
                stop_words = ['的', '是', '在', '了', '和', '与', '或', '也', '都', '很',
                             '一个', '这个', '那个', '什么', '怎么', '如何', '怎样']
                if word not in stop_words and len(set(word)) > 1:
                    keywords.add(word)

        return keywords

    # ==================== Embedding 向量相关方法 ====================
    
    def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        调用DeepSeek Embedding API获取文本向量

        Args:
            text: 输入文本

        Returns:
            向量列表，失败返回None
        """
        # 限制输入长度
        text = text[:2000] if text else ""
        if not text.strip():
            return None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        data = {
            "model": "deepseek-chat",
            "input": text,
        }

        return None  # 直接走TF-IDF方案

    @staticmethod
    def _tokenize_for_tfidf(text: str) -> List[str]:
        """
        对中文文本进行智能分词，用于TF-IDF计算
        
        策略：
        1. 提取英文词和数字+单位
        2. 对中文部分提取2-4字n-gram（不去重，保留所有可能的词组合）
        3. 过滤停用词
        
        不同于中文分词器，这里使用n-gram方式，虽然会产生噪声词，
        但相同的文章会产生相同的n-gram，相似文章会有大量重叠的n-gram，
        TF-IDF的IDF权重会自然降低高频噪声词的重要性。
        """
        if not text:
            return []
        
        # 停用词（2字）
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
        
        # 1. 提取英文词
        eng_words = re.findall(r'[a-zA-Z]{2,}', text)
        words.extend([w.lower() for w in eng_words])
        
        # 2. 提取数字+单位组合
        num_units = re.findall(r'\d+(?:\.\d+)?(?:点|%|亿|万|千|元|美元|块|年|月|日|天|次|人|篇|对|组|岁|名|位|家|所|条|项|期|轮|批|起|宗|份|册|座|辆|架|艘|台|套|件)', text)
        words.extend(num_units)
        
        # 3. 提取纯数字（2位以上）
        numbers = re.findall(r'\d+', text)
        words.extend([n for n in numbers if len(n) >= 2])
        
        # 4. 对中文部分提取n-gram（2字、3字、4字）
        chinese_text = re.sub(r'[^\u4e00-\u9fa5]', '', text)
        
        # 4字n-gram（覆盖4字专有名词）
        for i in range(len(chinese_text) - 3):
            word = chinese_text[i:i+4]
            if len(set(word)) > 1:  # 排除重复字
                words.append(word)
        
        # 3字n-gram
        for i in range(len(chinese_text) - 2):
            word = chinese_text[i:i+3]
            if len(set(word)) > 1:
                words.append(word)
        
        # 2字n-gram（过滤停用词）
        for i in range(len(chinese_text) - 1):
            word = chinese_text[i:i+2]
            if word not in stop_words_2 and len(set(word)) > 1:
                words.append(word)
        
        return words

    @staticmethod
    def compute_tfidf_embeddings(texts: List[str]) -> np.ndarray:
        """
        基于TF-IDF计算文本向量（改进版：智能分词+BM25风格IDF）

        Args:
            texts: 文本列表

        Returns:
            向量矩阵 (n_texts, n_features)
        """
        if not texts:
            return np.array([])

        # 使用智能分词
        tokenized = []
        for text in texts:
            words = DeepSeekClient._tokenize_for_tfidf(text)
            tokenized.append(words)

        # 构建词汇表
        all_words = set()
        for words in tokenized:
            all_words.update(words)

        if not all_words:
            return np.zeros((len(texts), 1))

        vocab = sorted(all_words)
        word_to_idx = {w: i for i, w in enumerate(vocab)}
        n_features = len(vocab)

        # 计算TF-IDF（BM25风格）
        n_docs = len(texts)
        
        # 文档频率
        df = np.zeros(n_features)
        for words in tokenized:
            seen = set()
            for w in words:
                if w in word_to_idx and w not in seen:
                    df[word_to_idx[w]] += 1
                    seen.add(w)

        # BM25风格IDF: log((N - df + 0.5) / (df + 0.5) + 1)
        idf = np.log((n_docs - df + 0.5) / (df + 0.5) + 1)

        # TF-IDF矩阵（使用BM25的TF公式：tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl/avgdl))）
        k1 = 1.5
        b = 0.75
        # 计算平均文档长度
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
                # BM25 TF normalization
                tf_norm = (count * (k1 + 1)) / (count + k1 * (1 - b + b * dl / avgdl))
                tfidf_matrix[i, idx] = tf_norm * idf[idx]

        # L2归一化
        norms = np.linalg.norm(tfidf_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        tfidf_matrix = tfidf_matrix / norms

        return tfidf_matrix

    @staticmethod
    def cosine_similarity_matrix(embeddings: np.ndarray) -> np.ndarray:
        """
        计算余弦相似度矩阵

        Args:
            embeddings: 归一化后的向量矩阵

        Returns:
            相似度矩阵 (n, n)
        """
        if embeddings.size == 0:
            return np.array([])
        # 向量已归一化，余弦相似度 = 点积
        return embeddings @ embeddings.T

    def find_similar_groups_v2(self, articles: List[dict]) -> List[Tuple[int, int, float]]:
        """
        找出所有相似的文章对（使用TF-IDF+余弦相似度）
        替代旧的关键词+Jaccard方法

        Args:
            articles: 文章列表，每个包含title和ai_summary

        Returns:
            相似对列表，每个元素是 (idx1, idx2, similarity)
        """
        if not articles:
            return []

        # 准备文本
        texts = []
        titles = []
        for art in articles:
            combined = f"{art.get('title', '')} {art.get('ai_summary', '')}"
            texts.append(combined)
            titles.append(art.get('title', '')[:50])

        n = len(texts)
        logger.info(f"开始TF-IDF+余弦相似度计算，共{n}篇文章...")

        # 计算TF-IDF向量
        embeddings = self.compute_tfidf_embeddings(texts)
        if embeddings.size == 0:
            logger.warning("TF-IDF向量为空，无法计算相似度")
            return []

        # 计算余弦相似度矩阵
        sim_matrix = self.cosine_similarity_matrix(embeddings)

        # 提取所有相似对（只取上三角）
        high_sim_pairs = []      # >= HIGH_SIM_THRESHOLD
        medium_sim_pairs = []    # >= MEDIUM_SIM_THRESHOLD
        low_sim_pairs = []       # >= LOW_SIM_THRESHOLD

        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim >= HIGH_SIM_THRESHOLD:
                    high_sim_pairs.append((i, j, sim))
                elif sim >= MEDIUM_SIM_THRESHOLD:
                    medium_sim_pairs.append((i, j, sim))
                elif sim >= LOW_SIM_THRESHOLD:
                    low_sim_pairs.append((i, j, sim))

        # 安全打印函数
        def safe_print(text):
            try:
                print(text)
            except UnicodeEncodeError:
                safe_text = text.encode('gbk', errors='replace').decode('gbk')
                print(safe_text)

        # 输出分析结果
        safe_print("\n" + "=" * 120)
        safe_print("TF-IDF 余弦相似度分析结果")
        safe_print("=" * 120)
        safe_print(f"高相似(>={HIGH_SIM_THRESHOLD}): {len(high_sim_pairs)}对 → 直接去重")
        safe_print(f"中相似(>={MEDIUM_SIM_THRESHOLD}): {len(medium_sim_pairs)}对 → LLM判断")
        safe_print(f"低相似(>={LOW_SIM_THRESHOLD}): {len(low_sim_pairs)}对 → 规则+LLM判断")
        safe_print("-" * 120)
        safe_print(f"{'序号':<6}{'文章1':<45}{'文章2':<45}{'相似度':<10}{'级别':<10}")
        safe_print("-" * 120)

        # 按相似度降序显示
        all_significant = sorted(
            high_sim_pairs + medium_sim_pairs + low_sim_pairs,
            key=lambda x: x[2], reverse=True
        )[:50]
        for idx, (i, j, sim) in enumerate(all_significant, 1):
            level = "高" if sim >= HIGH_SIM_THRESHOLD else "中" if sim >= MEDIUM_SIM_THRESHOLD else "低"
            safe_print(f"{idx:<6}{titles[i]:<45}{titles[j]:<45}{sim:<10.4f}{level}")

        safe_print("-" * 120)
        safe_print("=" * 120 + "\n")

        logger.info(f"TF-IDF相似度筛选: 高相似{len(high_sim_pairs)}对, 中相似{len(medium_sim_pairs)}对, 低相似{len(low_sim_pairs)}对")
        
        # 返回所有达到低相似度阈值以上的对
        return high_sim_pairs + medium_sim_pairs + low_sim_pairs

    def _jaccard_similarity(self, set1: set, set2: set) -> float:
        """
        计算Jaccard相似度

        Args:
            set1: 集合1
            set2: 集合2

        Returns:
            Jaccard相似度（0到1之间）
        """
        if not set1 or not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        if union == 0:
            return 0.0

        return intersection / union

    def find_similar_groups(self, articles: List[dict]) -> List[Tuple[int, int]]:
        """
        找出所有相似的文章对（使用关键词+Jaccard相似度）

        Args:
            articles: 文章列表

        Returns:
            相似对列表，每个元素是 (idx1, idx2, similarity)
        """
        if not articles:
            return []

        # 准备文本
        texts = []
        titles = []
        for art in articles:
            combined = f"{art.get('title', '')} {art.get('ai_summary', '')}"
            texts.append(combined)
            titles.append(art.get('title', '')[:50])

        logger.info(f"开始关键词+Jaccard相似度计算，共{len(texts)}篇文章...")

        # 提取所有关键词
        all_keywords = [self._extract_keywords(text) for text in texts]

        similar_pairs = []
        all_pairs = []
        n = len(texts)

        for i in range(n):
            for j in range(i + 1, n):
                similarity = self._jaccard_similarity(all_keywords[i], all_keywords[j])
                all_pairs.append((i, j, similarity))
                if similarity >= SIMILARITY_THRESHOLD:
                    similar_pairs.append((i, j, similarity))

        # 安全打印函数，处理编码问题和缓冲区阻塞
        def safe_print(text):
            try:
                print(text)
            except UnicodeEncodeError:
                try:
                    safe_text = text.encode('gbk', errors='replace').decode('gbk')
                    print(safe_text)
                except (BlockingIOError, OSError):
                    pass
            except (BlockingIOError, OSError):
                # 行缓冲模式下输出量过大时可能触发非阻塞写入失败，静默跳过
                pass

        # 输出所有相似度数据到表格
        safe_print("\n" + "=" * 120)
        safe_print("关键词Jaccard 相似度分析结果")
        safe_print("=" * 120)
        safe_print(f"{'序号':<6}{'文章1':<45}{'文章2':<45}{'相似度':<10}{'状态':<10}")
        safe_print("-" * 120)

        # 按相似度降序排列
        all_pairs_sorted = sorted(all_pairs, key=lambda x: x[2], reverse=True)
        for idx, (i, j, sim) in enumerate(all_pairs_sorted[:50], 1):  # 只显示前50对
            status = "[相似]" if sim >= SIMILARITY_THRESHOLD else "[不相似]"
            safe_print(f"{idx:<6}{titles[i]:<45}{titles[j]:<45}{sim:<10.4f}{status}")

        if len(all_pairs) > 50:
            safe_print(f"... (共{len(all_pairs)}对，仅显示前50对)")

        safe_print("-" * 120)
        safe_print(f"阈值: {SIMILARITY_THRESHOLD}")
        safe_print(f"总对数: {len(all_pairs)}, 相似对数: {len(similar_pairs)}")
        safe_print("=" * 120 + "\n")

        logger.info(f"关键词Jaccard筛选完成: 发现{len(similar_pairs)}对相似文章")
        return similar_pairs

    def generate_daily_summary(self, articles: List[dict]) -> str:
        """
        生成每日资讯的核心一句话导读

        Args:
            articles: 文章列表，包含title和ai_summary

        Returns:
            核心导读一句话（100字以内）
        """
        if not articles:
            return "今日无资讯更新。"

        # 准备文章摘要信息
        articles_info = []
        for i, art in enumerate(articles[:20], 1):  # 最多取20篇
            title = art.get('title', '')
            summary = art.get('ai_summary', '')
            articles_info.append(f"文章{i}：{title}\n摘要：{summary}")

        articles_text = "\n\n".join(articles_info)

        system_prompt = "你是一个专业的新闻编辑，擅长从大量资讯中提炼核心要点。"

        user_prompt = f"""请根据以下{len(articles)}篇文章的标题和摘要，生成今日资讯的核心导读。

文章列表：
{articles_text}

要求：
1. 只输出一句话，格式如下：
   "今日核心议题：①...；②...；③...；④..."
2. 必须严格列出4个核心议题，分别覆盖以下4个领域：
   - ①时政类：当日最重要的国内外政治/外交/宏观经济事件
   - ②AI/科技类：当日最重要的AI、科技产业相关事件
   - ③文化娱乐类：当日最重要的文化、娱乐、体育事件
   - ④社会热点类：当日最重大的社会事件（如重大灾害、重大安全事故等影响最广泛的事件）
3. 每个议题直接用简短词语概括核心事件（如"普京访华深化中俄战略协作"、"SpaceX递交IPO招股书估值2万亿美元"、"世界杯开幕式"等），不要用泛化描述（如"国际关系动态"）
4. **不要加"时政议题"、"AI/科技议题"、"文化娱乐议题"、"社会热点议题"等分类标签**，直接写事件本身
5. 社会热点议题必须选当天最重大、影响最广泛的事件，不能选次要事件
6. 如果某个领域当天确实没有重大事件，写"暂无重大事件"
7. 语言简洁有力，总字数控制在120字以内
8. **不要有后续解释说明，只输出这一句话导读**
9. 不要有任何解释或额外说明

正确示例：
"今日核心议题：①普京访华获高规格接待；②SpaceX递交IPO招股书估值2万亿美元；③拉勾网申请破产；④暂无重大事件"

错误示例（不要加分类标签）：
"今日核心议题：①时政议题普京访华获高规格接待；②AI/科技议题SpaceX递交IPO招股书估值2万亿美元" """

        try:
            response = self._call_api_with_system(system_prompt, user_prompt)
            summary = response.strip()
            logger.info(f"AI总结生成完成，字数: {len(summary)}")
            return summary
        except Exception as e:
            logger.error(f"AI总结生成失败: {e}")
            return "总结生成失败"

    def optimize_title(self, original_title: str, content: str = "", force: bool = False) -> str:
        """
        专门优化文章标题，使其更像新闻标题：简洁、聚焦、有信息量
        
        Args:
            original_title: 原标题
            content: 文章内容（可选，如果有内容会提高优化质量）
            force: 强制根据内容重新生成标题，即使原标题看起来没问题
            
        Returns:
            优化后的标题
        """
        if not original_title.strip() and not content.strip():
            return original_title
        
        # 【修改】检测原标题是否存在必须优化的问题：
        # - 含问号/感叹号（疑问句/感叹句式标题）
        # - 含口语化表达（"啦""就在""别太"等）
        # - 含破折号/省略号结尾（悬念式标题）
        # - 含"|"或"｜"分隔（常是栏目名+标题）
        force_optimize = force  # force=True 时始终重新生成
        force_reason = "强制重新生成" if force else ""
        if not force_optimize:
            if re.search(r'[？?!！]$', original_title.strip()):
                force_optimize = True
                force_reason = "疑问/感叹句式"
            elif re.search(r'(啦|就在|别太|快来|赶紧|速看|必看|震惊|意外)', original_title):
                force_optimize = True
                force_reason = "口语化表达"
            elif re.search(r'[—…]+$', original_title.strip()):
                force_optimize = True
                force_reason = "悬念式结尾"
            elif re.search(r'[｜|]$', original_title.strip()):
                force_optimize = True
                force_reason = "栏目分隔式"
            elif re.search(r'(这届|到底|究竟|凭什么|怎么说|怎么看|惹争议|引热议|炸锅|翻车|破防)', original_title):
                force_optimize = True
                force_reason = "标题党/疑问式"
            elif re.search(r'(谢谢|感谢|对不起|抱歉|别再|千万别)', original_title):
                force_optimize = True
                force_reason = "情感/口语化标题"
            elif re.search(r'(巧妇|无米之炊|怀念|黄蓉|洪七公|三国|西游|水浒|红楼梦|覆水难收|亡羊补牢|画蛇添足|守株待兔|掩耳盗铃|对牛弹琴|井底之蛙|杯弓蛇影|狐假虎威|画饼充饥|叶公好龙|纸上谈兵|打草惊蛇|指鹿为马|坐井观天|刻舟求剑|杞人忧天|买椟还珠|塞翁失马|鹬蚌相争|胸有成竹|破釜沉舟|卧薪尝胆|围魏救赵|草木皆兵|四面楚歌|退避三舍|望梅止渴|完璧归赵|负荆请罪|毛遂自荐|一鸣惊人|老马识途|鹏程万里|愚公移山)', original_title):
                force_optimize = True
                force_reason = "俗语/比喻/典故式标题"
        
        # 【关键修复】始终强制AI根据内容重新生成标题，绝不直接沿用原标题
        # 原因：原标题即使是【】格式也可能是原文标题的截取，必须由AI基于内容重新提炼
        # 即使原标题看起来"没问题"，也要用AI验证它是否真正概括了文章内容
        force_optimize = True
        force_reason = force_reason if force_reason else "强制AI重新生成标题（禁止沿用原文标题）"
        
        # 准备内容预览
        content_preview = content[:2000] if content else "文章详情请查看原文"
        
        system_prompt = "你是一个严谨的新闻标题编辑，你的唯一职责是将标题改写为客观、准确、信息密度高的新闻陈述句标题。"
        
        user_prompt = f"""请优化以下文章标题，使之成为客观、准确、信息密度高的新闻标题。

原标题：{original_title}
文章内容预览：{content_preview}

优秀的标题例子：
1. 【昔日硅谷宠儿Allbirds以2.68亿元被收购，市值大幅缩水】
2. 【北京积分落户竞争降温背后：中年失业潮导致大量资深北漂被迫出局】
3. 【欧盟与美国就坦贝利协议谈判，拟取消工业品关税换取15%关税上限】
4. 【美军称未完全摧毁伊朗军事设施，敌方藏于花岗岩地下工事】

不够好的标题例子：
1. 【AI时代需精打细算使用Token，其本质是信息成本控制的历史延续】（太冗长、不够聚焦）
2. 【婚姻不幸，凑合过呗】（口语化、比喻式标题，完全没有信息量，读者不知道在说什么）
3. 【抱团行情如何收场？】（空洞疑问句，没有具体信息）
4. 【收手吧匡威，外面都在笑你丑】（网络口语/主观评价，不像新闻标题）
5. 【敌在花岗岩】（奇怪表述，读者无法理解，应写明"敌方藏于花岗岩地下工事"）
6. 【怀念黄蓉与洪七公：全球稀土博弈中的中国困境】（"怀念黄蓉与洪七公"是原文比喻，与稀土毫无关联，应删除比喻，直接写【全球稀土博弈中的中国困境：澳大利亚矿企面临出口管制压力】）
7. 【巧妇难为无米之炊】（俗语比喻，读者完全不知道在说什么，必须根据文章内容用事实性语言重写）
8. 【谢谢所有来北京的朋友！】（感叹句，没有信息量，应改为【五月天鸟巢演唱会12场吸引65万人次，掀起"跟着歌手游北京"新风潮】）
9. 【这届老师到底在怕什么？】（疑问句标题党，没有信息量，应改为【上海高校学生情绪失控事件与家长举报零成本问题引发教育生态反思】）

优化要求：
1. 结果必须是【优化后的标题】格式，包含【】符号
2. 标题要：简洁、聚焦、像新闻标题、有信息量
3. 长度控制在15-50字之间
4. 去除学术化、冗长、不够聚焦的表达
5. 直接输出优化后的标题，不要有任何解释说明
6. **禁止使用问号（？/?)结尾的疑问句**，标题必须是陈述句，直接陈述核心事实
7. **禁止使用比喻和修辞手法**（如"冰火两重天""过山车""生死劫""不幸的婚姻""怀念黄蓉""巧妇难为无米之炊"等），用平实语言描述事实
8. **标题必须根据文章内容生成，而非直接沿用原文标题**——原文标题可能完全不反映文章内容（如标题是"为什么今天我们如此怀念黄蓉？"但文章讲的是澳大利亚稀土矿业），此时必须根据文章内容提炼标题，绝不能在标题中保留原文的比喻/俗语
9. 标题必须总结全文主旨，信息量要高，让读者一眼知道文章的核心内容和结论
10. **禁止使用口语化/网络化表达**（如"收手吧""凑合过""太意外了""震惊""别再惦记"等），标题必须正式、客观
11. **禁止使用读者无法理解的奇怪表述**（如"敌在花岗岩""巧妇难为无米之炊"），必须用完整的陈述句写明具体事实
12. **标题必须包含文章的核心事实信息**：涉及什么协议就写协议名，涉及什么事件就写事件名，涉及什么数据就写关键数据，不能用空洞的比喻/俗语代替
13. 如果原文标题用了比喻/口语/俗语/古诗词，必须完全抛弃这些修辞，还原为事实性表述（如"怀念黄蓉"→写明稀土矿业相关事实；如"巧妇难为无米之炊"→根据文章内容提炼核心事实）
14. **禁止使用悬念式标题**：如"全球各地的霸王龙，都来北京啦！就在——"必须改写为具体事实陈述，如"国家自然博物馆举办霸王龙特展，首次在亚洲展出完整霸王龙化石"
15. **禁止保留原文标题中的省略号/破折号/感叹号等悬念元素**，标题必须是完整的事实陈述
16. **标题必须是高度概括性的总结**：如果原文标题只是一个模糊的引子（如"就在——""都来啦""别太满""带了半个内阁""谢谢所有来北京的朋友""这届老师到底在怕什么"），必须根据文章内容提炼出核心事实作为标题
17. **长标题必须用逗号切分**：当标题超过20字且包含两个及以上独立意群/分句时，用逗号分隔各意群，提高可读性。如"罗志恒建议开征超额利润调节税应对AI时代收入分配失衡"→"罗志恒建议开征超额利润调节税，应对AI时代收入分配失衡"。逗号应放在逻辑断点处（主谓之间、因果/目的/转折等关系词之前）

请输出优化后的标题："""

        try:
            response = self._call_api_with_system(system_prompt, user_prompt)
            optimized_title = response.strip()
            
            # 提取标题（确保有【】格式）
            if optimized_title.startswith('【') and '】' in optimized_title:
                # 提取【】内的内容
                title_end = optimized_title.find('】')
                result = '【' + optimized_title[1:title_end+1]
            else:
                # 如果没有【】格式，手动添加
                result = '【' + optimized_title.strip() + '】'
            
            logger.info(f"标题优化完成: '{original_title}' -> '{result}'")
            return result
        except Exception as e:
            logger.error(f"标题优化失败: {e}")
            return original_title

    def batch_optimize_titles(self, articles: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        批量并发优化文章标题（8线程并发）

        Args:
            articles: 文章列表，每个文章包含 'title' 和可选的 'content'

        Returns:
            更新后的文章列表
        """
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
                    results[idx] = original  # 失败时保留原标题

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

        # 用优化后的标题更新articles
        for i, optimized in enumerate(results):
            if optimized is not None:
                articles[i]['title'] = optimized
            # 如果results[i]为None（不应发生），保留原始title

        return articles

    def batch_dedup_review(self, article_groups: List[Tuple[int, List[dict]]]) -> List[Tuple[int, set]]:
        """
        批量对疑似重复的文章组进行LLM判断（8线程并发）

        Args:
            article_groups: 列表，每个元素为 (group_id, articles_info)
                articles_info中每个元素包含title, source, summary

        Returns:
            列表，每个元素为 (group_id, remove_indices_set)
            remove_indices_set为应移除的文章在articles_info中的索引集合
        """
        if not article_groups:
            return []

        results = {}
        lock = threading.Lock()

        def _review_single_group(group_id, articles_info):
            """对单个组进行LLM判断"""
            try:
                keep_idx, remove_set = self._dedup_review_single_group(articles_info)
                with lock:
                    results[group_id] = (keep_idx, remove_set)
            except Exception as e:
                logger.error(f"批量去重判断失败(组{group_id}): {e}")
                with lock:
                    results[group_id] = (0, set())

        with ThreadPoolExecutor(max_workers=API_MAX_CONCURRENCY) as executor:
            futures = []
            for group_id, articles_info in article_groups:
                future = executor.submit(_review_single_group, group_id, articles_info)
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"批量去重判断异常: {e}")

        return [(gid, results[gid][1]) for gid in sorted(results.keys())]

    def _dedup_review_single_group(self, articles_info: List[dict]) -> Tuple[int, set]:
        """
        对一组疑似重复的文章进行LLM判断

        Args:
            articles_info: 文章信息列表，每个元素包含title, source, summary

        Returns:
            (应保留的索引, 应移除的索引集合)
        """
        if len(articles_info) < 2:
            return 0, set()

        articles_text = []
        for i, art in enumerate(articles_info):
            articles_text.append(f"文章{i+1}(编号{i+1}):\n标题：{art['title']}\n来源：{art['source']}\n摘要：{art.get('summary', '')[:500]}")
        articles_str = "\n\n".join(articles_text)

        prompt = f"""请仔细分析以下{len(articles_info)}篇文章，判断它们是否在讲同一事件或话题。

{articles_str}

【重要判断标准】：
1. 如果这些文章在讲**同一事件**（如：特朗普访华、创业板指创历史新高等），应该去重，只保留信息最全面的一篇
2. 如果这些文章在讲**同一话题的不同方面**（如：AI对教育的影响 vs AI对就业的影响，这是两个不同的话题），应该都保留
3. 如果这些文章在讲**完全不相关的事件**，应该都保留

【特别注意】：
- 标题相似不代表是同一事件，要看内容
- 同一事件的不同阶段报道（如：外交部宣布访华 vs 特朗普抵达北京 vs 会晤结果）算同一事件，应去重
- 同一事件的不同角度（如：特朗普访华的经贸角度 vs 地缘政治角度）也算同一事件，应去重——但前提是核心新闻事实（人物+事件+动作）必须一致
- **但不同事件即使都涉及"外交"或"中国"的泛化主题，也不应去重**：如"普京访华"和"日韩首脑联系特朗普"是两个完全不同的外交事件，不应去重
- 但同一大话题下的不同具体事件（如：百度AI基础设施 vs 快手可灵AI分拆）不应去重
- 注意看摘要中的具体事件细节，如时间、地点、人物、具体冲突内容等
- **绝对不能因为两篇文章都属于同一泛化分类就认为是同一事件**。例如：一篇讲"莫奈真迹被误判AI画作"、另一篇讲"盲道摆拍造假"，虽然都涉及"信任危机"，但这是两个完全不同的具体事件，不应去重
- **同一事件的严格标准：核心新闻事实完全一致（同一个人、同一件事、同一个新闻事实）**

请严格按以下JSON格式回复：
{{"is_same_event": true/false, "to_remove": [需要移除的文章编号列表，如[2,3]表示移除编号2和3的文章], "keep": [应保留的文章编号，通常只保留1篇最全面的], "reason": "判断理由"}}

如果判断为同一事件，to_remove中填入要移除的文章编号（编号从1开始），keep中填入应保留的文章编号。
保留信息最全面、分析最深入的那篇。
如果判断为不同事件，to_remove填入空列表[]，keep填入所有文章编号。

只回复JSON，不要有其他内容。"""

        try:
            result_json = self._call_api(prompt)
            result = json.loads(result_json)
            is_same = result.get("is_same_event", False)
            to_remove_nums = result.get("to_remove", [])
            reason = result.get("reason", "")

            logger.info(f"LLM去重判断: {'同一事件需去重' if is_same else '不同事件保留'}，原因: {reason}")

            if is_same and to_remove_nums:
                remove_set = set()
                for num in to_remove_nums:
                    if 1 <= num <= len(articles_info):
                        remove_set.add(num - 1)  # 转为0-based索引
                # 找到保留的索引
                keep_idx = 0
                keep_nums = result.get("keep", [])
                if keep_nums:
                    keep_num = keep_nums[0]
                    if 1 <= keep_num <= len(articles_info):
                        keep_idx = keep_num - 1
                else:
                    # 保留第一个不在to_remove中的
                    for i in range(len(articles_info)):
                        if (i + 1) not in to_remove_nums:
                            keep_idx = i
                            break
                return keep_idx, remove_set
            else:
                return 0, set()

        except Exception as e:
            logger.error(f"LLM去重判断失败: {e}")
            return 0, set()

    def verify_document_duplicates(self, document_text: str) -> Tuple[bool, list, str]:
        """
        验证生成的文档中是否还存在重复内容
        
        Args:
            document_text: 文档的文本内容（或关键部分）
            
        Returns:
            (has_duplicates, suggestions)
            - has_duplicates: 是否存在重复
            - suggestions: 修改建议（如果有重复）
        """
        # 限制输入长度，避免超出API限制
        max_chars = 16000
        if len(document_text) > max_chars:
            # 分段采样：取前6000字+中间4000字+后6000字，确保覆盖更多内容
            head = document_text[:6000]
            mid_start = len(document_text) // 2 - 2000
            mid = document_text[mid_start:mid_start + 4000]
            tail = document_text[-6000:]
            document_text = head + "\n...（中间部分）...\n" + mid + "\n...（文档内容已截断）...\n" + tail
        
        system_prompt = "你是一位资深新闻编辑，擅长检查资讯文档中的重复内容并提供修改建议。"
        
        user_prompt = f"""请仔细检查以下每日资讯文档，判断是否存在重复或高度相似的内容。

文档内容：
{document_text}

【检查标准】：
1. **重复事件**：两篇或多篇资讯在报道同一个事件（即使标题不同、角度不同）
2. **重复信息**：不同资讯中包含大量相同的事实、数据、引述
3. **重复主题**：多篇资讯聚焦同一个主题但缺乏足够差异化的信息

【不视为重复的情况】：
- 同一事件的不同方面（如政策本身 vs 市场反应 vs 专家解读）
- 相关但独立的事件（如：两家公司分别发布财报）
- 同一趋势下的不同案例

请严格按以下JSON格式回复：
{{"has_duplicates": true/false, "duplicate_groups": ["第X条和第Y条都涉及ZZZ", ...], "suggestions": "具体的修改建议"}}

如果存在重复：
- has_duplicates = true
- duplicate_groups: 列出发现的重复组，格式必须是"第X条和第Y条都涉及ZZZ"（X和Y是文章序号）
- suggestions: 提供具体的修改建议

如果没有重复：
- has_duplicates = false
- duplicate_groups: []
- suggestions: "文档无重复内容"

只回复JSON，不要有其他内容。"""

        try:
            response = self._call_api_with_system(system_prompt, user_prompt)
            result = json.loads(response)
            has_duplicates = result.get("has_duplicates", False)
            suggestions = result.get("suggestions", "")
            duplicate_groups = result.get("duplicate_groups", [])
            
            if has_duplicates and duplicate_groups:
                # 保持结构化数据，不再拼接为单行字符串
                pass  # duplicate_groups 和 suggestions 分别保留
            
            logger.info(f"文档重复验证: {'存在重复' if has_duplicates else '无重复'} - {suggestions[:100]}...")
            return has_duplicates, duplicate_groups, suggestions
            
        except Exception as e:
            logger.error(f"文档重复验证失败: {e}")
            return False, [], ""

    def batch_classify_ad_and_mece(self, articles: List[dict]) -> List[dict]:
        """
        批量并发判断广告+MECE分类（8线程并发，合并为一次API调用）

        Args:
            articles: 文章列表，每个元素包含title和content

        Returns:
            结果列表，每个元素包含is_ad、reason和category
        """
        if not articles:
            return []

        results = [None] * len(articles)
        lock = threading.Lock()

        def _classify_single(idx, article):
            title = article.get('title', '')
            content = article.get('content', '')
            try:
                result = self.classify_ad_and_mece(title, content)
                with lock:
                    results[idx] = result
            except Exception as e:
                logger.error(f"广告+分类判断失败: {title[:30]}... 错误: {e}")
                with lock:
                    results[idx] = {'is_ad': False, 'reason': f'判断失败: {e}', 'category': '11.3'}

        with ThreadPoolExecutor(max_workers=API_MAX_CONCURRENCY) as executor:
            futures = []
            for i, article in enumerate(articles):
                future = executor.submit(_classify_single, i, article)
                futures.append(future)
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"广告+分类判断异常: {e}")

        # 确保所有结果都有值
        for i in range(len(results)):
            if results[i] is None:
                results[i] = {'is_ad': False, 'reason': '未知', 'category': '11.3'}

        return results

    def batch_classify_advertisement(self, articles: List[dict]) -> List[dict]:
        """
        批量并发判断文章是否为广告（8线程并发）

        Args:
            articles: 文章列表，每个元素包含title和content

        Returns:
            结果列表，每个元素包含is_ad和reason
        """
        if not articles:
            return []

        results = [None] * len(articles)
        lock = threading.Lock()

        def _classify_single(idx, article):
            title = article.get('title', '')
            content = article.get('content', '')
            try:
                is_ad, reason = self.is_advertisement(title, content)
                with lock:
                    results[idx] = {'is_ad': is_ad, 'reason': reason}
            except Exception as e:
                logger.error(f"广告判断失败: {title[:30]}... 错误: {e}")
                with lock:
                    results[idx] = {'is_ad': False, 'reason': f'判断失败: {e}'}

        with ThreadPoolExecutor(max_workers=API_MAX_CONCURRENCY) as executor:
            futures = []
            for i, article in enumerate(articles):
                future = executor.submit(_classify_single, i, article)
                futures.append(future)
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"广告判断异常: {e}")

        # 确保所有结果都有值
        for i in range(len(results)):
            if results[i] is None:
                results[i] = {'is_ad': False, 'reason': '未知'}

        return results

    def batch_classify_mece(self, articles: List[dict]) -> List[str]:
        """
        批量并发判断文章MECE分类（8线程并发）

        Args:
            articles: 文章列表，每个元素包含title和summary

        Returns:
            分类编号列表
        """
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
                # 默认值已在初始化

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
