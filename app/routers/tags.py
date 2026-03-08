"""
タグ検索ルーター
/tags/{tag_name} : 指定タグを持つ記事を日付降順で表示
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import UserTag
from app.jinja import templates
from app.services.pipeline import load_daily_data, list_available_dates
from app.schemas import ArticleItem

router = APIRouter(prefix="/tags")

# カテゴリ表示名マッピング
CATEGORY_META = {
    "cv": {"icon": "🖼️", "title": "CV 論文", "is_paper": True},
    "lg": {"icon": "📈", "title": "機械学習論文 (cs.LG)", "is_paper": True},
    "ai": {"icon": "🤖", "title": "AI 論文 (cs.AI)", "is_paper": True},
    "cl": {"icon": "💬", "title": "自然言語処理 (cs.CL)", "is_paper": True},
    "industry": {"icon": "🏢", "title": "AI 企業動向（自社発表）", "is_paper": False},
    "industry_news": {
        "icon": "📰",
        "title": "AI 企業動向（その他報道）",
        "is_paper": False,
    },
    "community": {"icon": "🗣️", "title": "SNS・コミュニティ", "is_paper": False},
    "python": {
        "icon": "🐍",
        "title": "Python 情報（GitHub Trending）",
        "is_paper": False,
    },
}

CATEGORY_ORDER = [
    "cv",
    "lg",
    "ai",
    "cl",
    "industry",
    "industry_news",
    "community",
    "python",
]


@router.get("/{tag_name}", response_class=HTMLResponse)
async def tag_search(
    request: Request,
    tag_name: str,
    db: AsyncSession = Depends(get_db),
):
    """指定タグを持つ記事を全日付から検索して表示する"""
    all_dates = list_available_dates()  # 降順

    # DB からユーザータグでこのタグを持つ記事 ID を取得
    stmt = select(UserTag.article_id).where(UserTag.tag == tag_name)
    result = await db.execute(stmt)
    user_tagged_ids: set[str] = {row[0] for row in result.all()}

    # カテゴリ別にマッチした記事を収集（日付降順を維持）
    results: dict[str, list[tuple[str, ArticleItem]]] = {
        cat: [] for cat in CATEGORY_ORDER
    }
    seen_ids: set[str] = set()  # 重複防止

    for date_str in all_dates:
        data = load_daily_data(date_str)
        for cat in CATEGORY_ORDER:
            for item in data.get(cat, []):
                if item.id in seen_ids:
                    continue
                if tag_name in item.hashtags or item.id in user_tagged_ids:
                    results[cat].append((date_str, item))
                    seen_ids.add(item.id)

    # 各カテゴリで合計件数を計算
    total = sum(len(v) for v in results.values())

    return templates.TemplateResponse(
        "pages/tags.html",
        {
            "request": request,
            "tag_name": tag_name,
            "results": results,
            "total": total,
            "category_meta": CATEGORY_META,
            "category_order": CATEGORY_ORDER,
        },
    )


@router.get("/", response_class=HTMLResponse)
async def all_tags(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """全タグ一覧ページ（AI タグとユーザータグを分離して表示）"""
    all_dates = list_available_dates()
    ai_tag_counts: dict[str, int] = {}

    for date_str in all_dates:
        data = load_daily_data(date_str)
        for cat in CATEGORY_ORDER:
            for item in data.get(cat, []):
                for tag in item.hashtags:
                    ai_tag_counts[tag] = ai_tag_counts.get(tag, 0) + 1

    # DB のユーザータグを別途取得
    stmt = select(UserTag.tag, func.count(UserTag.id)).group_by(UserTag.tag)
    result = await db.execute(stmt)
    user_tag_counts: dict[str, int] = {tag: count for tag, count in result.all()}

    # 出現回数降順でソート
    sorted_ai_tags = sorted(ai_tag_counts.items(), key=lambda x: x[1], reverse=True)
    sorted_user_tags = sorted(user_tag_counts.items(), key=lambda x: x[1], reverse=True)

    return templates.TemplateResponse(
        "pages/tags_list.html",
        {
            "request": request,
            "ai_tags": sorted_ai_tags,
            "user_tags": sorted_user_tags,
            # 後方互換: 旧テンプレート変数も維持
            "tags": sorted_ai_tags,
        },
    )
