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
    manifest_issues = [m for m in manifest_issues if m]
    # 去重（同日期保留一条）
    seen = {}
    for m in manifest_issues:
        seen[m["date"]] = m
    manifest_issues = sorted(seen.values(), key=lambda x: x["date"], reverse=True)

    manifest = {
        "title": "材料选题日报",
        "subtitle": "每日写作线索，按日期归档",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "issues": manifest_issues,
    }
    with open(os.path.join(_WEB_DATA, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n完成！成功 {success_count} 期，manifest 含 {len(manifest_issues)} 期")
    print(f"数据输出目录: {_WEB_DATA}")
    return True


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
