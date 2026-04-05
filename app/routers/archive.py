"""
アーカイブページルーター（過去日付の記事表示）
日付を超えた直後でもページを表示し、データがなければ案内メッセージを出す。
"""

import markdown as md
import pytz
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import UserTag
from app.jinja import templates
from app.schemas import ArticleItem
from app.services.pipeline import load_daily_data, list_available_dates
from app.services.digest import load_digest, inject_citations

router = APIRouter(prefix="/archive")
JST = pytz.timezone("Asia/Tokyo")


@router.get("/{date_str}", response_class=HTMLResponse)
async def archive_day(
    request: Request, date_str: str, db: AsyncSession = Depends(get_db)
):
    # 日付フォーマット検証
    try:
        collection_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

    today = datetime.now(JST).date()
    is_today = collection_date == today

    target_date_str = (collection_date - timedelta(days=1)).isoformat()
    data = load_daily_data(date_str)

    # 全記事 ID を収集してユーザータグを一括取得
    all_items = []
    for key in [
        "cv",
        "openreview",
        "lg",
        "ai",
        "cl",
        "industry",
        "industry_news",
        "community",
        "github_trending",
    ]:
        all_items.extend(data.get(key, []))

    article_ids = [item.id for item in all_items]
    user_tags_by_id: dict[str, list[str]] = {aid: [] for aid in article_ids}
    if article_ids:
        stmt = (
            select(UserTag)
            .where(UserTag.article_id.in_(article_ids))
            .order_by(UserTag.article_id, UserTag.created_at)
        )
        result = await db.execute(stmt)
        for ut in result.scalars().all():
            user_tags_by_id.setdefault(ut.article_id, []).append(ut.tag)

    # ダイジェスト（引用リンク注入）
    digest_raw = load_digest(date_str)
    if digest_raw:
        processed = inject_citations(digest_raw, date_str, is_archive=True)
        digest_html = md.markdown(
            processed,
            extensions=["fenced_code", "tables", "nl2br"],
            tab_length=2,
        )
    else:
        digest_html = None

    available_dates = list_available_dates()
    # 今日の日付がリストになければ先頭に追加（日付変更直後でデータ未収集の場合）
    today_str = today.isoformat()
    if today_str not in available_dates:
        available_dates = [today_str] + available_dates

    # データが存在するかのフラグ
    has_data = bool(all_items)

    # GitHub Trending のソート済みリスト生成
    gt_items = data.get("github_trending", [])
    gt_by_daily = _sort_gt_items(gt_items, "stars_daily")
    gt_by_weekly = _sort_gt_items(gt_items, "stars_weekly")
    gt_by_monthly = _sort_gt_items(gt_items, "stars_monthly")
    gt_by_total = _sort_gt_items(gt_items, "stars_total")

    return templates.TemplateResponse(
        "pages/index.html",
        {
            "request": request,
            "date_str": date_str,
            "target_date_str": target_date_str,
            "is_today": is_today,
            "has_data": has_data,
            "digest_html": digest_html,
            "cv_papers": data.get("cv", []),
            "openreview_papers": data.get("openreview", []),
            "lg_papers": data.get("lg", []),
            "ai_papers": data.get("ai", []),
            "cl_papers": data.get("cl", []),
            "industry_items": data.get("industry", []),
            "industry_news_items": data.get("industry_news", []),
            "community_items": data.get("community", []),
            "python_items": [],
            "github_trending_items": gt_items,
            "github_trending_by_daily": gt_by_daily,
            "github_trending_by_weekly": gt_by_weekly,
            "github_trending_by_monthly": gt_by_monthly,
            "github_trending_by_total": gt_by_total,
            "available_dates": available_dates,
            "user_tags_by_id": user_tags_by_id,
        },
    )


def _extract_star_tag(item: ArticleItem, prefix: str) -> int:
    """tags から 'stars_daily:1234' 形式の数値を抽出"""
    for tag in item.tags:
        if tag.startswith(prefix + ":"):
            try:
                return int(tag[len(prefix) + 1 :])
            except ValueError:
                pass
    return 0


def _sort_gt_items(
    items: list[ArticleItem], key: str, *, filter_ranking: bool = True
) -> list[ArticleItem]:
    """GitHub Trending アイテムを指定のスター数キーで降順ソート

    filter_ranking=True の場合、対応する ranking:* タグを持つアイテムのみ返す。
    例: key="stars_daily" → ranking:daily タグがあるアイテムのみ。
    """
    if filter_ranking:
        # stars_daily → daily, stars_weekly → weekly, etc.
        period = key.replace("stars_", "")
        ranking_tag = f"ranking:{period}"
        items = [it for it in items if ranking_tag in it.tags]
    sorted_items = sorted(
        items, key=lambda it: _extract_star_tag(it, key), reverse=True
    )
    return sorted_items[:10]
