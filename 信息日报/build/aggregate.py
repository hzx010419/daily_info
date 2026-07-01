#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AI 课题聚合器

读取单期资讯的全部文章，调用 DeepSeek API 将其重新聚合为
**恰好 10 个**「写作线索 / 课题选题方向」。

与「每日资讯」的 MECE 大类分类不同，这里按**研究课题视角**聚合：
  把可能构成同一研究方向的若干篇文章归在一起，
  并由 AI 生成该方向可延展的「相关课题」（如 AI 就业、AI 经济学）。

为避免 AI 杜撰链接，prompt 只让模型返回**文章序号**，
真实链接由本脚本根据序号回填，确保可点击跳转原文准确无误。

输出 schema：
{
  "date": "2026-06-22",
  "weekday": "星期一",
  "stats": {"total": 119, "selected": 51, "clues": 10},
  "clues": [
     {
       "index": 1,
       "title": "谷歌AI人才持续流失，行业版图加速重构",
       "summary": "……（150-260字综述）……",
       "topics": ["AI就业影响研究", "AI时代的组织变革", "AI的政治经济学"],
       "sources": [
          {"title": "……", "source": "……", "url": "https://..."}
       ]
     }, ... (共10条)
  ]
}
"""

import os
import sys
import json
import re
import time
from typing import Dict, List, Optional

import requests

# 复用「每日资讯skill」的 DeepSeek 客户端与授权模块
_SKILL_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "每日资讯skill", "src",
)
sys.path.insert(0, _SKILL_SRC)

from ai_client import DeepSeekClient  # noqa: E402


# 聚合任务输出较长（10 条线索 + 综述 + 来源），需要更高的 token 上限，
# 避免被 skill 内置的 max_tokens=2000 截断导致 JSON 不完整。
AGG_MAX_TOKENS = 4096
AGG_TIMEOUT = 120
AGG_MAX_RETRIES = 3


SYSTEM_PROMPT = (
    "你是腾讯研究院的资深研究选题策划，擅长从海量资讯中识别有研究价值的"
    "「写作线索 / 课题方向」。你能把看似分散的多篇报道，按潜在的研究课题视角"
    "聚合在一起，并提出可延展的研究课题方向。"
)


# 允许的线索分类标签（供前端全局筛选使用；与 aggregate prompt 保持一致）
CLUE_CATEGORIES = [
    "AI", "科技", "金融", "消费民生", "文旅",
    "数字内容", "时政", "企业商业", "地方治理", "社会热点",
]


def _norm_category(value) -> str:
    """把模型返回的 category 归一化到 CLUE_CATEGORIES；无法识别归为「社会热点」。"""
    if not value:
        return "社会热点"
    text = str(value).strip().strip("[]\"' 【】")
    if text in CLUE_CATEGORIES:
        return text
    for cat in CLUE_CATEGORIES:
        if cat in text or text in cat:
            return cat
    alias = {
        "人工智能": "AI", "科技产业": "科技", "财经": "金融", "经济": "金融",
        "民生": "消费民生", "消费": "消费民生", "文化旅游": "文旅", "旅游": "文旅",
        "内容": "数字内容", "游戏": "数字内容", "政治": "时政", "政策": "时政",
        "企业": "企业商业", "商业": "企业商业", "地方": "地方治理", "热点": "社会热点",
    }
    for k, v in alias.items():
        if k in text:
            return v
    return "社会热点"


def _build_prompt(articles: List[Dict]) -> str:
    """构造聚合 prompt。articles 为带 idx 的文章列表。"""
    lines = []
    for a in articles:
        summary = (a.get("summary") or "").strip().replace("\n", " ")
        if len(summary) > 160:
            summary = summary[:160] + "…"
        lines.append(f"[{a['idx']}] 《{a['title']}》（{a.get('source','')}）：{summary}")
    article_block = "\n".join(lines)
    n = len(articles)

    # 用手动字符串拼接，彻底避开 .format() 的引号转义问题
    prompt = (
        "Below is " + str(n) + " news articles collected in one day (each with a unique index):\n"
        "\n" + article_block + "\n\n"
        "You are a senior research topic planner at Tencent Research Institute. "
        "From these articles, select the most valuable ones and synthesize them into "
        "**exactly 10** research topic clues.\n\n"
        "Requirements:\n"
        "1. Exactly 10 topics, no more no less. Each topic aggregates 1+ related articles.\n"
        "2. Topic logic: potential research angle, NOT news category. "
        "e.g. multiple AI talent + business model articles -> 'AI Employment Impact Research'.\n"
        "3. Each topic output:\n"
        "   - title: one-sentence topic title (15-30 chars, no brackets)\n"
        "   - summary: 300-500 chars, objective, high info density\n"
        "   - topics: 3-5 extensible research tags (4-12 chars each)\n"
        "   - category: EXACTLY ONE classification label chosen from this fixed set "
        "(use the Chinese label as-is): "
        "[\"AI\",\"科技\",\"金融\",\"消费民生\",\"文旅\",\"数字内容\",\"时政\",\"企业商业\",\"地方治理\",\"社会热点\"]. "
        "Pick the single best-fit label for cross-issue filtering.\n"
        "   - source_indices: array of article indices (at least 1)\n"
        "4. **[CRITICAL]** You MUST try to cover these categories each day. "
        "Do NOT skip a category if there are relevant articles!\n"
        "   - Culture/Tourism (文旅): 1 topic - cultural consumption, city tourism, "
        "intangible heritage, experience economy, cultural events\n"
        "   - Local Governance (地方政府): 1 topic - local government policies, "
        "regional competition, city development, local innovation, inter-city competition\n"
        "   - Digital Content (数字内容): 1 topic - games, film/TV dramas, "
        "short videos, web novels, anime, digital entertainment, content platforms\n"
        "   - AI-related (AI相关): 2 topics - AI technology, industry trends, "
        "AI governance, AI employment impact, AI ethics, AI applications\n"
        "   - Current Politics (时政): 1 topic - national policy, diplomacy, "
        "major political events, international relations, geopolitical shifts\n"
        "   - Finance (金融): 1 topic - capital markets, monetary policy, "
        "macro economic data, financial regulation, investment trends\n"
        "   - Consumer Economy/Livelihood (消费经济民生): 1 topic - consumption trends, "
        "employment issues, housing, population, consumer rights, social welfare\n"
        "   - Enterprise/Business (企业商业): 1 topic - corporate management, "
        "business dynamics, industry landscape, company strategies, market competition\n"
        "   - Hot Topics (热点议题): 1 topic - social hotspots, public opinion events, "
        "viral topics, cross-cutting social issues, trending discussions\n"
        "5. Before finalizing, check if you missed any category where relevant articles exist. "
        "If yes, adjust your topics to include that category.\n"
        "6. Prefer topics related to AI, tech industry, digital economy, platform governance, "
        "social change, policy regulation.\n"
        "7. Topics should be mutually exclusive; one article -> one topic.\n"
        "8. Rank 10 topics by importance/research value (highest first).\n\n"
        "Return ONLY the following JSON (no extra text, no markdown code blocks):\n"
        '{"clues": [\n'
        '  {"title": "topic title", "summary": "...", "topics": ["tag1","tag2"], "category": "AI", "source_indices": [1,5,8]},\n'
        "  ... exactly 10 ...\n"
        "]}"
    )
    return prompt


def _call_api_high_tokens(client: DeepSeekClient, system_prompt: str,
                          user_prompt: str) -> Optional[str]:
    """用更高的 max_tokens 直接调用 DeepSeek（复用 client 的密钥/地址/模型）。

    聚合输出较长，skill 内置的 2000 token 上限会截断 JSON，故此处单独发请求。
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {client.api_key}",
    }
    data = {
        "model": client.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.4,
        "max_tokens": AGG_MAX_TOKENS,
    }
    last_exc = None
    for attempt in range(AGG_MAX_RETRIES):
        try:
            resp = requests.post(client.api_base, headers=headers, json=data,
                                 timeout=AGG_TIMEOUT)
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                raise requests.HTTPError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            last_exc = e
            if attempt < AGG_MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    print(f"  [错误] API 调用失败: {last_exc}")
    return None


