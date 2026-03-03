"""
OpenReview 論文収集モジュール
前日に投稿・更新があった論文を対象学会から収集する
"""
import logging
from datetime import date, timedelta, datetime, timezone

import httpx

from app.schemas import ArticleItem
from app.config import settings

logger = logging.getLogger(__name__)

OPENREVIEW_API_URL = "https://api2.openreview.net/notes"


async def collect_openreview(target_date: date | None = None) -> list[ArticleItem]:
    """前日に投稿・更新された論文を OpenReview から収集する"""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    # 対象日の UTC タイムスタンプ範囲（milliseconds）
    start_dt = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=timezone.utc)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    items: list[ArticleItem] = []
    seen_ids: set[str] = set()

    logger.info(f"OpenReview 収集開始: 対象日 {target_date}")

    async with httpx.AsyncClient(timeout=60.0) as client:
        for venue in settings.openreview_venues:
            if len(items) >= settings.openreview_max_results:
                break
            venue_items = await _fetch_venue(client, venue, start_ms, end_ms, seen_ids)
            items.extend(venue_items)

    logger.info(f"OpenReview 収集完了: {len(items)} 件")
    return items[:settings.openreview_max_results]


async def _fetch_venue(
    client: httpx.AsyncClient,
    venue: str,
    start_ms: int,
    end_ms: int,
    seen_ids: set[str],
) -> list[ArticleItem]:
    params = {
        "content.venue": venue,
        "mintcdate": start_ms,
        "maxtcdate": end_ms,
        "limit": 25,
        "offset": 0,
        "select": "id,content,tcdate,tmdate",
    }
    try:
        resp = await client.get(OPENREVIEW_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning(f"OpenReview {venue} 取得失敗: {e}")
        return []

    notes = data.get("notes", [])
    items: list[ArticleItem] = []

    for note in notes:
        note_id = note.get("id", "")
        if not note_id or note_id in seen_ids:
            continue
        seen_ids.add(note_id)

        content = note.get("content", {})
        title = _extract_field(content, "title")
        abstract = _extract_field(content, "abstract")
        authors_raw = content.get("authors", {})
        if isinstance(authors_raw, dict):
            authors = authors_raw.get("value", [])
        elif isinstance(authors_raw, list):
            authors = authors_raw
        else:
            authors = []

        pdf_url = _extract_field(content, "pdf")
        if pdf_url and not pdf_url.startswith("http"):
            pdf_url = f"https://openreview.net{pdf_url}"

        tcdate = note.get("tcdate", 0)
        published_date_str = date.fromtimestamp(tcdate / 1000).isoformat() if tcdate else ""

        items.append(ArticleItem(
            id=f"openreview:{note_id}",
            title_en=title,
            authors=authors,
            abstract_en=abstract,
            published_date=published_date_str,
            url=f"https://openreview.net/forum?id={note_id}",
            pdf_url=pdf_url,
            source_type="openreview",
            source_name=f"OpenReview ({venue})",
            tags=["cv", venue],
        ))

    return items


def _extract_field(content: dict, key: str) -> str:
    val = content.get(key, "")
    if isinstance(val, dict):
        return val.get("value", "")
    return str(val) if val else ""
