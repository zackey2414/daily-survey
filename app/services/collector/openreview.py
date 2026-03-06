"""
OpenReview 論文収集モジュール
主要 AI 学会の投稿論文を OpenReview API v2 (invitation ベース) で収集する
"""
import logging
from datetime import date, timedelta, datetime, timezone

import httpx

from app.schemas import ArticleItem
from app.config import settings

logger = logging.getLogger(__name__)

OPENREVIEW_API_URL = "https://api2.openreview.net/notes"

# 短縮名 → invitation テンプレート（{year} は動的置換）
# OpenReview API v2 では `content.venue` ではなく `invitation` で学会を絞り込む
VENUE_INVITATIONS: dict[str, str] = {
    "ICLR":    "ICLR.cc/{year}/Conference/-/Blind_Submission",
    "NeurIPS": "NeurIPS.cc/{year}/Conference/-/Submission",
    "ICML":    "ICML.cc/{year}/Conference/-/Submission",
    "CVPR":    "CVPR.thecvf.com/{year}/Conference/-/Submission",
    "ICCV":    "ICCV.thecvf.com/{year}/Conference/-/Submission",
    "ECCV":    "ECCV/{year}/Conference/-/Submission",
    "AAAI":    "AAAI.org/{year}/Conference/-/Submission",
    "ACL":     "aclweb.org/ACL/{year}/Conference/-/Submission",
    "EMNLP":   "EMNLP/{year}/Conference/-/Submission",
    "IJCAI":   "IJCAI.org/{year}/Conference/-/Submission",
}


async def collect_openreview(target_date: date | None = None) -> list[ArticleItem]:
    """
    指定日付前後の論文を OpenReview から収集する。

    arXiv 同様、学会の投稿締切は特定日に集中するため前後4日を許容範囲とする。
    翌年→当年の順で各学会の invitation を試行し、結果が得られた年を採用する。
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    date_from = target_date - timedelta(days=4)
    date_to   = target_date + timedelta(days=1)

    start_ms = int(datetime(
        date_from.year, date_from.month, date_from.day, 0, 0, 0, tzinfo=timezone.utc
    ).timestamp() * 1000)
    end_ms = int(datetime(
        date_to.year, date_to.month, date_to.day, 23, 59, 59, tzinfo=timezone.utc
    ).timestamp() * 1000)

    items: list[ArticleItem] = []
    seen_ids: set[str] = set()

    # 試行する年（投稿受付は翌年の学会向けが多い: +1 → 0 → -1 の順）
    years_to_try = [target_date.year + 1, target_date.year, target_date.year - 1]

    logger.info(
        f"OpenReview 収集開始: 対象日 {target_date} "
        f"(許容範囲: {date_from} 〜 {date_to})"
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        for venue_short in settings.openreview_venues:
            if len(items) >= settings.openreview_max_results:
                break

            template = VENUE_INVITATIONS.get(venue_short)
            if template is None:
                logger.debug(f"OpenReview: {venue_short} の invitation テンプレート未定義")
                continue

            for year in years_to_try:
                invitation = template.format(year=year)
                venue_items = await _fetch_by_invitation(
                    client, invitation, venue_short, start_ms, end_ms, seen_ids
                )
                if venue_items:
                    items.extend(venue_items)
                    break  # 結果が得られたのでこの venue の試行を終了

    logger.info(f"OpenReview 収集完了: {len(items)} 件")
    return items[:settings.openreview_max_results]


async def _fetch_by_invitation(
    client: httpx.AsyncClient,
    invitation: str,
    venue_short: str,
    start_ms: int,
    end_ms: int,
    seen_ids: set[str],
) -> list[ArticleItem]:
    params = {
        "invitation": invitation,
        "mintcdate": start_ms,
        "maxtcdate": end_ms,
        "limit": 25,
        "offset": 0,
        "select": "id,content,tcdate",
    }
    try:
        resp = await client.get(OPENREVIEW_API_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.debug(f"OpenReview {invitation} 取得失敗: {e}")
        return []

    notes = data.get("notes", [])
    if not notes:
        return []

    logger.info(f"OpenReview {invitation}: {len(notes)} 件")
    items: list[ArticleItem] = []

    for note in notes:
        note_id = note.get("id", "")
        if not note_id or note_id in seen_ids:
            continue
        seen_ids.add(note_id)

        content = note.get("content", {})
        title = _extract_field(content, "title")
        if not title:
            continue

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
            source_name=f"OpenReview ({venue_short})",
            tags=["cv", venue_short],
        ))

    return items


def _extract_field(content: dict, key: str) -> str:
    val = content.get(key, "")
    if isinstance(val, dict):
        return val.get("value", "")
    return str(val) if val else ""