def _repair_truncated_json(text: str) -> Optional[Dict]:
    """修复被截断的 clues JSON：丢弃最后一个不完整的对象，补齐括号。"""
    if not text:
        return None
    # 定位到 "clues": [ 之后，逐个截取完整的 { ... } 对象
    start = text.find('"clues"')
    if start < 0:
        return None
    arr_start = text.find('[', start)
    if arr_start < 0:
        return None
    objs = []
    depth = 0
    in_str = False
    esc = False
    cur = ""
    for ch in text[arr_start + 1:]:
        if esc:
            cur += ch
            esc = False
            continue
        if ch == '\\':
            cur += ch
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            cur += ch
            continue
        if in_str:
            cur += ch
            continue
        if ch == '{':
            depth += 1
            cur += ch
        elif ch == '}':
            depth -= 1
            cur += ch
            if depth == 0:
                # 一个完整对象结束
                try:
                    objs.append(json.loads(cur.strip().lstrip(',').strip()))
                except Exception:
                    pass
                cur = ""
        elif ch == ']' and depth == 0:
            break
        else:
            cur += ch
    if objs:
        return {"clues": objs}
    return None


def _parse_json_response(text: str) -> Optional[Dict]:
    """从模型返回中稳健解析 JSON。"""
    if not text:
        return None
    # 去除可能的 ```json ``` 包裹
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except Exception:
        pass
    # 尝试截取第一个 { 到最后一个 }
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    # 兜底：修复被截断的 JSON
    return _repair_truncated_json(text)


