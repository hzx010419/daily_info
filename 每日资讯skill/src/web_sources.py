#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
网站资讯源采集（监控源3：中文 AI 媒体 + 社区聚合站）

抓取方法照搬 ai-news-radar/scripts/update_news.py，把这些"非公众号"网站
（AIbase / AI HOT / TopHub / NewsNow / TechURLs / Buzzing / AI HubToday 等）
的**今日**更新，归一化为统一条目，注入到「每日资讯skill」现有管线，
从而复用现有的 AI 广告过滤、MECE 分类、去重、限长摘要与 docx 生成。

设计要点：
  1. 每个源独立 try/except，单源失败不影响其他源。
  2. 统一输出 dict：{source, title, url, published_at(datetime|None), content}
     · published_at 为 naive 本地时间（与 main.py 的时间基准一致）
     · 热榜类站点（无逐条时间）published_at=None，由调用方按"当日"处理
  3. 时间过滤在 collect_web_items() 内完成：仅保留 one_day_ago~now 的条目；
     无时间戳的热榜条目视为"今日"。
  4. 每源条数上限 max_items，控制注入体量与后续 AI 调用成本。

对外只暴露 collect_web_items(now, one_day_ago) -> List[dict]。
"""

import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

try:
    from bs4 import BeautifulSoup  # 网页 HTML 解析（AIbase/TopHub/TechURLs）
    _HAS_BS4 = True
except Exception:  # pragma: no cover
    _HAS_BS4 = False

try:
    import xml.etree.ElementTree as ET  # RSS 解析（AI HubToday）
except Exception:  # pragma: no cover
    ET = None


BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# AI HOT 卡片分数门槛（与 ai-news-radar 一致，只保留高分条目）
AIHOT_MIN_SCORE = 60

# ============================================================================
# 监控源开关与配额（监控源3的网站清单）
#   enabled=False 可临时关闭某源；max_items 控制每源注入上限。
# ============================================================================
WEB_SOURCES_CONFIG = {
    "aibase":     {"enabled": True,  "max_items": 15, "name": "AIbase"},
    "aihot":      {"enabled": True,  "max_items": 20, "name": "AI HOT"},
    "buzzing":    {"enabled": True,  "max_items": 12, "name": "Buzzing"},
    "aihubtoday": {"enabled": True,  "max_items": 12, "name": "AI HubToday"},
    "techurls":   {"enabled": True,  "max_items": 12, "name": "TechURLs"},
    "tophub":     {"enabled": True,  "max_items": 15, "name": "TopHub"},
    "newsnow":    {"enabled": True,  "max_items": 15, "name": "NewsNow"},
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    return s


def _parse_dt(value, now: datetime):
    """把多种时间表示解析为 naive 本地 datetime；解析失败返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text:
        return None

    # 中文口语日期
    if "今天" in text or "刚刚" in text or "分钟前" in text:
        m0 = re.search(r"(\d+)\s*分钟前", text)
        return now - timedelta(minutes=int(m0.group(1))) if m0 else now
    if "前天" in text:
        return now - timedelta(days=2)
    if "昨天" in text:
        return now - timedelta(days=1)

    # 相对时间：如 "3小时前" / "10分钟前"
    m = re.search(r"(\d+)\s*(分钟|小时|天|min|hour|day)", text, re.I)
    if "前" in text or "ago" in text.lower():
        if m:
            n = int(m.group(1))
            unit = m.group(2).lower()
            if unit in ("分钟", "min"):
                return now - timedelta(minutes=n)
            if unit in ("小时", "hour"):
                return now - timedelta(hours=n)
            if unit in ("天", "day"):
                return now - timedelta(days=n)
        return now

    # ISO / 常见绝对格式
    iso = text.replace("Z", "+00:00")
    for fmt in (None,):  # 先试 fromisoformat
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y/%m/%d %H:%M", "%Y/%m/%d", "%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is not None:
                dt = dt.astimezone().replace(tzinfo=None)
            return dt
        except Exception:
            continue
    return None


def _item(source, title, url, published_at, content=""):
    title = (title or "").strip()
    url = (url or "").strip()
    if not title or not url:
        return None
    return {
        "source": source,
        "title": title,
        "url": url,
        "published_at": published_at,
        "content": (content or "").strip(),
    }


