#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
内容过滤器 - 增强版广告和商业推广识别
采用多层过滤策略，宁缺毋滥
"""

import re
import logging
from typing import List, Tuple, Set
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class FilterResult:
    """过滤结果"""
    is_filtered: bool
    reason: str
    confidence: float  # 0-1，过滤置信度

class ContentFilter:
    """增强版内容过滤器"""
    
    # 第一层：明确的广告关键词
    AD_KEYWORDS_LEVEL1 = {
        # 促销类
        '促销', '优惠', '折扣', '特价', '限时', '抢购', '秒杀', '团购',
        '买一送一', '满减', '立减', '省钱', '划算', '超值', '清仓', '甩卖',
        '钜惠', '大促', '爆款', '热卖', '热销', '抢购中', '仅剩', '库存',
        '特价', '折扣券', '优惠券', '代金券', '满减券', '立减券',
        # 商业推广
        '推广', '广告', '赞助', '招商', '加盟', '代理', '分销', '批发',
        '投资', '理财', '保险', '贷款', '信用卡', '融资', '众筹',
        # 电商相关
        '下单', '订购', '预订', '预约', '立即购买', '马上购买', '点击购买',
        '在线购买', '官网购买', '咨询热线', '客服热线', '订购热线',
        # 行动召唤
        '扫码', '扫一扫', '二维码', '点击链接', '了解更多', '查看详情',
        '立即咨询', '联系我们', '马上咨询', '咨询详情',
        # 产品推广
        '新品上市', '新品发布', '限量发售', '首发', '独家', '首发优惠',
        '专属优惠', 'VIP专享', '会员专享', '粉丝专享', '粉丝福利',
        # 营销话术
        '不容错过', '机会难得', '最后机会', '仅限今天', '马上行动',
        '抓紧时间', '手慢无', '错过等一年', '仅限前', '名额有限',
        '先到先得', '售完即止', '限时优惠', '限时特价', '限时免费',
        # 强力推广词
        '重磅', '震撼', '惊喜', '重磅来袭', '震撼发布', '惊喜优惠',
        '超低价', '白菜价', '史低', '历史最低', '跌破底价',
    }
    
    # 第二层：商业行为模式
    AD_PATTERNS_LEVEL2 = {
        # 价格模式
        'price_patterns': [
            r'原价\s*\d+', r'现价\s*\d+', r'特价\s*\d+',
            r'仅需\s*\d+', r'只需\s*\d+', r'¥\s*\d+', r'￥\s*\d+',
            r'\d+\s*元', r'\d+\s*块钱', r'\d+\s*块',
            r'\d+\.\d+\s*元', r'\d+\.\d+\s*块',
            r'售价\s*\d+', r'定价\s*\d+', r'标价\s*\d+',
            r'活动价\s*\d+', r'优惠价\s*\d+', r'促销价\s*\d+',
        ],
        # 联系方式模式
        'contact_patterns': [
            r'微信\s*[:：]\s*\S+', r'微信号\s*[:：]\s*\S+',
            r'QQ\s*[:：]\s*\d+', r'QQ号\s*[:：]\s*\d+',
            r'电话\s*[:：]\s*\d+', r'手机\s*[:：]\s*1[3-9]\d{9}',
            r'1[3-9]\d{9}', r'0\d{2,3}-?\d{7,8}',
            r'扫码\s*[:：]', r'二维码\s*[:：]',
            r'加\s*微信', r'加\s*QQ', r'联系\s*微信',
            r'添加\s*微信', r'添加\s*QQ',
        ],
        # URL模式
        'url_patterns': [
            r'http[s]?://\S+', r'www\.\S+\.\S+',
            r'\.com\b', r'\.cn\b', r'\.net\b', r'\.org\b',
        ],
        # 购买引导
        'buy_patterns': [
            r'购买\s*[:：]', r'下单\s*[:：]', r'订购\s*[:：]',
            r'请\s*购买', r'立即\s*购买', r'马上\s*购买',
            r'点击\s*购买', r'点击\s*链接', r'访问\s*链接',
        ],
    }
    
    # 第三层：标题推广特征
    TITLE_AD_INDICATORS = {
        # 推广语气
        '来了！', '重磅！', '惊喜！', '福利！', '免费！', '赠送！',
        '大放送', '限免', '0元', '免费领取', '免费试用', '免费体验',
        '不要钱', '0成本', '零成本', '免费获取',
        # 电商语气
        '热卖中', '火爆中', '抢购中', '疯抢', '秒杀',
        '最后\d+天', '仅剩\d+天', '最后\d+小时', '仅剩\d+小时',
        '限时\d+天', '限时\d+小时',
        # 产品推广
        '新品上市', '全新上市', '重磅推出', '震撼推出',
        '限量发售', '独家首发', '全球首发',
        # 价格优惠
        '半价', '一折', '二折', '三折', '四折', '五折', '六折', '七折', '八折', '九折',
        '超低价', '特惠价', '优惠价', '特价',
    }
    
    # 第四层：文章结构特征（软文特征）
    SOFT_ARTICLE_PATTERNS = {
        # 推广文章常见开头
        'intro_patterns': [
            r'最近.*朋友推荐',
            r'今天给大家推荐',
            r'强烈推荐',
            r'不得不推',
            r'良心推荐',
            r'亲自体验',
            r'亲自试用',
            r'亲身经历',
        ],
        # 软文常见过渡
        'transition_patterns': [
            r'经过.*发现',
            r'使用之后',
            r'体验之后',
            r'用了之后',
            r'效果.*出人意料',
            r'效果.*惊喜',
        ],
        # 软文常见结尾
        'conclusion_patterns': [
            r'感兴趣.*可以',
            r'想了解.*可以',
            r'更多.*请',
            r'详情.*请',
            r'咨询.*请',
            r'联系.*请',
        ],
    }
    
    # 第五层：高频营销词汇
    HIGH_FREQUENCY_AD_WORDS = {
        # 产品词
        '产品', '商品', '货物', '物资', '物品', '商品',
        '商城', '店铺', '旗舰店', '专营店', '专卖店', '体验店',
        '品牌', '名牌', '大品牌', '国际品牌',
        # 营销词
        '营销', '推广', '宣传', '广告', '投放', '推广费',
        '销售', '售出', '售卖', '出售', '推销',
        '客户', '客户群', '客户经理', '客户服务', '客服',
        # 订单词
        '订单', '订单号', '发货', '快递', '物流', '配送',
        '退换货', '售后服务', '服务热线', '售后电话',
    }
    
    # 白名单关键词（包含这些词的广告可能是正常内容）
    WHITELIST_KEYWORDS = {
        '公益活动', '慈善活动', '志愿者', '志愿服务',
        '公益活动报名', '志愿者招募', '慈善募捐',
        '科学研究', '学术研究', '科研课题', '学术会议',
        '政府政策', '官方通知', '政策解读', '官方发布',
        '新闻报道', '新闻稿', '记者', '媒体',
        '知识科普', '科普文章', '科普视频', '科普',
    }
    
    @classmethod
    def is_advertisement(cls, title: str, content: str) -> FilterResult:
        """
        判断是否为广告或商业推广（多层过滤）
        
        Args:
            title: 文章标题
            content: 文章内容
            
        Returns:
            FilterResult对象
        """
        # 合并标题和内容，标题权重更高
        text = title + " " + content
        title_lower = title.lower()
        content_lower = content.lower()
        
        logger.debug(f"开始过滤文章: {title[:50]}...")
        
        # 0. 白名单检查（优先）
        whitelist_hits = cls._check_whitelist(title, content)
        if whitelist_hits:
            logger.debug(f"命中白名单关键词: {whitelist_hits}")
            # 白名单不一定是非广告，需要继续检查
            pass
        
        # 1. 第一层：关键词过滤（最高优先级）
        level1_result = cls._check_level1_keywords(title, content)
        if level1_result.is_filtered:
            logger.info(f"文章被过滤（第一层）: {title[:50]} - 原因: {level1_result.reason}")
            return level1_result
        
        # 2. 第二层：模式过滤
        level2_result = cls._check_level2_patterns(title, content)
        if level2_result.is_filtered:
            logger.info(f"文章被过滤（第二层）: {title[:50]} - 原因: {level2_result.reason}")
            return level2_result
        
        # 3. 第三层：标题特征过滤
        level3_result = cls._check_title_features(title)
        if level3_result.is_filtered:
            logger.info(f"文章被过滤（第三层）: {title[:50]} - 原因: {level3_result.reason}")
            return level3_result
        
        # 4. 第四层：软文特征过滤
        level4_result = cls._check_soft_article_features(title, content)
        if level4_result.is_filtered:
            logger.info(f"文章被过滤（第四层）: {title[:50]} - 原因: {level4_result.reason}")
            return level4_result
        
        # 5. 第五层：高频营销词汇统计
        level5_result = cls._check_high_frequency_words(title, content)
        if level5_result.is_filtered:
            logger.info(f"文章被过滤（第五层）: {title[:50]} - 原因: {level5_result.reason}")
            return level5_result
        
        # 6. 综合评分（最终决策）
        final_result = cls._comprehensive_score(title, content)
        if final_result.is_filtered:
            logger.info(f"文章被过滤（综合评分）: {title[:50]} - 原因: {final_result.reason}")
            return final_result
        
        logger.debug(f"文章通过过滤: {title[:50]}")
        return FilterResult(is_filtered=False, reason="", confidence=0.0)
    
    @classmethod
    def _check_whitelist(cls, title: str, content: str) -> Set[str]:
        """检查白名单关键词"""
        hits = set()
        text = title + " " + content
        for keyword in cls.WHITELIST_KEYWORDS:
            if keyword in text:
                hits.add(keyword)
        return hits
    
    @classmethod
    def _check_level1_keywords(cls, title: str, content: str) -> FilterResult:
        """第一层：明确广告关键词检查"""
        found_keywords = []
        
        # 标题权重更高
        for keyword in cls.AD_KEYWORDS_LEVEL1:
            if keyword in title:
                found_keywords.append(f"标题-{keyword}")
            elif keyword in content:
                found_keywords.append(f"内容-{keyword}")
        
        if found_keywords:
            # 如果找到3个以上关键词，高置信度过滤
            if len(found_keywords) >= 3:
                return FilterResult(
                    is_filtered=True,
                    reason=f"包含多个广告关键词: {', '.join(found_keywords[:3])}等",
                    confidence=0.9
                )
            # 如果标题包含广告关键词，高置信度过滤
            if any("标题-" in kw for kw in found_keywords):
                return FilterResult(
                    is_filtered=True,
                    reason=f"标题包含广告关键词: {', '.join([kw for kw in found_keywords if '标题-' in kw][:2])}",
                    confidence=0.85
                )
        
        return FilterResult(is_filtered=False, reason="", confidence=0.0)
    
    @classmethod
    def _check_level2_patterns(cls, title: str, content: str) -> FilterResult:
        """第二层：商业行为模式检查"""
        reasons = []
        
        # 检查价格模式
        price_count = 0
        for pattern in cls.AD_PATTERNS_LEVEL2['price_patterns']:
            matches = re.findall(pattern, title + " " + content)
            if matches:
                price_count += len(matches)
        
        if price_count >= 2:
            reasons.append(f"包含{price_count}处价格信息")
        
        # 检查联系方式
        contact_count = 0
        for pattern in cls.AD_PATTERNS_LEVEL2['contact_patterns']:
            if re.search(pattern, title + " " + content):
                contact_count += 1
        
        if contact_count >= 1:
            reasons.append(f"包含联系方式（{contact_count}处）")
        
        # 检查URL数量
        urls = re.findall(r'http[s]?://\S+', title + " " + content)
        if len(urls) > 3:
            reasons.append(f"包含过多链接（{len(urls)}个）")
        
        # 检查购买引导
        for pattern in cls.AD_PATTERNS_LEVEL2['buy_patterns']:
            if re.search(pattern, content):
                reasons.append("包含购买引导")
                break
        
        if reasons:
            return FilterResult(
                is_filtered=True,
                reason="; ".join(reasons),
                confidence=0.8
            )
        
        return FilterResult(is_filtered=False, reason="", confidence=0.0)
    
    @classmethod
    def _check_title_features(cls, title: str) -> FilterResult:
        """第三层：标题推广特征检查"""
        for indicator in cls.TITLE_AD_INDICATORS:
            if indicator in title:
                return FilterResult(
                    is_filtered=True,
                    reason=f"标题包含推广特征词: {indicator}",
                    confidence=0.75
                )
        
        return FilterResult(is_filtered=False, reason="", confidence=0.0)
    
    @classmethod
    def _check_soft_article_features(cls, title: str, content: str) -> FilterResult:
        """第四层：软文特征检查"""
        feature_count = 0
        
        # 检查开头特征
        for pattern in cls.SOFT_ARTICLE_PATTERNS['intro_patterns']:
            if re.search(pattern, content[:500]):
                feature_count += 1
                break
        
        # 检查过渡特征
        for pattern in cls.SOFT_ARTICLE_PATTERNS['transition_patterns']:
            if re.search(pattern, content):
                feature_count += 1
                break
        
        # 检查结尾特征
        for pattern in cls.SOFT_ARTICLE_PATTERNS['conclusion_patterns']:
            if re.search(pattern, content[-500:]):
                feature_count += 1
                break
        
        # 如果同时具备2个以上软文特征，过滤
        if feature_count >= 2:
            return FilterResult(
                is_filtered=True,
                reason=f"具备{feature_count}个软文特征",
                confidence=0.7
            )
        
        return FilterResult(is_filtered=False, reason="", confidence=0.0)
    
    @classmethod
    def _check_high_frequency_words(cls, title: str, content: str) -> FilterResult:
        """第五层：高频营销词汇统计"""
        text = title + " " + content
        word_count = 0
        found_words = []
        
        for word in cls.HIGH_FREQUENCY_AD_WORDS:
            count = text.count(word)
            if count > 0:
                word_count += count
                found_words.append(word)
        
        # 如果营销词汇出现超过5次，过滤
        if word_count >= 5:
            return FilterResult(
                is_filtered=True,
                reason=f"高频营销词汇出现{word_count}次: {', '.join(found_words[:5])}",
                confidence=0.65
            )
        
        return FilterResult(is_filtered=False, reason="", confidence=0.0)
    
    @classmethod
    def _comprehensive_score(cls, title: str, content: str) -> FilterResult:
        """综合评分"""
        score = 0
        reasons = []
        
        # 标题长度过短（可能是简单推广）
        if len(title) < 10:
            score += 10
            reasons.append("标题过短")
        
        # 内容包含大量数字（可能是价格）
        digit_count = len(re.findall(r'\d+', content))
        if digit_count > 10:
            score += 15
            reasons.append(f"包含大量数字({digit_count}处)")
        
        # 内容包含感叹号（情绪化推广）
        exclamation_count = title.count('！') + title.count('!')
        if exclamation_count >= 2:
            score += 10
            reasons.append(f"标题包含{exclamation_count}个感叹号")
        
        # 内容过于简短（可能是简单广告）
        if len(content) < 100:
            score += 20
            reasons.append("内容过短")
        
        # 综合评分阈值
        if score >= 40:
            return FilterResult(
                is_filtered=True,
                reason=f"综合评分过高({score}分): {', '.join(reasons)}",
                confidence=0.6
            )
        
        return FilterResult(is_filtered=False, reason="", confidence=0.0)
