"""
OpenReview 論文収集モジュール
主要 AI 学会の投稿論文を OpenReview API v2 (invitation ベース) で収集する
対象トピック: CV / LLM / VLM
"""
import logging
from datetime import date, timedelta, datetime, timezone

import httpx

from app.schemas import ArticleItem
from app.config import settings

logger = logging.getLogger(__name__)

OPENREVIEW_API_URL = "https://api2.openreview.net/notes"
JST = timezone(timedelta(hours=9))

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

# CV / LLM / VLM 関連キーワード（タイトル・アブストラクト照合）
_CV_KEYWORDS = [
    "image", "video", "vision", "visual", "segmentation", "detection",
    "recognition", "object", "scene", "depth", "pose", "3d", "rendering",
    "diffusion", "generation", "synthesis", "super-resolution", "tracking",
    "camera", "optical flow", "point cloud", "stereo",
]
_LLM_KEYWORDS = [
    "language model", "llm", "large language", "gpt", "pre-train", "pretrain",
    "instruction tun", "fine-tun", "finetuning", "rlhf", "alignment",
    "text generation", "autoregressive", "token", "reasoning", "chain-of-thought",
]
_VLM_KEYWORDS = [
    "vision-language", "vision language", "multimodal", "visual language",
    "vlm", "clip", "image-text", "text-image", "vision encoder",
    "visual grounding", "vqa", "visual question", "image captioning",
]

_ALL_TOPIC_KEYWORDS = _CV_KEYWORDS + _LLM_KEYWORDS + _VLM_KEYWORDS


def _is_relevant_topic(title: str, abstract: str) -> bool:
    """CV / LLM / VLM トピックに該当するか判定"""
    text = (title + " " + abstract[:500]).lower()
    return any(kw in text for kw in _ALL_TOPIC_KEYWORDS)


async def collect_openreview(target_date: date | None = None) -> list[ArticleItem]:
    """
    日本時間 target_date の 00:00〜23:59 に新規投稿された論文を収集する。
    CV / LLM / VLM トピックのみを対象とする。
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    # JST target_date 00:00:00 〜 23:59:59 をミリ秒に変換
    start_ms = int(datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=JST
    ).timestamp() * 1000)
    end_ms = int(datetime(
        target_date.year, target_date.month, target_date.day, 23, 59, 59, tzinfo=JST
    ).timestamp() * 1000)

    items: list[ArticleItem] = []
    seen_ids: set[str] = set()

    # 試行する年（投稿受付は翌年の学会向けが多い: +1 → 0 → -1 の順）
    years_to_try = [target_date.year + 1, target_date.year, target_date.year - 1]

    logger.info(f"OpenReview 収集開始: 対象日(JST) {target_date}")

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

    logger.info(f"OpenReview 収集完了: {len(items)} 件（トピックフィルタ後）")
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

    logger.info(f"OpenReview {invitation}: {len(notes)} 件（フィルタ前）")
    items: list[ArticleItem] = []

    for note in notes:
        note_id = note.get("id", "")
        if not note_id or note_id in seen_ids:
            continue

        content = note.get("content", {})
        title = _extract_field(content, "title")
        if not title:
            continue

        abstract = _extract_field(content, "abstract")

        # CV / LLM / VLM トピックフィルタ
        if not _is_relevant_topic(title, abstract):
            continue

        seen_ids.add(note_id)

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
