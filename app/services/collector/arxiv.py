"""
arXiv 論文収集モジュール
対象カテゴリ: cs.CV, cs.LG, cs.AI, cs.CL
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal
import xml.etree.ElementTree as ET

import httpx

from app.schemas import ArticleItem
from app.config import settings

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
JST = timezone(timedelta(hours=9))

ArxivCategory = Literal["cs.CV", "cs.LG", "cs.AI", "cs.CL"]


async def collect_arxiv(
    category: ArxivCategory,
    target_date: date | None = None,
    max_results: int | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ArticleItem]:
    """
    指定カテゴリの arXiv 論文を収集する。

    target_date (JST 前日) の 00:00〜23:59 JST に投稿された論文のみを返す。
    UTC 換算: (target_date - 1日) 15:00:00 〜 target_date 14:59:59

    client を渡すと既存の httpx.AsyncClient を再利用する（直列収集向け）。
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    if max_results is None:
        max_results = settings.arxiv_max_results

    # JST 前日 00:00〜23:59 = UTC (target_date-1) 15:00 〜 target_date 14:59
    # 月曜日の場合、金曜〜月曜の投稿を含むため submittedDate を金曜まで遡る
    if target_date.weekday() == 0:  # Monday
        lookback_days = 3  # 金曜まで遡る
    else:
        lookback_days = 1
    from_str = (target_date - timedelta(days=lookback_days)).strftime(
        "%Y%m%d"
    ) + "150000"
    to_str = target_date.strftime("%Y%m%d") + "145959"

    params: dict[str, Any] = {
        "search_query": f"cat:{category} AND submittedDate:[{from_str} TO {to_str}]",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max(100, max_results * 5),
        "start": 0,
    }

    logger.info(
        f"arXiv 収集開始: {category} / 対象日(JST): {target_date} "
        f"(UTC: {from_str} 〜 {to_str})"
    )

    max_retries = 5
    resp = None

    async def _fetch(c: httpx.AsyncClient) -> httpx.Response | None:
        nonlocal resp
        for attempt in range(max_retries):
            try:
                resp = await c.get(ARXIV_API_URL, params=params)
                resp.raise_for_status()
                return resp
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                retryable = status == 429 or status >= 500
                if attempt < max_retries - 1 and retryable:
                    wait = 10 * (2**attempt)  # 10s, 20s, 40s, 80s
                    logger.warning(
                        f"arXiv API {status} ({category}): "
                        f"{wait}秒後にリトライ (試行 {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"arXiv API エラー ({category}): {e}")
                return None
            except httpx.HTTPError as e:
                logger.error(f"arXiv API エラー ({category}): {e}")
                return None
        return None

    if client is not None:
        result = await _fetch(client)
    else:
        async with httpx.AsyncClient(timeout=90.0) as c:
            result = await _fetch(c)

    if result is None:
        return []

    items = _parse_arxiv_xml(result.text, category, target_date)
    items = items[:max_results]
    logger.info(f"arXiv 収集完了: {category} / {len(items)} 件")
    return items


def _parse_arxiv_xml(
    xml_text: str,
    category: str,
    target_date: date,
) -> list[ArticleItem]:
    root = ET.fromstring(xml_text)
    items: list[ArticleItem] = []

    for entry in root.findall("atom:entry", NS):
        published_raw = entry.findtext("atom:published", "", NS)
        if not published_raw:
            continue

        # JST で公開日を判定
        try:
            pub_dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            pub_jst_date = pub_dt.astimezone(JST).date()
        except ValueError:
            continue

        if pub_jst_date != target_date:
            continue

        arxiv_id_raw = entry.findtext("atom:id", "", NS)
        arxiv_id = arxiv_id_raw.split("/abs/")[-1].strip()

        title = (entry.findtext("atom:title", "", NS) or "").replace("\n", " ").strip()
        abstract = (
            (entry.findtext("atom:summary", "", NS) or "").replace("\n", " ").strip()
        )

        authors = [
            a.findtext("atom:name", "", NS) for a in entry.findall("atom:author", NS)
        ]

        pdf_url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break

        items.append(
            ArticleItem(
                id=f"arxiv:{arxiv_id}",
                title_en=title,
                authors=authors,
                abstract_en=abstract,
                published_date=pub_jst_date.isoformat(),
                url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
                source_type="arxiv",
                source_name="arXiv",
                tags=[category],
            )
        )

    return items


def _cv_priority_score(item: ArticleItem) -> int:
    """CS.CV 論文のトピック優先度スコア（小さいほど優先表示）"""
    text = (item.title_en + " " + item.abstract_en[:300]).lower()
    # 優先度 1: 画像検索・物体中心画像検索・動画サンプリング
    if any(
        kw in text
        for kw in [
            "image retrieval",
            "image search",
            "object-centric",
            "video sampling",
            "temporal sampling",
            "frame sampling",
            "video retrieval",
            "content-based retrieval",
        ]
    ):
        return 0
    # 優先度 2: 動画像分類・物体検知・セグメンテーション・認識
    if any(
        kw in text
        for kw in [
            "classification",
            "object detection",
            "instance segmentation",
            "semantic segmentation",
            "panoptic",
            "action recognition",
            "video understanding",
            "video classification",
            "pose estimation",
        ]
    ):
        return 1
    # 優先度 3: その他 cs.CV
    return 2


async def collect_arxiv_cv(
    target_date: date | None = None,
    max_results: int = 40,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ArticleItem]:
    """
    cs.CV 論文をトピック優先度付きで収集する（最大 max_results 件）。

    多めに取得してから優先度でソートし上位 max_results 件を返す。
    優先度: 画像検索系 > 分類・検知・セグメンテーション > その他 CV
    """
    raw = await collect_arxiv(
        "cs.CV", target_date, max_results=max_results * 2, client=client
    )
    sorted_items = sorted(raw, key=lambda item: _cv_priority_score(item))
    return sorted_items[:max_results]


# カテゴリ間の待機秒数（arXiv API のレートリミットを避けるため余裕を持たせる）
_INTER_CATEGORY_DELAY = 5


async def collect_all_arxiv_serial(
    target_date: date | None = None,
) -> tuple[list[ArticleItem], dict[str, list[ArticleItem]]]:
    """
    全 arXiv カテゴリ（cs.CV, cs.LG, cs.AI, cs.CL）を1つのクライアントで直列に収集する。

    カテゴリ間に十分な待機時間を設けて 429 を回避する。
    Returns: (cv_papers, {category: papers})
    """
    categories: list[ArxivCategory] = ["cs.LG", "cs.AI", "cs.CL"]

    async with httpx.AsyncClient(timeout=90.0) as client:
        # 1) cs.CV（優先度付き）
        try:
            cv_papers = await collect_arxiv_cv(target_date, client=client)
        except Exception as e:
            logger.error(f"arXiv cs.CV 収集失敗: {e}")
            cv_papers = []

        await asyncio.sleep(_INTER_CATEGORY_DELAY)

        # 2) LG / AI / CL を直列に収集
        other_results: dict[str, list[ArticleItem]] = {}
        for cat in categories:
            try:
                items = await collect_arxiv(cat, target_date, client=client)
                other_results[cat] = items
            except Exception as e:
                logger.error(f"{cat} 収集失敗: {e}")
                other_results[cat] = []
            await asyncio.sleep(_INTER_CATEGORY_DELAY)

    return cv_papers, other_results
