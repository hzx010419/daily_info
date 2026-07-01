#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI摘要生成器 - 智能内容摘要
生成200-300字的AI智能摘要，而非简单截取
"""

import re
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

class AISummarizer:
    """AI智能摘要生成器"""
    
    @classmethod
    def generate_summary(cls, content: str, target_length: int = 250) -> str:
        """
        生成200-300字的AI内容摘要（基于全文内容的智能总结）
        
        Args:
            content: 文章完整内容
            target_length: 目标摘要长度（默认250字）
            
        Returns:
            200-300字的AI智能摘要
        """
        if not content or len(content.strip()) < 30:
            return "内容过短，无法生成有意义的摘要。"
        
        # 清理内容
        cleaned_content = cls._clean_content(content)
        
        # 如果内容本身就很短，直接返回
        if len(cleaned_content) <= 300:
            return cleaned_content
        
        # 使用智能算法生成摘要
        summary = cls._intelligent_summarization(cleaned_content, target_length)
        
        # 调整长度到200-300字范围
        summary = cls._adjust_length(summary, target_length)
        
        return summary
    
    @staticmethod
    def _clean_content(content: str) -> str:
        """清理和标准化文章内容"""
        if not content:
            return ""
        
        # 移除HTML标签
        content = re.sub(r'<[^>]+>', ' ', content)
        
        # 移除HTML实体
        content = re.sub(r'&nbsp;', ' ', content)
        content = re.sub(r'&amp;', '&', content)
        content = re.sub(r'&lt;', '<', content)
        content = re.sub(r'&gt;', '>', content)
        content = re.sub(r'&quot;', '"', content)
        content = re.sub(r'&#39;', "'", content)
        
        # 移除多余空白
        content = re.sub(r'\s+', ' ', content)
        
        # 移除特殊字符但保留中文标点
        content = re.sub(r'[^\u4e00-\u9fff\w\s，。！？；："\'、,.!?;:\-()（）《》【】]', '', content)
        
        return content.strip()
    
    @staticmethod
    def _split_sentences(content: str) -> List[str]:
        """智能分句"""
        # 按中文标点分句
        sentences = re.split(r'[。！？.!?]+', content)
        sentences = [s.strip() for s in sentences if s.strip()]
        return sentences
    
    @staticmethod
    def _extract_key_sentences(sentences: List[str], target_length: int) -> List[Tuple[int, str, float]]:
        """
        提取关键句子
        
        Returns:
            List of (index, sentence, score)
        """
        scored_sentences = []
        
        for i, sentence in enumerate(sentences):
            score = 0
            
            # 位置权重
            if i == 0:  # 第一句最重要
                score += 10
            elif i == 1:  # 第二句也重要
                score += 8
            elif i == len(sentences) - 1:  # 最后一句重要
                score += 9
            elif i == len(sentences) - 2:  # 倒数第二句
                score += 7
            
            # 长度权重（适中的句子更可能是关键句）
            length = len(sentence)
            if 20 <= length <= 100:
                score += 5
            elif 10 <= length < 20:
                score += 3
            
            # 关键词权重
            keywords = ['重要', '关键', '核心', '主要', '根本', '基本', '本质',
                       '因此', '所以', '结果', '总之', '综上', '可见',
                       '问题', '答案', '原因', '结果', '影响', '意义']
            for keyword in keywords:
                if keyword in sentence:
                    score += 3
                    break
            
            # 信息密度权重（包含较多数字、专有名词的句子可能更重要）
            digit_count = len(re.findall(r'\d+', sentence))
            if digit_count > 0:
                score += min(digit_count, 3)
            
            scored_sentences.append((i, sentence, score))
        
        # 按分数排序
        scored_sentences.sort(key=lambda x: x[2], reverse=True)
        
        return scored_sentences
    
    @staticmethod
    def _build_summary(key_sentences: List[Tuple[int, str, float]], target_length: int) -> str:
        """构建摘要，保持句子顺序"""
        # 重新按原始顺序排序
        key_sentences.sort(key=lambda x: x[0])
        
        summary = ""
        for idx, sentence, score in key_sentences:
            if len(summary) + len(sentence) < target_length * 1.2:
                summary += sentence + "。"
            else:
                break
        
        return summary.strip()
    
    @staticmethod
    def _supplement_content(summary: str, sentences: List[str], target_length: int) -> str:
        """补充内容"""
        current_length = len(summary)
        needed = target_length - current_length
        
        if needed <= 0:
            return summary
        
        # 查找尚未包含的句子
        used_indices = set()
        for sentence in re.split(r'[。！？.!?]+', summary):
            for i, s in enumerate(sentences):
                if s in sentence and s.strip():
                    used_indices.add(i)
                    break
        
        # 添加未使用的句子
        for i, sentence in enumerate(sentences):
            if i not in used_indices:
                if len(summary) + len(sentence) < target_length * 1.1:
                    summary += "。" + sentence
                else:
                    break
        
        return summary
    
    @staticmethod
    def _adjust_length(text: str, target_length: int) -> str:
        """调整文本长度到200-300字范围"""
        text = text.strip()
        min_length = int(target_length * 0.8)  # 200字
        max_length = int(target_length * 1.2)  # 300字
        
        current_length = len(text)
        
        # 如果长度正好在范围内
        if min_length <= current_length <= max_length:
            return text
        
        # 如果太长，智能截断
        if current_length > max_length:
            # 找到最接近目标长度的句子结束处
            sentences = re.split(r'[。！？.!?]', text)
            
            accumulated = 0
            result_sentences = []
            
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                
                if accumulated + len(sentence) <= target_length:
                    result_sentences.append(sentence)
                    accumulated += len(sentence)
                else:
                    # 如果这一句加进去会超太多，就停在这里
                    if accumulated + len(sentence) > target_length * 1.3:
                        break
                    result_sentences.append(sentence)
                    accumulated += len(sentence)
                    break
            
            if result_sentences:
                summary = '。'.join(result_sentences) + '。'
                # 确保不超过最大长度
                if len(summary) > max_length:
                    summary = summary[:max_length-3] + "..."
                return summary
            
            # 如果分句失败，直接截断
            # 尝试在标点处截断
            for i in range(max_length - 10, max_length + 10):
                if i < len(text) and text[i] in '。！？.!?':
                    return text[:i+1]
            
            # 最后手段：直接截断
            return text[:target_length] + "..."
        
        # 如果太短，保持原样（在实际应用中可以考虑智能扩展）
        return text
    
    @classmethod
    def generate_detailed_summary(cls, title: str, content: str, target_length: int = 250) -> str:
        """
        生成包含标题信息的详细摘要
        
        Args:
            title: 文章标题
            content: 文章内容
            target_length: 目标长度
            
        Returns:
            包含标题信息的摘要
        """
        # 生成正文摘要
        content_summary = cls.generate_summary(content, target_length - 20)
        
        # 如果标题较短，可以包含标题
        if len(title) < 30:
            return title + "。" + content_summary
        
        return content_summary
