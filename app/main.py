"""
FastAPI アプリケーションのエントリポイント
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db.database import init_db
from app.routers import archive, chat, main_page, summaries, tags
from app.scheduler import start_scheduler, stop_scheduler

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            settings.log_dir / "app.log" if settings.log_dir.exists()
            else "app.log",
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


templates = Jinja2Templates(directory="app/templates")


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "status_code": 404, "message": "ページが見つかりません"},
        status_code=404,
    )


@app.exception_handler(500)
async def server_error_handler(request: Request, exc):
    return templates.TemplateResponse(
        "error.html",
        {"request": request, "status_code": 500, "message": "サーバーエラーが発生しました"},
        status_code=500,
    )
