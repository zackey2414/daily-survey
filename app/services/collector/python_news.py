"""
Python 情報収集モジュール
GitHub Trending (Python, daily) からトレンドリポジトリを収集する
"""
import logging
from datetime import date, timedelta

import httpx
from bs4 import BeautifulSoup

from app.schemas import ArticleItem
from app.config import settings

logger = logging.getLogger(__name__)

GITHUB_TRENDING_URL = "https://github.com/trending/python"


async def collect_python_news(target_date: date | None = None) -> list[ArticleItem]:
    """GitHub Trending (Python) からトレンドリポジトリを収集する"""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    items = await _collect_github_trending(target_date)
    items = items[:settings.python_max_results]
    logger.info(f"Python 情報収集完了: {len(items)} 件")
    return items


async def _collect_github_trending(target_date: date) -> list[ArticleItem]:
    """GitHub Trending (Python, daily) をスクレイピングする"""
    try:
        async with httpx.AsyncClient(
            timeout=30.0,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Daily-Survey/1.0)"},
        ) as client:
            resp = await client.get(
                GITHUB_TRENDING_URL,
                params={"since": "daily"},
                follow_redirects=True,
            )
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"GitHub Trending 取得失敗: {e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[ArticleItem] = []

    for article in soup.select("article.Box-row"):
        if len(items) >= settings.python_max_results:
            break

        h2 = article.select_one("h2 a")
        if not h2:
            continue
        href = h2.get("href", "")
        repo_url = f"https://github.com{href}"
        repo_name = href.strip("/")

        desc_el = article.select_one("p")
        description = desc_el.get_text(strip=True) if desc_el else ""

        stars_el = article.select_one("a[href$='/stargazers']")
        stars = stars_el.get_text(strip=True) if stars_el else ""

        title = repo_name
        if stars:
            title += f" (★ {stars})"

        items.append(ArticleItem(
            id=f"github_trending:{_url_to_id(repo_url)}",
            title_en=title,
            title_ja=title,
            abstract_en=description,
            published_date=target_date.isoformat(),
            url=repo_url,
            source_type="github_trending",
            source_name="GitHub Trending",
            tags=["python", "github", "trending"],
        ))

    logger.info(f"GitHub Trending: {len(items)} 件")
    return items


def _url_to_id(url: str) -> str:
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:12]
