"""
LLM・AIエージェント動向収集モジュール（ai_dev カテゴリ）

2つのパスで「全ソース横断」収集する:
  Pass A: コーディングAI ツール・LLM ベンダーの公式アップデート（changelog/release/blog）RSS
          → settings.ai_dev_rss_feeds（Claude Code / Codex / Cursor / Copilot / Mistral / HF / DeepMind）
  Pass B: LLM/エージェント/コーディングAI の性能・ベンチマーク記事
          → settings.ai_dev_news_feeds をキーワード（ai_dev_filter_keywords）でフィルタ

industry.py / industry_news.py のパターンを踏襲。要約は "industry" リテラルで行う想定。
"""

import asyncio
import hashlib
import logging
import time
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser

import feedparser
import httpx

from app.config import settings
from app.schemas import ArticleItem

logger = logging.getLogger(__name__)


async def collect_ai_dev(target_date: date | None = None) -> list[ArticleItem]:
    """公式アップデート + キーワード該当ニュースを収集し、id で重複除去して返す。"""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    official = await _collect_official(target_date)
    news = await _collect_news(target_date)

    # id で重複除去（公式を優先）
    merged: dict[str, ArticleItem] = {}
    for item in official + news:
        merged.setdefault(item.id, item)

    items = list(merged.values())
    logger.info(
        f"LLM・AIエージェント動向 収集完了: {len(items)} 件 "
        f"(公式 {len(official)} / ニュース {len(news)})"
    )
    return items


# ── Pass A: 公式アップデート ───────────────────────────────────


async def _collect_official(target_date: date) -> list[ArticleItem]:
    tasks = [
        _fetch_official(name, url, target_date)
        for name, url in settings.ai_dev_rss_feeds.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[ArticleItem] = []
    for name, result in zip(settings.ai_dev_rss_feeds.keys(), results):
        if isinstance(result, list):
            items.extend(result)
        else:
            logger.warning(f"ai_dev 公式フィード収集失敗 ({name}): {result}")
    return items


async def _fetch_official(name: str, url: str, target_date: date) -> list[ArticleItem]:
    feed = await _fetch_feed(url)
    if feed is None:
        return []

    slug = name.lower().replace(" ", "-")
    items: list[ArticleItem] = []
    for entry in feed.entries:
        entry_date = _parse_entry_date(entry)
        if entry_date != target_date:
            continue

        title = entry.get("title", "")
        # プレリリース（alpha/beta/rc/dev/nightly）は安定版に絞るためスキップ
        if _is_prerelease(title):
            continue
        link = entry.get("link", "")
        summary = _strip_html(entry.get("summary", "") or entry.get("description", ""))

        items.append(
            ArticleItem(
                id=f"ai_dev:{slug}:{_url_to_id(link)}",
                title_en=title,
                abstract_en=summary[:800],
                published_date=target_date.isoformat(),
                url=link,
                source_type="rss",
                source_name=name,
                tags=["ai_dev", slug, "official"],
            )
        )
        if len(items) >= settings.ai_dev_max_per_source:
            break

    logger.info(f"ai_dev 公式 ({name}): {len(items)} 件")
    return items


# ── Pass B: キーワード該当ニュース ─────────────────────────────


async def _collect_news(target_date: date) -> list[ArticleItem]:
    tasks = [_fetch_news(url, target_date) for url in settings.ai_dev_news_feeds]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[ArticleItem] = []
    for url, result in zip(settings.ai_dev_news_feeds, results):
        if isinstance(result, list):
            items.extend(result)
        else:
            logger.warning(f"ai_dev ニュース収集失敗 ({url}): {result}")

    # キーワードフィルタ（タイトル or 本文に LLM/エージェント/コーディングAI 関連語）
    keywords_lower = [kw.lower() for kw in settings.ai_dev_filter_keywords]
    filtered = [
        item
        for item in items
        if any(
            kw in (item.title_en + " " + item.abstract_en).lower()
            for kw in keywords_lower
        )
    ]
    filtered = filtered[: settings.ai_dev_news_max_results]
    logger.info(f"ai_dev ニュース: {len(filtered)} 件 (フィルタ前 {len(items)} 件)")
    return filtered


async def _fetch_news(url: str, target_date: date) -> list[ArticleItem]:
    feed = await _fetch_feed(url)
    if feed is None:
        return []

    source_name = feed.feed.get("title", url)
    items: list[ArticleItem] = []
    for entry in feed.entries:
        entry_date = _parse_entry_date(entry)
        # 日付が取れない場合は含める（緩めに）、取れたら前日のみ
        if entry_date is not None and entry_date != target_date:
            continue

        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = _strip_html(entry.get("summary", "") or entry.get("description", ""))

        items.append(
            ArticleItem(
                id=f"ai_dev_news:{_url_to_id(link)}",
                title_en=title,
                abstract_en=summary[:800],
                published_date=target_date.isoformat() if entry_date else "",
                url=link,
                source_type="rss",
                source_name=source_name,
                tags=["ai_dev", "news"],
            )
        )

    logger.info(f"ai_dev ニュース ({source_name}): {len(items)} 件")
    return items


# ── ユーティリティ ────────────────────────────────────────────


async def _fetch_feed(url: str):
    """RSS/Atom を取得して feedparser でパースする。失敗時 None。"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                url,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Daily-Survey/1.0)"},
            )
            resp.raise_for_status()
            return feedparser.parse(resp.text)
    except Exception as e:
        logger.warning(f"ai_dev フィード取得失敗 ({url}): {e}")
        return None


def _parse_entry_date(entry) -> date | None:
    for field in ("published", "updated", "created"):
        raw = entry.get(f"{field}_parsed") or entry.get(field)
        if raw is None:
            continue
        try:
            if hasattr(raw, "tm_year"):
                return date(*time.gmtime(time.mktime(raw))[:3])
            dt = parsedate_to_datetime(str(raw))
            return dt.date()
        except Exception:
            continue
    return None


def _strip_html(text: str) -> str:
    class Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.result = []

        def handle_data(self, d):
            self.result.append(d)

        def get_data(self):
            return " ".join(self.result)

    s = Stripper()
    s.feed(text)
    return s.get_data()


_PRERELEASE_MARKERS = ("alpha", "beta", "-rc", "rc.", ".dev", "nightly", "canary")


def _is_prerelease(title: str) -> bool:
    """バージョンタイトルがプレリリース（alpha/beta/rc 等）か判定する。"""
    t = title.lower()
    return any(m in t for m in _PRERELEASE_MARKERS)


def _url_to_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]
