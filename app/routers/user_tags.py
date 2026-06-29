"""
ユーザータグ CRUD ルーター (HTMX 対応)
- POST   /user-tags/{article_id}       : タグ追加
- DELETE /user-tags/{article_id}/{tag} : タグ削除
"""

import json
import logging
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.db.models import Article, UserTag
from app.jinja import templates
from app.schemas import DailyCollection, ThemeCollection
from app.services.pipeline import list_available_dates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user-tags")

TAG_RE = re.compile(r"^[\w\u3000-\u9FFF\-]+$")


async def _get_or_create_article(article_id: str, db: AsyncSession) -> Article | None:
    article = await db.get(Article, article_id)
    if article:
        return article

    categories = [
        "cv",
        "openreview",
        "lg",
        "ai",
        "cl",
        "industry",
        "industry_news",
        "community",
        "github_trending",
        "ai_dev",
        "python",
    ]
    for date_str in list_available_dates():
        for category in categories:
            file_path = settings.data_dir / date_str / f"papers_{category}.json"
            if not file_path.exists():
                continue
            try:
                raw = json.loads(file_path.read_text(encoding="utf-8"))
                collection = DailyCollection.model_validate(raw)
                item = next(
                    (it for it in collection.items if it.id == article_id), None
                )
                if item:
                    article = Article(
                        id=item.id,
                        date=date_str,
                        category=category,
                        title_ja=item.title_ja or item.title_en or "",
                        title_en=item.title_en or "",
                        url=item.url or "",
                        summary_ja=item.summary_ja or "",
                    )
                    db.add(article)
                    await db.commit()
                    await db.refresh(article)
                    return article
            except Exception as e:
                logger.warning(f"JSON 検索中にエラー ({file_path}): {e}")
                continue

        # テーマ別検索でのみ取得した論文（papers_*.json に存在しない）も対象にする。
        # data/{date}/themes/{theme_id}.json を走査する。
        themes_dir = settings.data_dir / date_str / "themes"
        if themes_dir.is_dir():
            for theme_file in sorted(themes_dir.glob("*.json")):
                try:
                    tc = ThemeCollection.model_validate_json(
                        theme_file.read_text(encoding="utf-8")
                    )
                    item = next((it for it in tc.items if it.id == article_id), None)
                    if item:
                        article = Article(
                            id=item.id,
                            date=date_str,
                            category="theme",
                            title_ja=item.title_ja or item.title_en or "",
                            title_en=item.title_en or "",
                            url=item.url or "",
                            summary_ja=item.summary_ja or "",
                        )
                        db.add(article)
                        await db.commit()
                        await db.refresh(article)
                        return article
                except Exception as e:
                    logger.warning(f"テーマ JSON 検索中にエラー ({theme_file}): {e}")
                    continue
    return None


async def _get_user_tags(article_id: str, db: AsyncSession) -> list[str]:
    stmt = (
        select(UserTag.tag)
        .where(UserTag.article_id == article_id)
        .order_by(UserTag.created_at)
    )
    result = await db.execute(stmt)
    return [row[0] for row in result.all()]


def _safe_id(article_id: str) -> str:
    return article_id.replace(":", "-").replace("/", "-").replace(".", "-")


@router.post("/{article_id:path}", response_class=HTMLResponse)
async def add_tag(
    request: Request,
    article_id: str,
    tag: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    tag = tag.strip()
    if not tag:
        return HTMLResponse(
            '<span class="text-red-500 text-xs px-1">タグを入力してください</span>'
        )
    if len(tag) > 50:
        return HTMLResponse(
            '<span class="text-red-500 text-xs px-1">50文字以内で入力してください</span>'
        )
    if not TAG_RE.match(tag):
        return HTMLResponse(
            '<span class="text-red-500 text-xs px-1">使用できない文字が含まれています</span>'
        )

    article = await _get_or_create_article(article_id, db)
    if not article:
        return HTMLResponse(
            '<span class="text-red-500 text-xs px-1">記事が見つかりません</span>'
        )

    try:
        db.add(UserTag(article_id=article_id, tag=tag))
        await db.commit()
    except Exception:
        await db.rollback()  # 重複等

    user_tags = await _get_user_tags(article_id, db)
    return templates.TemplateResponse(
        "components/tags/user_tags.html",
        {
            "request": request,
            "article_id": article_id,
            "safe_id": _safe_id(article_id),
            "user_tags": user_tags,
        },
    )


@router.delete("/{article_id:path}/{tag}", response_class=HTMLResponse)
async def delete_tag(
    request: Request,
    article_id: str,
    tag: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(UserTag).where(UserTag.article_id == article_id, UserTag.tag == tag)
    result = await db.execute(stmt)
    user_tag = result.scalar_one_or_none()
    if user_tag:
        await db.delete(user_tag)
        await db.commit()

    user_tags = await _get_user_tags(article_id, db)
    return templates.TemplateResponse(
        "components/tags/user_tags.html",
        {
            "request": request,
            "article_id": article_id,
            "safe_id": _safe_id(article_id),
            "user_tags": user_tags,
        },
    )
