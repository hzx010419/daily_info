#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
批量构建「写作线索日报」网页数据

流程：
  1. 扫描「每日资讯/」目录下所有期次的 docx
  2. 逐期解析 + AI 聚合为 10 条写作线索
  3. 输出 web/data/{date}.json（每期数据）
  4. 输出 web/data/manifest.json（往期归档索引，供首页使用）

用法：
  python build_all.py                # 增量：已生成过的期次跳过
  python build_all.py --force        # 全量重建
  python build_all.py --date 2026-06-22   # 只重建指定日期
  python build_all.py --limit 5      # 只处理最近 5 期（调试用）
"""

import os
import sys
import json
import glob
import re
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx_parser import parse_docx
from aggregate import aggregate_issue

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))          # 自动爬取skill/
_NEWS_DIR = os.path.join(_ROOT, "每日资讯")
_WEB_DATA = os.path.join(os.path.dirname(_THIS), "web", "data")
_DOCS_DIR = os.path.join(_WEB_DATA, "docs")            # docx 文件存放目录


def find_all_docx() -> list:
    """返回所有期次 docx 路径，按日期升序。

    兼容两种目录结构：
      · 嵌套式（较新）：每日资讯/2026_06/每日资讯_2026-06-22/每日资讯_2026-06-22.docx
      · 扁平式（较早）：每日资讯/2026_04/每日资讯_2026-04-01.docx
    """
    patterns = [
        os.path.join(_NEWS_DIR, "*", "每日资讯_*", "每日资讯_*.docx"),  # 嵌套
        os.path.join(_NEWS_DIR, "*", "每日资讯_*.docx"),                # 扁平
    ]
    files = set()
    for pat in patterns:
        for f in glob.glob(pat):
            if "~$" in f:
                continue
            files.add(f)
    # 按文件名中的日期升序
    def _date_key(p):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(p))
        return m.group(1) if m else os.path.basename(p)
    return sorted(files, key=_date_key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="全量重建")
    ap.add_argument("--date", type=str, default=None, help="只重建指定日期 YYYY-MM-DD")
    ap.add_argument("--limit", type=int, default=0, help="只处理最近 N 期")
    args = ap.parse_args()

    os.makedirs(_WEB_DATA, exist_ok=True)
    os.makedirs(_DOCS_DIR, exist_ok=True)

    # 获取 API Key（复用 skill 授权）
    import auth
    api_key = auth.get_api_key()
    if not api_key:
        print("[错误] 未获取到 API Key")
        return False
    from ai_client import DeepSeekClient
    client = DeepSeekClient(api_key)

    files = find_all_docx()
    if args.date:
        files = [f for f in files if args.date in f]
    if args.limit > 0:
        files = files[-args.limit:]

    print(f"发现 {len(files)} 期资讯文档")

    # 先加载已有的 manifest，保证历史数据不丢失
    manifest_path = os.path.join(_WEB_DATA, "manifest.json")
    old_manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                for item in old_data.get("issues", []):
                    old_manifest[item["date"]] = item
            print(f"  [信息] 已加载历史 manifest，共 {len(old_manifest)} 期")
        except Exception:
            pass

    manifest_issues = []
    success_count = 0

    for docx_path in files:
        date_match = os.path.basename(docx_path).replace("每日资讯_", "").replace(".docx", "")
        out_path = os.path.join(_WEB_DATA, f"{date_match}.json")

        # 增量跳过
        if not args.force and os.path.exists(out_path):
            try:
                with open(out_path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                manifest_issues.append(_manifest_entry(existing))
                print(f"  [跳过] {date_match}（已存在）")
                success_count += 1
                continue
            except Exception:
                pass

        print(f"  [处理] {date_match} ...")
        parsed = parse_docx(docx_path)
        if not parsed or not parsed.get("articles"):
            print(f"    [警告] {date_match} 解析为空，跳过")
            continue

        result = aggregate_issue(parsed, client)
        if not result:
            print(f"    [失败] {date_match} 聚合失败，跳过")
            continue

        # 复制 docx 文件到 web/data/docs/
        import shutil
        docx_basename = os.path.basename(docx_path)
        docx_dest = os.path.join(_DOCS_DIR, docx_basename)
        try:
            shutil.copy2(docx_path, docx_dest)
        except Exception as e:
            print(f"    [警告] 复制 docx 文件失败: {e}")

        # 添加 docx 下载链接（相对路径，供网页使用）
        # 注意：网页中 JSON 在 data/ 目录，但页面在 web/ 根目录，
        # 所以相对路径需要加 data/ 前缀
        result["docx_url"] = "data/docs/" + docx_basename
        result["docx_name"] = docx_basename

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        manifest_issues.append(_manifest_entry(result))
        success_count += 1
        print(f"    [完成] {date_match} -> 10 条线索, 引用 {result['stats']['selected']} 篇")

    # 写 manifest（按日期降序）
    # 合并历史数据 + 新数据，保证不丢失
    all_issues = {}
    # 先加入历史数据
    for date, item in old_manifest.items():
        all_issues[date] = item
    # 再覆盖新数据（如果当天有更新）
    for m in manifest_issues:
        all_issues[m["date"]] = m
    # 转成列表，按日期降序
    manifest_issues = sorted(all_issues.values(), key=lambda x: x["date"], reverse=True)

    manifest = {
        "title": "信息选题参考",
        "subtitle": "每日热点信息，按日期归档",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "issues": manifest_issues,
    }
    with open(os.path.join(_WEB_DATA, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # 读取全部期次的完整数据，生成「全局搜索索引」与「跨期追踪线」
    all_data = _load_all_issue_data()
    build_search_index(all_data, manifest_issues)
    build_timelines(all_data)

    print(f"\n完成！成功 {success_count} 期，manifest 含 {len(manifest_issues)} 期")
    print(f"数据输出目录: {_WEB_DATA}")
    return True


def _load_all_issue_data() -> list:
    """读取 web/data 下全部期次 {date}.json（不含 manifest/索引/时间线）。"""
    skip = {"manifest.json", "search-index.json", "timelines.json"}
    out = []
    for path in glob.glob(os.path.join(_WEB_DATA, "*.json")):
        name = os.path.basename(path)
        if name in skip:
            continue
        if not re.match(r"\d{4}-\d{2}-\d{2}\.json$", name):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                out.append(json.load(f))
        except Exception:
            continue
    out.sort(key=lambda d: d.get("date", ""), reverse=True)
    return out


# 分类关键词兜底：历史线索没有 category 时按标题关键词推断，
# 保证「全部线索/追踪线」分类在预览与 CI 中一致、可着色（不依赖 AI 重跑）。
_CATEGORY_RULES = [
    ("AI", ["AI", "人工智能", "大模型", "模型", "算力", "智能体", "GPT", "OpenAI",
            "机器人", "算法", "Agent", "生成式", "多模态"]),
    ("金融", ["股", "金融", "银行", "基金", "投资", "利率", "美联储", "货币", "债",
             "财报", "市值", "融资", "A股", "汇率", "IPO", "证券"]),
    ("科技", ["芯片", "半导体", "苹果", "华为", "科技", "软件", "互联网", "数据",
             "5G", "操作系统", "自动驾驶", "新能源车"]),
    ("消费民生", ["消费", "就业", "房价", "楼市", "民生", "养老", "收入", "物价",
                "零售", "医保", "社保", "裁员", "劳动力", "人口", "教育", "医疗"]),
    ("文旅", ["旅游", "文旅", "景区", "演唱会", "博物馆", "文化遗产", "出游", "票房", "旅客"]),
    ("数字内容", ["游戏", "影视", "短视频", "动漫", "直播", "综艺", "网文", "电竞", "剧集"]),
    ("时政", ["政策", "外交", "国务院", "监管", "峰会", "关税", "制裁", "博弈",
             "地缘", "冲突", "能源", "安全"]),
    ("企业商业", ["企业", "公司", "商业", "品牌", "上市", "CEO", "战略", "并购", "营收"]),
    ("地方治理", ["地方", "省", "区域", "县", "乡村", "政府债务", "政绩", "城市"]),
]


def _guess_category(text: str) -> str:
    t = text or ""
    for cat, kws in _CATEGORY_RULES:
        for k in kws:
            if k in t:
                return cat
    return "社会热点"


def build_search_index(all_data: list, manifest_issues: list) -> None:
    """生成 search-index.json：把所有期次的线索摊平，供前端全局搜索/标签筛选。"""
    entries = []
    cat_counter = {}
    for issue in all_data:
        date = issue.get("date", "")
        weekday = issue.get("weekday", "")
        for clue in issue.get("clues", []):
            cat = clue.get("category") or _guess_category(clue.get("title", "") + (clue.get("summary") or ""))
            cat_counter[cat] = cat_counter.get(cat, 0) + 1
            summary = clue.get("summary") or ""
            entries.append({
                "date": date,
                "weekday": weekday,
                "index": clue.get("index"),
                "title": clue.get("title", ""),
                "category": cat,
                "topics": clue.get("topics", []),
                "sources": len(clue.get("sources", [])),
                "excerpt": summary[:90],
            })
    index = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "categories": [
            {"name": k, "count": v}
            for k, v in sorted(cat_counter.items(), key=lambda x: -x[1])
        ],
        "total": len(entries),
        "entries": entries,
    }
    with open(os.path.join(_WEB_DATA, "search-index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"  [索引] search-index.json：{len(entries)} 条线索，{len(cat_counter)} 个分类")


# ---------- 跨期追踪线（同一主题多期串联） ----------
def _bigrams(text: str) -> set:
    """标题字符二元组集合（去空白/标点），用于中文短文本相似度。"""
    t = re.sub(r"\s+", "", text or "")
    t = re.sub(r"[，。、；：！？（）()《》\"'”“·\-—]", "", t)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


# 过于宽泛的词/二元组：作为"泛词"降权，不能仅凭它们把线索聚到一起
# （否则所有 AI 内容会因为共享「AI/人工智能/模型」被错误合并成一条巨型线）
_GENERIC_TOKENS = set([
    "AI", "ai", "人工智能", "智能", "模型", "大模", "模型", "型的", "技术", "科技",
    "发展", "行业", "产业", "中国", "美国", "全球", "国际", "企业", "公司", "市场",
    "经济", "政策", "研究", "影响", "趋势", "分析", "应用", "时代", "未来", "数字",
    "平台", "创新", "问题", "挑战", "机遇", "方向", "相关", "领域", "推动", "加速",
    "布局", "如何", "背后", "面临", "迎来", "开启", "重塑", "升级",
])


def _clue_tokens(node: dict):
    """返回 (全部 token 集, 具体 token 集)。
    token 来源：topic 标签（整词，语义最准）+ 标题字符二元组。
    泛词（_GENERIC_TOKENS）不计入"具体 token"。
    """
    tok, spec = set(), set()
    for tg in (node.get("topics") or []):
        t = re.sub(r"\s+", "", str(tg))
        if len(t) >= 2:
            tok.add(t)
            if t not in _GENERIC_TOKENS:
                spec.add(t)
    for bg in _bigrams(node.get("title", "")):
        tok.add(bg)
        if bg not in _GENERIC_TOKENS:
            spec.add(bg)
    return tok, spec


def _weighted_jaccard(a: set, b: set) -> float:
    """加权 Jaccard：泛词权重 0.15，具体词权重 1.0。"""
    if not a or not b:
        return 0.0
    def w(t):
        return 0.15 if t in _GENERIC_TOKENS else 1.0
    inter = a & b
    union = a | b
    si = sum(w(t) for t in inter)
    su = sum(w(t) for t in union)
    return si / su if su else 0.0


def build_timelines(all_data: list, sim_threshold: float = 0.34,
                    min_shared_specific: int = 2) -> None:
    """把多期同主题线索聚合成「追踪线」，写入 timelines.json。

    采用**锚点式贪心聚类**（而非并查集连边），从根本上避免链式膨胀：
      · 每条追踪线以其"第一条线索"为锚点；
      · 新线索要加入，必须与锚点共享 >= min_shared_specific 个「具体词」，
        且加权相似度 >= sim_threshold；
      · 泛词（AI/人工智能/模型/中国…）被降权，无法仅凭它们把内容黏在一起，
        因此 AI 内部会按 ai金融 / ai就业 / ai伦理 等具体方向自然分开。
    仅保留跨 >=2 个不同日期的主题。
    """
    nodes = []
    for issue in all_data:
        date = issue.get("date", "")
        for clue in issue.get("clues", []):
            nd = {
                "date": date,
                "index": clue.get("index"),
                "title": clue.get("title", ""),
                "summary": clue.get("summary", ""),
                "category": clue.get("category") or _guess_category(clue.get("title", "") + (clue.get("summary") or "")),
                "topics": clue.get("topics", []),
            }
            nd["_tok"], nd["_spec"] = _clue_tokens(nd)
            nodes.append(nd)

    # 按日期升序，保证"锚点"是该主题最早出现的那条
    nodes.sort(key=lambda x: (x["date"], x["index"] or 0))

    clusters = []  # {anchor_tok, anchor_spec, members:[node...]}
    MAX_MEMBERS = 30  # 安全上限，超出视为泛主题，丢弃
    for nd in nodes:
        best, best_sim = None, 0.0
        for cl in clusters:
            if len(cl["members"]) >= MAX_MEMBERS:
                continue
            shared = nd["_spec"] & cl["anchor_spec"]
            if len(shared) < min_shared_specific:
                continue
            sim = _weighted_jaccard(nd["_tok"], cl["anchor_tok"])
            if sim >= sim_threshold and sim > best_sim:
                best, best_sim = cl, sim
        if best is not None:
            best["members"].append(nd)
        else:
            clusters.append({
                "anchor_tok": set(nd["_tok"]),
                "anchor_spec": set(nd["_spec"]),
                "members": [nd],
            })

    timelines = []
    for cl in clusters:
        members = cl["members"]
        dates = sorted({m["date"] for m in members})
        if len(dates) < 2:
            continue
        if len(members) > MAX_MEMBERS:
            continue
        entries = sorted(
            [{
                "date": m["date"],
                "index": m["index"],
                "title": m["title"],
                "excerpt": (m["summary"] or "")[:70],
            } for m in members],
            key=lambda e: (e["date"], e["index"] or 0), reverse=True,
        )
        # 标签：优先共享标签，再补充；分类取众数
        tag_set = []
        for m in members:
            for t in (m["topics"] or []):
                if t not in tag_set:
                    tag_set.append(t)
        cats = [m["category"] for m in members]
        rep_cat = max(set(cats), key=cats.count)
        timelines.append({
            "title": entries[0]["title"],
            "category": rep_cat,
            "tags": tag_set[:6],
            "issues": len(dates),          # 跨越的不同日期数（真正的"期数"）
            "count": len(entries),         # 线索条数
            "date_start": dates[0],
            "date_end": dates[-1],
            "entries": entries,
        })

    # 排序：先按最近更新，再按跨越期数
    timelines.sort(key=lambda t: (t["date_end"], t["issues"], t["count"]), reverse=True)
    for i, t in enumerate(timelines, 1):
        t["id"] = i

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(timelines),
        "timelines": timelines,
    }
    with open(os.path.join(_WEB_DATA, "timelines.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  [追踪线] timelines.json：{len(timelines)} 条跨期主题线")


def _manifest_entry(issue: dict) -> dict:
    """从一期数据提取首页归档条目。"""
    if not issue or not issue.get("clues"):
        return None
    headline = issue["clues"][0]["title"] if issue["clues"] else ""
    return {
        "date": issue.get("date", ""),
        "weekday": issue.get("weekday", ""),
        "clue_count": len(issue.get("clues", [])),
        "headline": headline,
    }


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