# ---------------------------------------------------------------------------
# 各站点抓取器（方法照搬 ai-news-radar）
# ---------------------------------------------------------------------------
def fetch_aibase(session, now):
    """AIbase：抓 https://www.aibase.com/zh/news 网页，解析 a[href^='/news/'] 的 h3 标题与时间。"""
    if not _HAS_BS4:
        return []
    r = session.get("https://www.aibase.com/zh/news", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a[href^='/news/']"):
        h3 = a.select_one("h3")
        if not h3:
            continue
        title = h3.get_text(" ", strip=True)
        href = (a.get("href") or "").strip()
        if not title or not href:
            continue
        time_text = ""
        time_tag = a.select_one("div.text-sm.text-gray-400 span") or a.select_one("span.text-gray-400")
        if time_tag:
            time_text = time_tag.get_text(" ", strip=True)
        out.append(_item("AIbase", title, urljoin("https://www.aibase.com", href),
                         _parse_dt(time_text, now)))
    return [x for x in out if x]


def fetch_aihot(session, now):
    """AI HOT：读公开 JSON API，仅保留卡片分数 >= 60 的条目。"""
    r = session.get(
        "https://aihot.virxact.com/api/public/items",
        params={"mode": "selected", "take": 100},
        timeout=30,
        headers={"Accept": "application/json"},
    )
    r.raise_for_status()
    payload = r.json()
    raw_items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(raw_items, list):
        return []
    out = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        try:
            score = float(entry.get("score"))
        except (TypeError, ValueError):
            continue
        if score < AIHOT_MIN_SCORE:
            continue
        title = (entry.get("title") or entry.get("title_en") or "").strip()
        url = (entry.get("url") or "").strip()
        published = _parse_dt(entry.get("publishedAt") or entry.get("published_at"), now)
        source = (entry.get("source") or "AI HOT").strip()
        item = _item(f"AI HOT·{source}" if source and source != "AI HOT" else "AI HOT",
                     title, url, published, entry.get("summary") or "")
        if item:
            out.append(item)
    return out


def fetch_buzzing(session, now):
    """Buzzing：读 https://www.buzzing.cc/feed.json（JSON Feed）。"""
    r = session.get("https://www.buzzing.cc/feed.json", timeout=30)
    r.raise_for_status()
    payload = r.json()
    out = []
    for it in payload.get("items", []):
        title = it.get("title") or ""
        url = it.get("url") or it.get("external_url") or ""
        published = _parse_dt(it.get("date_published") or it.get("date_modified"), now)
        content = it.get("summary") or it.get("content_text") or ""
        item = _item("Buzzing", title, url, published, content)
        if item:
            out.append(item)
    return out


def fetch_aihubtoday(session, now):
    """AI HubToday：读 RSS。"""
    if ET is None:
        return []
    for feed_url in ("https://www.aihub.today/feed", "https://aihub.today/feed",
                     "https://www.aihubtoday.com/feed"):
        try:
            r = session.get(feed_url, timeout=30)
            r.raise_for_status()
            return _parse_rss(r.content, "AI HubToday", now)
        except Exception:
            continue
    return []


def fetch_techurls(session, now):
    """TechURLs：抓 https://techurls.com/ 科技头条聚合网页。"""
    if not _HAS_BS4:
        return []
    r = session.get("https://techurls.com/", timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for a in soup.select("a[href^='http']"):
        title = a.get_text(" ", strip=True)
        href = (a.get("href") or "").strip()
        if not title or len(title) < 8 or "techurls.com" in href:
            continue
        out.append(_item("TechURLs", title, href, now))  # 聚合头条，视为当日
    return [x for x in out if x]


def fetch_tophub(session, now):
    """TopHub 今日热榜：抓 https://tophub.today/ 聚合热榜（视为当日）。"""
    if not _HAS_BS4:
        return []
    r = session.get("https://tophub.today/", timeout=30)
    r.raise_for_status()
    html = r.content.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.select("a[href^='/x/'], a.link, div.cc-cd-cb-l a"):
        title = a.get_text(" ", strip=True)
        href = (a.get("href") or "").strip()
        if not title or len(title) < 6:
            continue
        # tophub 内部链接指向聚合详情，保留可用外链
        full = urljoin("https://tophub.today", href)
        out.append(_item("TopHub", title, full, now))
    return [x for x in out if x]


def fetch_newsnow(session, now):
    """NewsNow：抓首页热榜聚合（视为当日）。尽量走公开接口，失败则跳过。"""
    base = "https://newsnow.busiyi.world"
    out = []
    try:
        # 公开聚合接口（部分部署提供）；失败进入兜底
        r = session.get(f"{base}/api/s/entire", timeout=20)
        if r.status_code == 200:
            data = r.json()
            blocks = data if isinstance(data, list) else data.get("data", [])
            for blk in blocks or []:
                for it in (blk.get("items") or []):
                    title = it.get("title") or ""
                    url = it.get("url") or it.get("mobileUrl") or ""
                    item = _item("NewsNow", title, url, now)
                    if item:
                        out.append(item)
    except Exception:
        pass
    return out


# 抓取器注册表（key 与 WEB_SOURCES_CONFIG 对应）
_FETCHERS = {
    "aibase": fetch_aibase,
    "aihot": fetch_aihot,
    "buzzing": fetch_buzzing,
    "aihubtoday": fetch_aihubtoday,
    "techurls": fetch_techurls,
    "tophub": fetch_tophub,
    "newsnow": fetch_newsnow,
}


def _parse_rss(content: bytes, source_name: str, now: datetime):
    """极简 RSS/Atom 解析（不依赖 feedparser）。"""
    out = []
    try:
        root = ET.fromstring(content)
    except Exception:
        return out
    # RSS: channel/item ; Atom: entry
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for it in items:
        def _find(tags):
            for t in tags:
                el = it.find(t)
                if el is not None and (el.text or el.get("href")):
                    return el.text or el.get("href")
            return ""
        title = _find(["title", "{http://www.w3.org/2005/Atom}title"])
        link = _find(["link", "{http://www.w3.org/2005/Atom}link", "guid"])
        pub = _find(["pubDate", "published", "updated",
                     "{http://www.w3.org/2005/Atom}updated"])
        desc = _find(["description", "summary",
                      "{http://www.w3.org/2005/Atom}summary"])
        item = _item(source_name, title, link, _parse_dt(pub, now), desc)
        if item:
            out.append(item)
    return out


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------
def collect_web_items(now: datetime, one_day_ago: datetime):
    """采集所有已启用的网站源，返回**今日**（one_day_ago~now）的归一化条目列表。

    Args:
        now: 当前本地时间（naive）
        one_day_ago: 时间下界（naive），仅保留此后条目

    Returns:
        List[dict]  每个 dict 含 source/title/url/published_at/content
    """
    session = _new_session()
    collected = []
    seen_urls = set()

    for key, cfg in WEB_SOURCES_CONFIG.items():
        if not cfg.get("enabled"):
            continue
        fetcher = _FETCHERS.get(key)
        if fetcher is None:
            continue
        name = cfg.get("name", key)
        try:
            raw = fetcher(session, now) or []
        except Exception as e:
            logger.warning(f"[网站源] {name} 抓取失败: {e}")
            continue

        kept = []
        for it in raw:
            if not it:
                continue
            pub = it.get("published_at")
            # 时间过滤：有时间戳的按 24h 窗口筛；无时间戳（热榜）视为今日
            if pub is not None and pub < one_day_ago:
                continue
            if pub is None:
                it["published_at"] = now
            url = it["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            kept.append(it)
            if len(kept) >= cfg.get("max_items", 15):
                break

        logger.info(f"[网站源] {name}: 保留 {len(kept)} 条今日资讯")
        collected.extend(kept)

    logger.info(f"[网站源] 合计注入 {len(collected)} 条今日资讯（来自 {sum(1 for c in WEB_SOURCES_CONFIG.values() if c.get('enabled'))} 个网站源）")
    return collected


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _now = datetime.now()
    items = collect_web_items(_now, _now - timedelta(days=1))
    print(f"共 {len(items)} 条")
    for x in items[:20]:
        print(f"  [{x['source']}] {x['title'][:40]} | {x['published_at']} | {x['url'][:60]}")
