#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试关键词+Jaccard相似度分析 - 改进版"""

import sys
sys.path.insert(0, 'src')
from ai_client import SIMILARITY_THRESHOLD
import re

# 使用真实的文章标题来测试
titles = [
    "于东来魏建军隔空喊话：两个从泥土里爬出来的人",
    "河南获批一条高铁，陕西人为何更兴奋",
    "谷歌，真的退出中国了吗？",
    "中国PMI重回扩张区间，国行版ChatGPT要来了",
    "外企在中国，今天需要怎样的心态",
    "偏执的犒赏：张雪峰，机车和他的疯马秀",
    "B站下线猜你喜欢，这步走得值吗",
    "DeepSeek又崩了，焦虑的打工人等了一整夜",
    "张雪峰回应落榜风波，说自己被误解了",
    "大学生校内送外卖被处分，管理何时能人性化",
    "信号来了，房地产彻底明牌",
    "李嘉诚又大甩卖，在头等舱的他，错过了什么",
    "美的亮剑！物理AI才是中国AI的真正机会",
    "全球风口城市房价上涨，各自背靠什么",
    "地铁吐血女孩接收捐款账户被封，平台责任几何",
    "买安眠药收注销驾照短信，个人隐私得加把锁",
    "女子被羁押821天无罪后再被立案，申请国赔惹的祸",
    "全球资产大清算，来临了？",
]

def extract_keywords_v2(text):
    """提取关键词 - 改进版"""
    if not text:
        return set()
    keywords = set()

    # 提取英文词
    english = re.findall(r'[a-zA-Z]{2,}', text)
    keywords.update([w.lower() for w in english])

    # 提取数字
    numbers = re.findall(r'\d+', text)
    keywords.update(numbers)

    # 清理后的中文文本
    chinese_text = re.sub(r'[^\u4e00-\u9fa5]', '', text)

    # 提取2-3字词组（更有意义的名词、动词等）
    for length in [2, 3]:
        for i in range(len(chinese_text) - length + 1):
            word = chinese_text[i:i+length]
            # 过滤掉停用词
            stop_words = ['的', '是', '在', '了', '和', '与', '或', '也', '都', '很',
                         '一个', '这个', '那个', '什么', '怎么', '如何', '怎样', '的']
            if word not in stop_words and len(set(word)) > 1:  # 避免重复字
                keywords.add(word)

    return keywords

def jaccard(s1, s2):
    if not s1 or not s2:
        return 0.0
    inter = len(s1 & s2)
    union = len(s1 | s2)
    return inter / union if union > 0 else 0.0

# 提取关键词
all_keywords = [extract_keywords_v2(t) for t in titles]
print(f"文章数量: {len(titles)}")
print(f"阈值: {SIMILARITY_THRESHOLD}")
print(f"\n各文章关键词示例:")
for i in range(min(5, len(titles))):
    print(f"  文章{i}: {sorted(list(all_keywords[i]))[:15]}")
    print(f"        {titles[i]}")

# 计算所有相似度
all_pairs = []
n = len(titles)
for i in range(n):
    for j in range(i+1, n):
        sim = jaccard(all_keywords[i], all_keywords[j])
        all_pairs.append((i, j, sim))

# 输出表格
print(f'\n{"="*100}')
print(f'关键词Jaccard 相似度分析结果 (改进版)')
print(f'{"="*100}')
print(f'{"序号":<5}{"文章1":<40}{"文章2":<40}{"相似度":<10}{"状态":<10}')
print(f'{"-"*100}')

all_pairs_sorted = sorted(all_pairs, key=lambda x: x[2], reverse=True)
for idx, (i, j, sim) in enumerate(all_pairs_sorted[:50], 1):
    t1 = titles[i][:37]
    t2 = titles[j][:37]
    status = "[相似]" if sim >= SIMILARITY_THRESHOLD else "[不相似]"
    print(f'{idx:<5}{t1:<40}{t2:<40}{sim:<10.4f}{status}')

if len(all_pairs) > 50:
    print(f"... (共{len(all_pairs)}对，仅显示前50对)")

print(f'{"-"*100}')
similar_count = len([x for x in all_pairs if x[2]>=SIMILARITY_THRESHOLD])
print(f'总对数: {len(all_pairs)}, 阈值内(>{SIMILARITY_THRESHOLD}): {similar_count}')
print(f'{"="*100}')
