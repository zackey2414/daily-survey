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


# 0件時に遡及を段階的に拡大するフォールバック日数（索引反映遅延・低調日・週末対策）
_FALLBACK_LOOKBACKS = (3, 7)
_FALLBACK_DELAY = 8  # フォールバック再取得の前に待機する秒数（連続リクエスト回避）
_MAX_RETRIES = 5


async def collect_arxiv(
    category: ArxivCategory,
    target_date: date | None = None,
    max_results: int | None = None,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ArticleItem]:
    """
    指定カテゴリの arXiv 論文を収集する。

    通常は target_date (JST 前日) 当日に投稿された論文を返す。
    0 件だった場合（arXiv の submittedDate インデックス反映遅延・低調日・週末など）は
    遡及日数を段階的に広げて再取得し、空の日を極力作らない。重複は呼び出し側の
    seen_ids で除去される前提。

    client を渡すと既存の httpx.AsyncClient を再利用する（直列収集向け）。
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    if max_results is None:
        max_results = settings.arxiv_max_results

    logger.info(f"arXiv 収集開始: {category} / 対象日(JST): {target_date}")

    # 通常ウィンドウ: target 当日分
    items = await _query_arxiv(
        category, target_date, target_date, max_results, client=client
    )

    # 0件フォールバック: 遡及を段階的に拡大
    if not items:
        for fb in _FALLBACK_LOOKBACKS:
            await asyncio.sleep(_FALLBACK_DELAY)  # 連続リクエストを避けレート制限に配慮
            earliest = target_date - timedelta(days=fb)
            logger.warning(
                f"arXiv {category}: 0件のため遡及 {fb} 日 "
                f"({earliest}〜{target_date}) に拡大して再取得"
            )
            items = await _query_arxiv(
                category, earliest, target_date, max_results, client=client
            )
            if items:
                break

    logger.info(f"arXiv 収集完了: {category} / {len(items)} 件")
    return items


async def _query_arxiv(
    category: str,
    earliest_date: date,
    target_date: date,
    max_results: int,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ArticleItem]:
    """submittedDate ウィンドウ [earliest_date, target_date] を検索し、その範囲に
    JST 公開された論文を返す。"""
    # JST earliest_date 00:00 = UTC (earliest_date-1) 15:00 / JST target 23:59 = UTC target 14:59
    from_str = (earliest_date - timedelta(days=1)).strftime("%Y%m%d") + "150000"
    to_str = target_date.strftime("%Y%m%d") + "145959"

    params: dict[str, Any] = {
        "search_query": f"cat:{category} AND submittedDate:[{from_str} TO {to_str}]",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max(100, max_results * 5),
        "start": 0,
    }

    if client is not None:
        text = await _fetch_with_retry(category, params, client)
    else:
        async with httpx.AsyncClient(timeout=90.0) as c:
            text = await _fetch_with_retry(category, params, c)

    if text is None:
        return []
    return _parse_arxiv_xml(text, category, earliest_date, target_date)[:max_results]


async def _fetch_with_retry(
    category: str, params: dict[str, Any], client: httpx.AsyncClient
) -> str | None:
    """arXiv API をリトライ付きで取得し XML テキストを返す。

    429/5xx に加えてタイムアウト・接続エラー（TransportError）もリトライ対象とする。
    """
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(ARXIV_API_URL, params=params)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if attempt < _MAX_RETRIES - 1 and (status == 429 or status >= 500):
                retry_after = e.response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = int(retry_after) + 5
                else:
                    wait = 15 * (2**attempt)  # 15s, 30s, 60s, 120s
                logger.warning(
                    f"arXiv API {status} ({category}): "
                    f"{wait}秒後にリトライ (試行 {attempt + 1}/{_MAX_RETRIES})"
                )
                await asyncio.sleep(wait)
                continue
            logger.error(f"arXiv API エラー ({category}): {e}")
            return None
        except (httpx.TimeoutException, httpx.TransportError) as e:
            # ネットワーク/タイムアウト系は一時障害としてリトライ
            if attempt < _MAX_RETRIES - 1:
                wait = 10 * (2**attempt)  # 10s, 20s, 40s, 80s
                logger.warning(
                    f"arXiv API 通信エラー ({category}): {e} "
                    f"{wait}秒後にリトライ (試行 {attempt + 1}/{_MAX_RETRIES})"
                )
                await asyncio.sleep(wait)
                continue
            logger.error(f"arXiv API 通信エラー ({category}): {e}")
            return None
        except httpx.HTTPError as e:
            logger.error(f"arXiv API エラー ({category}): {e}")
            return None
    return None


def _parse_arxiv_xml(
    xml_text: str,
    category: str,
    earliest_date: date,
    target_date: date,
) -> list[ArticleItem]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"arXiv XML パース失敗 ({category}): {e}")
        return []
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

        # 公開日が [earliest_date, target_date] の範囲外なら除外
        if not (earliest_date <= pub_jst_date <= target_date):
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
    """CS.CV 論文のトピック優先度スコア（小さいほど優先表示）。

    特定トピック（画像検索・物体中心画像検索など）の優先付けは「検索テーマ」機構
    （app/services/theme_search.py）に一本化したため、ここでは一般的な CV タスクを
    その他の cs.CV より前に出す軽いランキングのみを行う。
    """
    text = (item.title_en + " " + item.abstract_en[:300]).lower()
    # 優先度 0: 動画像分類・物体検知・セグメンテーション・認識など主要 CV タスク
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
        return 0
    # 優先度 1: その他 cs.CV
    return 1


async def collect_arxiv_cv(
    target_date: date | None = None,
    max_results: int = 40,
    *,
    client: httpx.AsyncClient | None = None,
) -> list[ArticleItem]:
    """
    cs.CV 論文をトピック優先度付きで収集する（最大 max_results 件）。

    多めに取得してから優先度でソートし上位 max_results 件を返す。
    優先度: 主要 CV タスク（分類・検知・セグメンテーション等） > その他 CV。
    特定の研究テーマ（画像検索など）は検索テーマ機構で別途横断収集される。
    """
    raw = await collect_arxiv(
        "cs.CV", target_date, max_results=max_results * 2, client=client
    )
    sorted_items = sorted(raw, key=lambda item: _cv_priority_score(item))
    return sorted_items[:max_results]


# カテゴリ間の待機秒数（arXiv API のレートリミットを避けるため余裕を持たせる）
_INTER_CATEGORY_DELAY = 15


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
