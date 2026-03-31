"""
アーカイブページルーター（過去日付の記事表示）
"""

import markdown as md
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import UserTag
from app.jinja import templates
from app.services.pipeline import load_daily_data, list_available_dates
from app.services.digest import load_digest, inject_citations

router = APIRouter(prefix="/archive")


@router.get("/{date_str}", response_class=HTMLResponse)
async def archive_day(
    request: Request, date_str: str, db: AsyncSession = Depends(get_db)
):
    # 日付フォーマット検証
    try:
        from datetime import date, timedelta

        collection_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

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
        "python",
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

    return templates.TemplateResponse(
        "pages/index.html",
        {
            "request": request,
            "date_str": date_str,
            "target_date_str": target_date_str,
            "is_today": False,
            "digest_html": digest_html,
            "cv_papers": data.get("cv", []),
            "openreview_papers": data.get("openreview", []),
            "lg_papers": data.get("lg", []),
            "ai_papers": data.get("ai", []),
            "cl_papers": data.get("cl", []),
            "industry_items": data.get("industry", []),
            "industry_news_items": data.get("industry_news", []),
            "community_items": data.get("community", []),
            "python_items": data.get("python", []),
            "available_dates": available_dates,
            "user_tags_by_id": user_tags_by_id,
        },
    )
