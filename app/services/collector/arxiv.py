"""
arXiv 論文収集モジュール
対象カテゴリ: cs.CV, cs.LG, cs.AI, cs.CL
"""
import asyncio
import logging
from datetime import date, timedelta
from typing import Literal
import xml.etree.ElementTree as ET

import httpx

from app.schemas import ArticleItem
from app.config import settings

logger = logging.getLogger(__name__)

ARXIV_API_URL = "http://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

ArxivCategory = Literal["cs.CV", "cs.LG", "cs.AI", "cs.CL"]


async def collect_arxiv(
    category: ArxivCategory,
    target_date: date | None = None,
    max_results: int | None = None,
) -> list[ArticleItem]:
    """
    指定カテゴリの arXiv 論文を収集する。
    target_date: 収集対象日（デフォルト: 前日）
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    if max_results is None:
        max_results = settings.arxiv_max_results

    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_results * 3,  # フィルタ後に必要数を確保するため多めに取得
        "start": 0,
    }

    logger.info(f"arXiv 収集開始: {category} / 対象日: {target_date}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.get(ARXIV_API_URL, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            logger.error(f"arXiv API エラー ({category}): {e}")
            return []

    items = _parse_arxiv_xml(resp.text, category, target_date)
    items = items[:max_results]
    logger.info(f"arXiv 収集完了: {category} / {len(items)} 件")
    return items


def _parse_arxiv_xml(xml_text: str, category: str, target_date: date) -> list[ArticleItem]:
    root = ET.fromstring(xml_text)
    items: list[ArticleItem] = []

    for entry in root.findall("atom:entry", NS):
        # 公開日
        published_raw = entry.findtext("atom:published", "", NS)
        if not published_raw:
            continue
        published_date_str = published_raw[:10]  # "YYYY-MM-DD"
        try:
            published = date.fromisoformat(published_date_str)
        except ValueError:
            continue

        # 対象日のみに絞る
        if published != target_date:
            continue

        arxiv_id_raw = entry.findtext("atom:id", "", NS)
        arxiv_id = arxiv_id_raw.split("/abs/")[-1].strip()

        title = (entry.findtext("atom:title", "", NS) or "").replace("\n", " ").strip()
        abstract = (entry.findtext("atom:summary", "", NS) or "").replace("\n", " ").strip()

        authors = [
            a.findtext("atom:name", "", NS)
            for a in entry.findall("atom:author", NS)
        ]

        # PDF URL
        pdf_url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break

        items.append(ArticleItem(
            id=f"arxiv:{arxiv_id}",
            title_en=title,
            authors=authors,
            abstract_en=abstract,
            published_date=published_date_str,
            url=f"https://arxiv.org/abs/{arxiv_id}",
            pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
            source_type="arxiv",
            source_name="arXiv",
            tags=[category],
        ))

    return items


async def collect_all_arxiv(target_date: date | None = None) -> dict[str, list[ArticleItem]]:
    """全カテゴリを並列収集する"""
    categories: list[ArxivCategory] = ["cs.CV", "cs.LG", "cs.AI", "cs.CL"]
    results = await asyncio.gather(
        *[collect_arxiv(cat, target_date) for cat in categories],
        return_exceptions=True,
    )
    return {
        cat: (r if isinstance(r, list) else [])
        for cat, r in zip(categories, results)
    }