def aggregate_issue(parsed_issue: Dict, client: DeepSeekClient,
                    target_clues: int = 10) -> Optional[Dict]:
    """对单期解析结果做 AI 课题聚合，返回写作线索结构。"""
    articles = parsed_issue.get("articles", [])
    if not articles:
        return None

    # 给文章编号（从 1 开始）
    indexed = []
    for i, a in enumerate(articles, start=1):
        indexed.append({
            "idx": i,
            "title": a.get("title", ""),
            "source": a.get("source", ""),
            "summary": a.get("summary", ""),
            "links": a.get("links", []),
        })

    prompt = _build_prompt(indexed)
    resp = _call_api_high_tokens(client, SYSTEM_PROMPT, prompt)
    if resp is None:
        return None

    data = _parse_json_response(resp)
    if not data or "clues" not in data:
        print("  [错误] 无法解析 AI 返回的 JSON")
        print("  原始返回片段:", (resp or "")[:300])
        return None

    raw_clues = data["clues"]
    idx_map = {a["idx"]: a for a in indexed}

    clues = []
    used_indices = set()
    for ci, rc in enumerate(raw_clues, start=1):
        src_idxs = rc.get("source_indices", []) or []
        sources = []
        seen_urls = set()
        for si in src_idxs:
            art = idx_map.get(si)
            if not art:
                continue
            used_indices.add(si)
            # 一篇文章可能有多个原文链接（整合文章）
            for lk in art.get("links", []):
                url = lk.get("url", "")
                key = url or lk.get("title", "")
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                sources.append({
                    "title": lk.get("title", art["title"]),
                    "source": lk.get("source", art["source"]),
                    "url": url,
                })
            if not art.get("links"):
                sources.append({
                    "title": art["title"],
                    "source": art["source"],
                    "url": "",
                })
        clues.append({
            "index": ci,
            "title": (rc.get("title") or "").strip(),
            "summary": (rc.get("summary") or "").strip(),
            "category": _norm_category(rc.get("category")),
            "topics": [t.strip() for t in (rc.get("topics") or []) if t.strip()],
            "sources": sources,
        })

    return {
        "date": parsed_issue.get("date", ""),
        "weekday": parsed_issue.get("weekday", ""),
        "stats": {
            "total": len(articles),
            "selected": len(used_indices),
            "clues": len(clues),
        },
        "clues": clues,
    }


if __name__ == "__main__":
    # 单文件联调：解析 + 聚合 一期
    from docx_parser import parse_docx

    _ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    docx_path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(_ROOT_DIR, "每日资讯", "2026_06", "每日资讯_2026-06-22", "每日资讯_2026-06-22.docx")

    # 获取 API Key（复用 skill 的授权流程）
    import auth  # noqa: E402
    api_key = auth.get_api_key()
    if not api_key:
        print("未获取到 API Key")
        sys.exit(1)

    client = DeepSeekClient(api_key)
    parsed = parse_docx(docx_path)
    print(f"解析: {parsed['date']} 文章数 {parsed['article_count']}")
    result = aggregate_issue(parsed, client)
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])
        print("...")
        print(f"\n共生成 {len(result['clues'])} 条线索, "
              f"引用 {result['stats']['selected']} 篇资讯")
