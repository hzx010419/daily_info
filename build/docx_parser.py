#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
每日资讯 docx 解析器

从「每日资讯/YYYY_MM/每日资讯_YYYY-MM-DD/每日资讯_YYYY-MM-DD.docx」中提取
结构化文章数据，供后续 AI 重新聚合为「写作线索」使用。

每篇文章提取字段：
  - title:    AI 优化后的标题（去掉【】与序号）
  - source:   来源（公众号名，可能是"多来源整合"）
  - summary:  内容摘要
  - links:    [{title, source, url}]  原文链接列表
              · 单篇文章：1 个链接（来自"文章链接："）
              · 整合文章：N 个链接（来自"来源列表"中的超链接）
"""

import os
import re
from typing import List, Dict, Optional

import docx
from docx.oxml.ns import qn

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
HYPERLINK_RT = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"


def _para_text_and_links(paragraph) -> (str, List[str]):
    """返回段落纯文本，以及段落内出现的超链接 URL 列表（按出现顺序）。"""
    urls: List[str] = []
    el = paragraph._p
    # 遍历所有 w:hyperlink，读取其 r:id -> 目标 URL
    try:
        rels = paragraph.part.rels
        for hl in el.findall(qn("w:hyperlink")):
            rid = hl.get(qn("r:id"))
            if rid and rid in rels:
                target = rels[rid]._target
                if target:
                    urls.append(target)
    except Exception:
        pass
    # 降级：如果没找到超链接，尝试从文本中提取 http(s) URL
    if not urls:
        text = paragraph.text or ""
        for m in __import__("re").finditer(r"https?://[^\s）)\"]+", text):
            urls.append(m.group(0))
    return paragraph.text or "", urls


def _extract_bracket_titles(text: str) -> List[Dict[str, str]]:
    """从来源列表行提取 《标题》（来源） 结构。"""
    result = []
    # 匹配 《...》（...）  其中来源括号可能是中文括号
    for m in re.finditer(r"《([^》]+)》\s*[（(]([^）)]*)[）)]", text):
        result.append({"title": m.group(1).strip(), "source": m.group(2).strip()})
    # 兜底：只有《标题》没有来源
    if not result:
        for m in re.finditer(r"《([^》]+)》", text):
            result.append({"title": m.group(1).strip(), "source": ""})
    return result


def parse_docx(docx_path: str) -> Optional[Dict]:
    """解析单个 docx，返回 {date, weekday, articles:[...]}。"""
    if not os.path.exists(docx_path):
        return None

    doc = docx.Document(docx_path)
    paras = doc.paragraphs

    # 从文件名/标题解析日期
    date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", os.path.basename(docx_path))
    date_str = "-".join(date_match.groups()) if date_match else ""

    articles: List[Dict] = []
    current: Optional[Dict] = None
    in_source_list = False  # 是否处于"来源列表"多行收集状态

    # 文章标题行：
    #   · 新格式：一、【标题】
    #   · 旧格式：一、标题（无书名号/方括号）
    # 旧格式需排除「目录」条目（也是 序号、大类名），用"下一非空行是否为来源行"区分。
    title_bracket_re = re.compile(r"^\s*[一二三四五六七八九十百零]+、\s*【(.+?)】\s*$")
    title_plain_re = re.compile(r"^\s*[一二三四五六七八九十百零]+、\s*(.+?)\s*$")
    # 分隔线
    sep_re = re.compile(r"^[—\-─]{5,}$")

    # 预取所有段落的纯文本，供"下一行"判断
    para_texts = [p.text.strip() for p in paras]

    def _next_nonempty_text(start_idx: int) -> str:
        for k in range(start_idx + 1, len(para_texts)):
            if para_texts[k]:
                return para_texts[k]
        return ""

    def _flush():
        nonlocal current
        if current is not None and current.get("title"):
            articles.append(current)
        current = None

    def _detect_title(text: str, idx: int) -> Optional[str]:
        """若该行是文章标题，返回标题文本，否则 None。"""
        m = title_bracket_re.match(text)
        if m:
            return m.group(1).strip()
        m = title_plain_re.match(text)
        if m:
            # 旧格式：必须后接"来源"行，才算文章标题（排除目录项）
            nxt = _next_nonempty_text(idx)
            if nxt.startswith("来源"):
                return m.group(1).strip().strip("【】")
        return None

    for idx, p in enumerate(paras):
        raw, urls = _para_text_and_links(p)
        text = raw.strip()
        if not text:
            continue

        # 跳过目录 / 大类标题 / 分隔块
        if sep_re.match(text) or text.startswith("═"):
            in_source_list = False
            continue

        m_title = _detect_title(text, idx)
        if m_title:
            _flush()
            current = {
                "title": m_title,
                "source": "",
                "summary": "",
                "links": [],
            }
            in_source_list = False
            continue

        if current is None:
            continue

        # 来源行
        if text.startswith("来源：") or text.startswith("来源:"):
            current["source"] = re.sub(r"^来源[：:]\s*", "", text).strip()
            in_source_list = False
            continue

        # 发布时间
        if text.startswith("发布时间"):
            in_source_list = False
            continue

        # 内容摘要
        if text.startswith("内容摘要"):
            current["summary"] = re.sub(r"^内容摘要[：:]\s*", "", text).strip()
            in_source_list = False
            continue

        # 单篇文章链接
        if text.startswith("文章链接"):
            url = re.sub(r"^文章链接[：:]\s*", "", text).strip()
            if not url and urls:
                url = urls[0]
            if url:
                current["links"].append({
                    "title": current["title"],
                    "source": current["source"],
                    "url": url,
                })
            in_source_list = False
            continue

        # 来源列表（整合文章）起始
        if text.startswith("来源列表"):
            in_source_list = True
            continue

        # 来源列表条目：• 《标题》（来源）  且带超链接
        if in_source_list:
            bracket = _extract_bracket_titles(text)
            if bracket:
                # 将本行的超链接按顺序分配给本行的《》条目
                for i, b in enumerate(bracket):
                    url = urls[i] if i < len(urls) else (urls[0] if urls else "")
                    current["links"].append({
                        "title": b["title"],
                        "source": b["source"] or current["source"],
                        "url": url,
                    })
                continue
            else:
                # 来源列表结束
                in_source_list = False

        # 摘要可能跨多段（截断的长摘要），补充到 summary
        if current.get("summary") and not text.startswith(("来源", "发布", "文章", "•")):
            # 只在尚未进入链接区时拼接
            if not in_source_list:
                current["summary"] += text

    _flush()

    # 计算星期
    weekday = ""
    if date_str:
        try:
            from datetime import datetime
            wd = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
            weekday = wd[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
        except Exception:
            pass

    # 给每篇文章兜底链接（无链接则空）
    for a in articles:
        if not a["links"]:
            a["links"] = []

    return {
        "date": date_str,
        "weekday": weekday,
        "article_count": len(articles),
        "articles": articles,
    }


if __name__ == "__main__":
    import json
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else \
        "/Users/hzx/Desktop/codebuddy工作流/自动爬取skill/每日资讯/2026_06/每日资讯_2026-06-22/每日资讯_2026-06-22.docx"
    result = parse_docx(path)
    print(f"日期: {result['date']} {result['weekday']}  文章数: {result['article_count']}")
    for a in result["articles"][:3]:
        print("=" * 60)
        print("标题:", a["title"])
        print("来源:", a["source"])
        print("摘要:", a["summary"][:80])
        print("链接数:", len(a["links"]))
        for l in a["links"]:
            print("   -", l["title"][:30], "|", l["source"], "|", l["url"][:50])
    # 统计有链接的文章占比
    with_link = sum(1 for a in result["articles"] if a["links"])
    print("=" * 60)
    print(f"有链接文章: {with_link}/{result['article_count']}")
