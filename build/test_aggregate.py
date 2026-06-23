#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试聚合功能，显示10条线索标题"""
import sys
import os
import json

# 添加路径
_skill_src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "每日资讯skill", "src")
sys.path.insert(0, _skill_src)

from docx_parser import parse_docx
from aggregate import aggregate_issue
import auth
from ai_client import DeepSeekClient

# 解析 docx
docx_path = "../../每日资讯/2026_06/每日资讯_2026-06-22/每日资讯_2026-06-22.docx"
parsed = parse_docx(docx_path)
if not parsed:
    print("解析失败")
    sys.exit(1)

print(f"解析到 {parsed['article_count']} 篇文章")
print(f"日期: {parsed['date']}\n")

# 调用 API 聚合
api_key = auth.get_api_key()
if not api_key:
    print("未获取到 API Key")
    sys.exit(1)

client = DeepSeekClient(api_key)
result = aggregate_issue(parsed, client)
if not result:
    print("聚合失败")
    sys.exit(1)

# 显示结果
print(f"成功生成 {len(result['clues'])} 条线索:\n")
for c in result['clues']:
    print(f"{c['index']}. {c['title']}")
    print(f"   来源数: {len(c['sources'])}, 课题: {', '.join(c['topics'])}\n")

# 保存到 JSON 文件
output_path = "../web/data/test_2026-06-22.json"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n完整结果已保存到: {output_path}")
