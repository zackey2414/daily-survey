"""
AI 企業動向収集モジュール
各社公式ブログの RSS フィードから前日の記事を収集する
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


async def collect_industry(target_date: date | None = None) -> list[ArticleItem]:
    """全企業の RSS を並列収集する"""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    tasks = [
        _fetch_rss(company, url, target_date)
        for company, url in settings.industry_rss_feeds.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[ArticleItem] = []
    for company, result in zip(settings.industry_rss_feeds.keys(), results):
        if isinstance(result, list):
            items.extend(result)
        else:
            logger.warning(f"{company} RSS 収集失敗: {result}")

    logger.info(f"企業動向収集完了: {len(items)} 件")
    return items


async def _fetch_rss(
    company: str,
    url: str,
    target_date: date,
) -> list[ArticleItem]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)
    except Exception as e:
        logger.warning(f"{company} RSS 取得失敗: {e}")
        return []

    items: list[ArticleItem] = []
    for entry in feed.entries:
        entry_date = _parse_entry_date(entry)
        if entry_date != target_date:
            continue

        title = entry.get("title", "")
        link = entry.get("link", "")
        summary = entry.get("summary", "") or entry.get("description", "")
        # HTML タグを除去
        summary = _strip_html(summary)

        item_id = f"industry:{company.lower()}:{_url_to_id(link)}"
        items.append(ArticleItem(
            id=item_id,
            title_en=title,
            abstract_en=summary[:500],
            published_date=target_date.isoformat(),
            url=link,
            source_type="rss",
            source_name=company,
            tags=["industry", company.lower()],
        ))

        if len(items) >= settings.industry_max_per_company:
            break

    logger.info(f"{company}: {len(items)} 件")
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
