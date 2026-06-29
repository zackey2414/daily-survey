"""
検索テーマ ルーター
- /themes              : テーマ一覧 + 管理 UI
- /themes/{theme_id}   : テーマ別の収集結果（日付横断）
- /admin/themes/*      : テーマ CRUD・オンデマンド検索（HTMX）
"""

import asyncio
import logging
from datetime import date, datetime, timedelta

import pytz
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Favorite
from app.jinja import templates
from app.services import themes as themes_svc
from app.services.theme_search import (
    collect_theme,
    load_all_theme_stats,
    load_theme_results,
    save_theme_collection,
)

logger = logging.getLogger(__name__)
JST = pytz.timezone("Asia/Tokyo")

router = APIRouter()

_MAX_ONDEMAND_DAYS = 31


def _theme_stats(themes: list) -> dict[str, dict]:
    """各テーマの収集論文数・最終収集日・収集日数を集計する（一覧バッジ用）。

    全日付ディレクトリを1回だけ走査する load_all_theme_stats に委譲する。
    """
    return load_all_theme_stats([t.id for t in themes])


# ── 表示ページ ────────────────────────────────────────────────


@router.get("/themes", response_class=HTMLResponse)
async def themes_page(request: Request):
    themes = themes_svc.load_themes()
    return templates.TemplateResponse(
        "pages/themes_list.html",
        {
            "request": request,
            "themes": themes,
            "theme_stats": _theme_stats(themes),
            "max_themes": themes_svc.MAX_THEMES,
            "max_keywords": themes_svc.MAX_KEYWORDS,
            "default_to": datetime.now(JST).date().isoformat(),
            "default_from": (datetime.now(JST).date() - timedelta(days=7)).isoformat(),
        },
    )


@router.get("/themes/{theme_id}", response_class=HTMLResponse)
async def theme_detail(
    request: Request, theme_id: str, db: AsyncSession = Depends(get_db)
):
    theme = themes_svc.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="テーマが見つかりません。")
    # 0 件の日（検索したが該当なし）は表示から除外。これにより詳細ページの
    # 「最新日を開く」折りたたみが常に実データのある最新日を指す。
    collections = [c for c in load_theme_results(theme_id) if c.items]
    total = sum(c.total for c in collections)

    # 表示記事のうちお気に入り登録済みの ID を取得（スター初期状態用）
    article_ids = [item.id for c in collections for item in c.items]
    favorite_ids: set[str] = set()
    if article_ids:
        fav_stmt = select(Favorite.article_id).where(
            Favorite.article_id.in_(article_ids)
        )
        favorite_ids = {row[0] for row in (await db.execute(fav_stmt)).all()}

    return templates.TemplateResponse(
        "pages/theme_detail.html",
        {
            "request": request,
            "theme": theme,
            "collections": collections,
            "total": total,
            "favorite_ids": favorite_ids,
        },
    )


# ── HTMX フラグメント ─────────────────────────────────────────


def _themes_list_fragment(request: Request) -> HTMLResponse:
    themes = themes_svc.load_themes()
    return templates.TemplateResponse(
        "components/theme/list.html",
        {
            "request": request,
            "themes": themes,
            "theme_stats": _theme_stats(themes),
            "max_keywords": themes_svc.MAX_KEYWORDS,
            "default_to": datetime.now(JST).date().isoformat(),
            "default_from": (datetime.now(JST).date() - timedelta(days=7)).isoformat(),
        },
    )


def _keywords_fragment(request: Request, theme) -> HTMLResponse:
    return templates.TemplateResponse(
        "components/theme/keywords.html",
        {"request": request, "theme": theme},
    )


@router.get("/admin/themes", response_class=HTMLResponse)
async def admin_list_themes(request: Request):
    return _themes_list_fragment(request)


@router.post("/admin/themes", response_class=HTMLResponse)
async def admin_create_theme(request: Request):
    form = await request.form()
    name = str(form.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="テーマ名を入力してください。")
    if themes_svc.count_enabled_themes() >= themes_svc.MAX_THEMES:
        raise HTTPException(
            status_code=400,
            detail=f"テーマ数の上限（{themes_svc.MAX_THEMES}）に達しています。",
        )
    # Gemini で関連キーワードを生成。失敗時はテーマ名のみで登録。
    keywords = await themes_svc.generate_keywords(name)
    if not keywords:
        keywords = [name]
    themes_svc.add_theme(name, keywords)
    return _themes_list_fragment(request)


