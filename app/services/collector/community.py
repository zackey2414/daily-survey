"""
SNS・コミュニティ収集モジュール
Qiita API, Zenn RSS, Reddit API から前日の記事を収集する
"""
import asyncio
import logging
from datetime import date, timedelta

import feedparser
import httpx

from app.schemas import ArticleItem
from app.config import settings

logger = logging.getLogger(__name__)

QIITA_API_URL = "https://qiita.com/api/v2/items"
ZENN_RSS_URLS = [
    "https://zenn.dev/topics/machinelearning/feed",
    "https://zenn.dev/topics/deeplearning/feed",
    "https://zenn.dev/topics/llm/feed",
    "https://zenn.dev/topics/ai/feed",
]
REDDIT_JSON_BASE = "https://www.reddit.com/r/{}/new.json"


async def collect_community(target_date: date | None = None) -> list[ArticleItem]:
    """Qiita, Zenn, Reddit を並列収集する"""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    qiita_task = _collect_qiita(target_date)
    zenn_task = _collect_zenn(target_date)
    reddit_task = _collect_reddit(target_date)

    results = await asyncio.gather(qiita_task, zenn_task, reddit_task, return_exceptions=True)
    items: list[ArticleItem] = []
    for r in results:
        if isinstance(r, list):
            items.extend(r)
    # 全ソース合計で上限に収める
    items = items[:settings.community_max_results]
    logger.info(f"コミュニティ収集完了: {len(items)} 件")
    return items


async def _collect_qiita(target_date: date) -> list[ArticleItem]:
    date_str = target_date.isoformat()
    headers = {}
    if settings.qiita_access_token:
        headers["Authorization"] = f"Bearer {settings.qiita_access_token}"

    params = {
        "page": 1,
        "per_page": 10,  # Qiita は最大 10 件（合計 20 件に収めるため）
        "query": f"tag:AI OR tag:機械学習 OR tag:LLM OR tag:生成AI created:{date_str}",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(QIITA_API_URL, params=params, headers=headers)
            resp.raise_for_status()
            entries = resp.json()
    except Exception as e:
        logger.warning(f"Qiita 取得失敗: {e}")
        return []

    items: list[ArticleItem] = []
    for entry in entries:
        created_at = entry.get("created_at", "")[:10]
        if created_at != date_str:
            continue
        items.append(ArticleItem(
            id=f"qiita:{entry.get('id', '')}",
            title_ja=entry.get("title", ""),
            title_en=entry.get("title", ""),
            abstract_en=(entry.get("body", "") or "")[:300],
            published_date=created_at,
            url=entry.get("url", ""),
            source_type="qiita",
            source_name="Qiita",
            tags=[t.get("name", "") for t in entry.get("tags", [])],
        ))
    logger.info(f"Qiita: {len(items)} 件")
    return items


async def _collect_zenn(target_date: date) -> list[ArticleItem]:
    items: list[ArticleItem] = []
    seen_urls: set[str] = set()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for rss_url in ZENN_RSS_URLS:
            try:
                resp = await client.get(rss_url, follow_redirects=True)
                feed = feedparser.parse(resp.text)
            except Exception as e:
                logger.warning(f"Zenn RSS 取得失敗 ({rss_url}): {e}")
                continue

            for entry in feed.entries:
                if len(items) >= 7:  # Zenn は最大 7 件
                    break
                link = entry.get("link", "")
                if link in seen_urls:
                    continue

                # 日付判定
                pub = entry.get("published", "")
                entry_date = _parse_date_from_str(pub)
                if entry_date != target_date:
                    continue

                seen_urls.add(link)
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")

                items.append(ArticleItem(
                    id=f"zenn:{_url_to_id(link)}",
                    title_ja=title,
                    title_en=title,
                    abstract_en=summary[:300],
                    published_date=target_date.isoformat(),
                    url=link,
                    source_type="zenn",
                    source_name="Zenn",
                    tags=["zenn"],
                ))

    logger.info(f"Zenn: {len(items)} 件")
    return items


async def _collect_reddit(target_date: date) -> list[ArticleItem]:
    import time
    start_ts = int(
        (date(target_date.year, target_date.month, target_date.day).__class__(
            target_date.year, target_date.month, target_date.day
        )).timetuple().__reduce__()[1][1]
    )
    # よりシンプルな方法でタイムスタンプを計算
    from datetime import datetime
    start_ts = int(datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0).timestamp())
    end_ts = int(datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59).timestamp())

    items: list[ArticleItem] = []
    headers = {"User-Agent": settings.reddit_user_agent}

    async with httpx.AsyncClient(timeout=30.0) as client:
        for subreddit in settings.reddit_subreddits:
            if len(items) >= 10:  # Reddit は合計最大 10 件（各サブレディット 5 件程度）
                break
            try:
                url = REDDIT_JSON_BASE.format(subreddit)
                resp = await client.get(url, headers=headers, params={"limit": 25})
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(f"Reddit r/{subreddit} 取得失敗: {e}")
                continue

            for post in data.get("data", {}).get("children", []):
                pd = post.get("data", {})
                created = pd.get("created_utc", 0)
                if not (start_ts <= created <= end_ts):
                    continue

                post_id = pd.get("id", "")
                title = pd.get("title", "")
                selftext = (pd.get("selftext", "") or "")[:300]
                post_url = pd.get("url", "")
                permalink = f"https://www.reddit.com{pd.get('permalink', '')}"

                items.append(ArticleItem(
                    id=f"reddit:{subreddit}:{post_id}",
                    title_en=title,
                    abstract_en=selftext,
                    published_date=target_date.isoformat(),
                    url=permalink,
                    source_type="reddit",
                    source_name=f"r/{subreddit}",
                    tags=["reddit", subreddit],
                ))

    logger.info(f"Reddit: {len(items)} 件")
    return items


def _parse_date_from_str(date_str: str) -> date | None:
    from email.utils import parsedate_to_datetime
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.date()
    except Exception:
        pass
    try:
        return date.fromisoformat(date_str[:10])
    except Exception:
        return None


def _url_to_id(url: str) -> str:
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:12]
