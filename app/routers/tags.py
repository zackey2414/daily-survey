"""
タグ検索ルーター
/tags/{tag_name} : 指定タグを持つ記事を日付降順で表示
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.pipeline import load_daily_data, list_available_dates
from app.schemas import ArticleItem

router = APIRouter(prefix="/tags")
templates = Jinja2Templates(directory="app/templates")

# カテゴリ表示名マッピング
CATEGORY_META = {
    "cv":        {"icon": "🖼️",  "title": "CV 論文",              "is_paper": True},
    "lg":        {"icon": "📈",  "title": "機械学習論文 (cs.LG)",  "is_paper": True},
    "ai":        {"icon": "🤖",  "title": "AI 論文 (cs.AI)",       "is_paper": True},
    "cl":        {"icon": "💬",  "title": "自然言語処理 (cs.CL)",  "is_paper": True},
    "industry":  {"icon": "🏢",  "title": "AI 企業動向",           "is_paper": False},
    "community": {"icon": "🗣️",  "title": "SNS・コミュニティ",     "is_paper": False},
    "python":    {"icon": "🐍",  "title": "Python 情報（GitHub Trending）", "is_paper": False},
}

CATEGORY_ORDER = ["cv", "lg", "ai", "cl", "industry", "community", "python"]


@router.get("/{tag_name}", response_class=HTMLResponse)
async def tag_search(request: Request, tag_name: str):
    """指定タグを持つ記事を全日付から検索して表示する"""
    all_dates = list_available_dates()  # 降順

    # カテゴリ別にマッチした記事を収集（日付降順を維持）
    results: dict[str, list[tuple[str, ArticleItem]]] = {cat: [] for cat in CATEGORY_ORDER}

    for date_str in all_dates:
        data = load_daily_data(date_str)
        for cat in CATEGORY_ORDER:
            for item in data.get(cat, []):
                if tag_name in item.hashtags:
                    results[cat].append((date_str, item))

    # 各カテゴリで合計件数を計算
    total = sum(len(v) for v in results.values())

    return templates.TemplateResponse(
        "tags.html",
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
async def all_tags(request: Request):
    """全タグ一覧ページ"""
    all_dates = list_available_dates()
    tag_counts: dict[str, int] = {}

    for date_str in all_dates:
        data = load_daily_data(date_str)
        for cat in CATEGORY_ORDER:
            for item in data.get(cat, []):
                for tag in item.hashtags:
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

    # 出現回数降順でソート
    sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)

    return templates.TemplateResponse(
        "tags_list.html",
        {
            "request": request,
            "tags": sorted_tags,
        },
    )