@router.delete("/admin/themes/{theme_id}", response_class=HTMLResponse)
async def admin_delete_theme(request: Request, theme_id: str):
    themes_svc.delete_theme(theme_id)
    return _themes_list_fragment(request)


@router.post("/admin/themes/{theme_id}/toggle", response_class=HTMLResponse)
async def admin_toggle_theme(request: Request, theme_id: str):
    theme = themes_svc.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="テーマが見つかりません。")
    # 有効化する場合は上限チェック
    if not theme.enabled and themes_svc.count_enabled_themes() >= themes_svc.MAX_THEMES:
        raise HTTPException(
            status_code=400,
            detail=f"有効テーマ数の上限（{themes_svc.MAX_THEMES}）に達しています。",
        )
    themes_svc.set_theme_enabled(theme_id, not theme.enabled)
    return _themes_list_fragment(request)


@router.post("/admin/themes/{theme_id}/keywords", response_class=HTMLResponse)
async def admin_add_keyword(request: Request, theme_id: str):
    form = await request.form()
    keyword = str(form.get("keyword", "")).strip()
    theme = themes_svc.add_keyword(theme_id, keyword) if keyword else None
    if theme is None:
        theme = themes_svc.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="テーマが見つかりません。")
    return _keywords_fragment(request, theme)


@router.delete("/admin/themes/{theme_id}/keywords/{index}", response_class=HTMLResponse)
async def admin_remove_keyword(request: Request, theme_id: str, index: int):
    theme = themes_svc.remove_keyword_at(theme_id, index)
    if theme is None:
        raise HTTPException(status_code=404, detail="テーマが見つかりません。")
    return _keywords_fragment(request, theme)


@router.post("/admin/themes/{theme_id}/search")
async def admin_ondemand_search(request: Request, theme_id: str):
    """オンデマンド検索: 指定期間（収集日範囲）でテーマ検索を実行する。"""
    theme = themes_svc.get_theme(theme_id)
    if theme is None:
        raise HTTPException(status_code=404, detail="テーマが見つかりません。")

    form = await request.form()
    from_str = str(form.get("date_from", "")).strip()
    to_str = str(form.get("date_to", "")).strip()
    try:
        date_from = date.fromisoformat(from_str)
        date_to = date.fromisoformat(to_str)
    except ValueError:
        return JSONResponse({"error": "日付の形式が不正です。"}, status_code=400)
    if date_from > date_to:
        return JSONResponse(
            {"error": "開始日は終了日以前にしてください。"}, status_code=400
        )
    span = (date_to - date_from).days + 1
    if span > _MAX_ONDEMAND_DAYS:
        return JSONResponse(
            {"error": f"期間は最大 {_MAX_ONDEMAND_DAYS} 日までです。"},
            status_code=400,
        )

    from app.services.tasks import spawn

    spawn(
        _run_ondemand(theme, date_from, date_to),
        name=f"theme-ondemand:{theme.id}:{from_str}_{to_str}",
    )

    msg = (
        f"テーマ「{theme.name}」を {from_str}〜{to_str} で検索開始しました"
        "（バックグラウンド実行）"
    )
    if "hx-request" in request.headers:
        return HTMLResponse(f'<span class="text-emerald-600 text-xs">✓ {msg}</span>')
    return {"message": msg}


async def _run_ondemand(theme, date_from: date, date_to: date) -> None:
    """収集日範囲を1日ずつテーマ検索して保存する。"""
    collection_date = date_from
    while collection_date <= date_to:
        target_date = collection_date - timedelta(days=1)
        try:
            tc = await collect_theme(theme, target_date)
            save_theme_collection(collection_date.isoformat(), theme.id, tc)
            logger.info(
                f"オンデマンド検索: {theme.name} / {collection_date} → {tc.total} 件"
            )
        except Exception as e:
            logger.error(
                f"オンデマンド検索失敗 ({theme.name} / {collection_date}): {e}"
            )
        await asyncio.sleep(3)  # arXiv レートリミット配慮
        collection_date += timedelta(days=1)
