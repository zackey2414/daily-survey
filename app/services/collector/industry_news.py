"""
海外ニュースメディア RSS から AI 企業・製品関連記事を収集するモジュール
BBC Technology / TechCrunch / The Verge / Wired などを対象とする
"""
import asyncio
import logging
from datetime import date, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from app.schemas import ArticleItem
from app.config import settings

logger = logging.getLogger(__name__)


async def collect_industry_news(target_date: date | None = None) -> list[ArticleItem]:
    """複数ニュースサイトから並列収集し、AI企業関連記事をフィルタリングして返す"""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    tasks = [_fetch_news_rss(url, target_date) for url in settings.news_rss_feeds]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[ArticleItem] = []
    for url, result in zip(settings.news_rss_feeds, results):
        if isinstance(result, list):
            items.extend(result)
        else:
            logger.warning(f"ニュース RSS 収集失敗 ({url}): {result}")

    # キーワードフィルタリング（タイトル or 本文に企業名/製品名を含む）
    keywords_lower = [kw.lower() for kw in settings.news_filter_keywords]
    filtered = [
        item for item in items
        if any(
            kw in (item.title_en + " " + item.abstract_en).lower()
            for kw in keywords_lower
        )
    ]

    # 件数上限
    filtered = filtered[:settings.news_max_results]
    logger.info(f"企業ニュース収集完了: {len(filtered)} 件 (フィルタ前: {len(items)} 件)")
    return filtered


async def _fetch_news_rss(url: str, target_date: date) -> list[ArticleItem]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
    except Exception as e:
        logger.warning(f"ニュース RSS 取得失敗 ({url}): {e}")
        return []

    source_name = feed.feed.get("title", url)
    items: list[ArticleItem] = []

    for entry in feed.entries:
        entry_date = _parse_entry_date(entry)
        # 日付が取得できない場合は含める（緩めにフィルタ）、取得できた場合は前日のみ
        if entry_date is not None and entry_date != target_date:
            continue

        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        summary = _strip_html(summary)

        item_id = f"news:{_url_to_id(link)}"
        items.append(ArticleItem(
            id=item_id,
            title_en=title,
            abstract_en=summary[:500],
            published_date=target_date.isoformat() if entry_date else "",
            url=link,
            source_type="rss",
            source_name=source_name,
            tags=["industry_news"],
        ))

    logger.info(f"ニュース RSS ({source_name}): {len(items)} 件")
    return items


def _parse_entry_date(entry) -> date | None:
    for field in ("published", "updated", "created"):
        raw = entry.get(f"{field}_parsed") or entry.get(field)
        if raw is None:
            continue
        try:
            if hasattr(raw, "tm_year"):
                import time
                return date(*time.gmtime(time.mktime(raw))[:3])
            dt = parsedate_to_datetime(str(raw))
            return dt.date()
        except Exception:
            continue
    return None


def _strip_html(text: str) -> str:
    from html.parser import HTMLParser

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


def _url_to_id(url: str) -> str:
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:12]
