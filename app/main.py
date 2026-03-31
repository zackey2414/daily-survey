"""
FastAPI アプリケーションのエントリポイント
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.database import init_db, migrate_db
from app.jinja import templates
from app.routers import archive, chat, daily_chat, main_page, summaries, tags, user_tags
from app.scheduler import start_scheduler, stop_scheduler

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            settings.log_dir / "app.log" if settings.log_dir.exists() else "app.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.summaries_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    await init_db()
    await migrate_db()
    start_scheduler()
    logger.info("AI Daily Survey 起動完了")
    yield
    # 終了時
    stop_scheduler()
    logger.info("AI Daily Survey 停止")


app = FastAPI(
    title="AI Daily Survey",
    description="毎日の AI 動向を1ページでチェック",
    version="1.0.0",
    lifespan=lifespan,
)

# ルーター登録
app.include_router(main_page.router)
app.include_router(tags.router)
app.include_router(archive.router)
app.include_router(summaries.router)
app.include_router(chat.router)
app.include_router(daily_chat.router)
app.include_router(user_tags.router)


# 手動実行エンドポイント（デバッグ・テスト用）
@app.post("/admin/run-pipeline")
async def manual_run_pipeline(date_str: str | None = None):
    """パイプラインを手動実行する（管理用）"""
    import asyncio
    from datetime import date, timedelta, datetime
    import pytz
    from app.services.pipeline import run_daily_pipeline

    JST = pytz.timezone("Asia/Tokyo")

    if date_str:
        try:
            collection_date = date.fromisoformat(date_str)
        except ValueError:
            return JSONResponse({"error": "Invalid date format"}, status_code=400)
    else:
        collection_date = datetime.now(JST).date()

    target_date = collection_date - timedelta(days=1)
    asyncio.create_task(run_daily_pipeline(collection_date))
    return {
        "message": (
            f"収集日 {collection_date.isoformat()} / 対象日 {target_date.isoformat()} "
            "のパイプラインを非同期で開始しました"
        )
    }


@app.post("/admin/reprocess-summaries")
async def reprocess_summaries(date_str: str | None = None):
    """既存 JSON の summarized=false なアイテムだけ再要約する（収集はスキップ）"""
    import asyncio
    from datetime import datetime
    import pytz
    from app.services.pipeline import load_daily_data, _save_collection
    from app.services.summarizer import summarize_items

    JST = pytz.timezone("Asia/Tokyo")
    if not date_str:
        date_str = datetime.now(JST).date().isoformat()

    async def _run():
        data = load_daily_data(date_str)
        # target_date_str は JSON の date フィールドから取得
        from app.config import settings
        import json

        first_json = settings.data_dir / date_str / "papers_cv.json"
        target_date_str = date_str  # フォールバック
        if first_json.exists():
            raw = json.loads(first_json.read_text())
            target_date_str = raw.get("date", date_str)

        paper_cats = ["cv", "lg", "ai", "cl"]
        article_cats = ["industry", "industry_news", "community", "github_trending"]
        tasks = [summarize_items(data[c], "paper") for c in paper_cats] + [
            summarize_items(data[c], "article") for c in article_cats
        ]
        results = await asyncio.gather(*tasks)
        all_cats = paper_cats + article_cats
        for cat, items in zip(all_cats, results):
            _save_collection(date_str, target_date_str, cat, items)
        return sum(len(r) for r in results)

    asyncio.create_task(_run())
    return {"message": f"{date_str} の再要約を開始しました（バックグラウンド実行）"}


def _render_keywords_html(keywords: list[str]) -> str:
    """キーワード一覧の HTML フラグメントを生成"""
    tags = []
    for kw in keywords:
        tags.append(
            f'<span class="inline-flex items-center gap-1 text-xs bg-emerald-50 text-emerald-700 '
            f'ring-1 ring-emerald-200 px-2.5 py-1 rounded-full">'
            f"{kw}"
            f'<button hx-delete="/admin/github-trending-keywords/{kw}" '
            f'hx-target="#gt-keywords-container" hx-swap="innerHTML" '
            f'class="text-emerald-400 hover:text-red-500 ml-0.5 font-bold">×</button>'
            f"</span>"
        )
    return f'<div class="flex flex-wrap gap-1.5">{"".join(tags)}</div>'


@app.get("/admin/github-trending-keywords")
async def get_github_trending_keywords(request: Request):
    """GitHub Trending のフィルタキーワード一覧を取得"""
    from app.services.collector.github_trending import load_keywords

    keywords = load_keywords()
    if "hx-request" in request.headers:
        from fastapi.responses import HTMLResponse

        return HTMLResponse(_render_keywords_html(keywords))
    return {"keywords": keywords}


@app.post("/admin/github-trending-keywords")
async def add_github_trending_keyword(request: Request, keyword: str = ""):
    """GitHub Trending のフィルタキーワードを追加"""
    from app.services.collector.github_trending import load_keywords, save_keywords

    # HTMX form の場合は form data から取得
    if "hx-request" in request.headers:
        form = await request.form()
        keyword = str(form.get("keyword", keyword))
    keywords = load_keywords()
    kw = keyword.strip()
    if kw and kw not in keywords:
        keywords.append(kw)
        save_keywords(keywords)
    if "hx-request" in request.headers:
        from fastapi.responses import HTMLResponse

        return HTMLResponse(_render_keywords_html(keywords))
    return {"keywords": keywords}


@app.delete("/admin/github-trending-keywords/{keyword}")
async def delete_github_trending_keyword(request: Request, keyword: str):
    """GitHub Trending のフィルタキーワードを削除"""
    from app.services.collector.github_trending import load_keywords, save_keywords

    keywords = load_keywords()
    kw = keyword.strip()
    keywords = [k for k in keywords if k != kw]
    save_keywords(keywords)
    if "hx-request" in request.headers:
        from fastapi.responses import HTMLResponse

        return HTMLResponse(_render_keywords_html(keywords))
    return {"keywords": keywords}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        "pages/error.html",
        {"request": request, "status_code": 404, "message": "ページが見つかりません"},
        status_code=404,
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return templates.TemplateResponse(
        "pages/error.html",
        {
            "request": request,
            "status_code": 500,
            "message": "サーバーエラーが発生しました",
        },
        status_code=500,
    )
