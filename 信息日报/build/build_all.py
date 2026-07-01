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


def build_search_index(all_data: list, manifest_issues: list) -> None:
    """生成 search-index.json：把所有期次的线索摊平，供前端全局搜索/标签筛选。"""
    entries = []
    cat_counter = {}
    for issue in all_data:
        date = issue.get("date", "")
        weekday = issue.get("weekday", "")
        for clue in issue.get("clues", []):
            cat = clue.get("category") or "社会热点"
            cat_counter[cat] = cat_counter.get(cat, 0) + 1
            summary = clue.get("summary") or ""
            entries.append({
                "date": date,
                "weekday": weekday,
                "index": clue.get("index"),
                "title": clue.get("title", ""),
                "category": cat,
                "topics": clue.get("topics", []),
                "excerpt": summary[:80],
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
_STOP_CHARS = set("的了和与及或为在中对上下年月日一二三四五六七八九十")


def _bigrams(text: str) -> set:
    """标题字符二元组集合（去空白），用于中文短文本相似度。"""
    t = re.sub(r"\s+", "", text or "")
    t = re.sub(r"[，。、；：！？（）()《》\"'”“·\-—]", "", t)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _clue_similarity(a: dict, b: dict) -> float:
    """两条线索的主题相似度：标题字符二元组 Jaccard + 共享标签加成 + 同类加成。"""
    ba, bb = _bigrams(a["title"]), _bigrams(b["title"])
    if not ba or not bb:
        jac = 0.0
    else:
        inter = len(ba & bb)
        union = len(ba | bb)
        jac = inter / union if union else 0.0
    # 共享 topic 标签
    ta = {t for t in (a.get("topics") or [])}
    tb = {t for t in (b.get("topics") or [])}
    shared_tags = len(ta & tb)
    tag_bonus = min(0.3, 0.15 * shared_tags)
    # 同分类小幅加成
    cat_bonus = 0.08 if a.get("category") and a.get("category") == b.get("category") else 0.0
    return jac + tag_bonus + cat_bonus


class _UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def build_timelines(all_data: list, threshold: float = 0.34) -> None:
    """把多期同主题线索用相似度聚合成「追踪线」，写入 timelines.json。

    仅保留跨 >=2 个不同日期的主题（真正可追踪的），按最近更新与热度排序。
    """
    nodes = []
    for issue in all_data:
        date = issue.get("date", "")
        for clue in issue.get("clues", []):
            nodes.append({
                "date": date,
                "index": clue.get("index"),
                "title": clue.get("title", ""),
                "summary": clue.get("summary", ""),
                "category": clue.get("category") or "社会热点",
                "topics": clue.get("topics", []),
            })

    n = len(nodes)
    uf = _UF(n)
    # O(n^2) 相似度连边；线索总量有限（每期10条），可接受
    for i in range(n):
        for j in range(i + 1, n):
            if nodes[i]["date"] == nodes[j]["date"]:
                continue  # 同一期不连
            if _clue_similarity(nodes[i], nodes[j]) >= threshold:
                uf.union(i, j)

    clusters = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    timelines = []
    for members in clusters.values():
        dates = {nodes[m]["date"] for m in members}
        if len(dates) < 2:
            continue  # 只出现在单期，不算追踪线
        entries = sorted(
            [{
                "date": nodes[m]["date"],
                "index": nodes[m]["index"],
                "title": nodes[m]["title"],
                "excerpt": (nodes[m]["summary"] or "")[:70],
            } for m in members],
            key=lambda e: e["date"], reverse=True,
        )
        # 代表标题取最新一期；标签取并集
        tag_set = []
        for m in members:
            for t in nodes[m]["topics"]:
                if t not in tag_set:
                    tag_set.append(t)
        # 代表分类取众数
        cats = [nodes[m]["category"] for m in members]
        rep_cat = max(set(cats), key=cats.count)
        timelines.append({
            "title": entries[0]["title"],
            "category": rep_cat,
            "tags": tag_set[:6],
            "count": len(entries),
            "date_start": min(dates),
            "date_end": max(dates),
            "entries": entries,
        })

    # 排序：先按最近更新日期，再按跨越期数
    timelines.sort(key=lambda t: (t["date_end"], t["count"]), reverse=True)
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
