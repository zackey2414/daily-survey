"""
お気に入りルーター
- POST /favorites/{article_id} : お気に入りトグル（HTMX、スター自身を outerHTML 入れ替え）
- GET  /favorites/            : お気に入り記事一覧ページ
"""

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.db.models import Favorite
from app.jinja import templates
from app.routers.tags import CATEGORY_META as _BASE_META, CATEGORY_ORDER as _BASE_ORDER
from app.routers.user_tags import _get_or_create_article, _safe_id
from app.schemas import ArticleItem, ThemeCollection
from app.services.pipeline import load_daily_data, list_available_dates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/favorites")

# タグ別ページのカテゴリ定義に、お気に入り一覧で扱う追加カテゴリ（テーマ別論文・
# OpenReview）を足して使う。テーマ別論文を先頭に表示する。
CATEGORY_META = {
    "theme": {"icon": "🎯", "title": "テーマ別論文", "is_paper": True},
    **_BASE_META,
    "openreview": {"icon": "📝", "title": "OpenReview", "is_paper": True},
}
CATEGORY_ORDER = ["theme"] + list(_BASE_ORDER) + ["openreview"]


async def _render_star(
    request: Request, article_id: str, is_favorite: bool
) -> HTMLResponse:
    return templates.TemplateResponse(
        "components/favorite/star.html",
        {
            "request": request,
            "article_id": article_id,
            "safe_id": _safe_id(article_id),
            "is_favorite": is_favorite,
        },
    )


@router.post("/{article_id:path}", response_class=HTMLResponse)
async def toggle_favorite(
    request: Request,
    article_id: str,
    db: AsyncSession = Depends(get_db),
):
    """お気に入り登録/解除をトグルし、更新後のスターボタンを返す。"""
    stmt = select(Favorite).where(Favorite.article_id == article_id)
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        # 冪等な一括削除。同一記事への同時クリックで 0 行 DELETE になっても
        # StaleDataError を起こさない（ORM の delete(existing) は 0 行で例外）。
        await db.execute(delete(Favorite).where(Favorite.article_id == article_id))
        await db.commit()
        return await _render_star(request, article_id, is_favorite=False)

    # 未登録 → 登録。FK のため記事メタを必要なら JSON から復元して登録する。
    article = await _get_or_create_article(article_id, db)
    if not article:
        # 表示中の記事なら通常ここには来ない（テーマ別論文も復元対象）。
        logger.warning(
            "お気に入り登録: 記事が見つかりません (article_id=%s)", article_id
        )
        return await _render_star(request, article_id, is_favorite=False)

    try:
        db.add(Favorite(article_id=article_id))
        await db.commit()
    except Exception:
        await db.rollback()  # 競合（既に登録済み）などは無視
    return await _render_star(request, article_id, is_favorite=True)


@router.get("/", response_class=HTMLResponse)
async def favorites_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """お気に入り登録した記事を全期間・全カテゴリから横断表示する。"""
    favorite_ids: set[str] = {
        row[0] for row in (await db.execute(select(Favorite.article_id))).all()
    }

    results: dict[str, list[tuple[str, ArticleItem]]] = {
        cat: [] for cat in CATEGORY_ORDER
    }
    seen_ids: set[str] = set()

    if favorite_ids:
        for date_str in list_available_dates():  # 降順
            data = load_daily_data(date_str)
            for cat in _BASE_ORDER + ["openreview"]:
                for item in data.get(cat, []):
                    if item.id in seen_ids or item.id not in favorite_ids:
                        continue
                    results[cat].append((date_str, item))
                    seen_ids.add(item.id)
            # テーマ別論文（メインカテゴリに無いものを拾う）。テーマの有効/無効に
            # かかわらず登録済みお気に入りを表示するため、テーマJSONを直接走査する。
            themes_dir = settings.data_dir / date_str / "themes"
            if themes_dir.is_dir():
                for theme_file in sorted(themes_dir.glob("*.json")):
                    try:
                        tc = ThemeCollection.model_validate_json(
                            theme_file.read_text(encoding="utf-8")
                        )
                    except Exception:
                        continue
                    for item in tc.items:
                        if item.id in seen_ids or item.id not in favorite_ids:
                            continue
                        results["theme"].append((date_str, item))
                        seen_ids.add(item.id)

    total = sum(len(v) for v in results.values())

    return templates.TemplateResponse(
        "pages/favorites.html",
        {
            "request": request,
            "results": results,
            "total": total,
            "favorite_ids": favorite_ids,
            "category_meta": CATEGORY_META,
            "category_order": CATEGORY_ORDER,
        },
    )
