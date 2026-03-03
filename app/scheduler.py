"""
APScheduler による定期実行スケジューラ
毎日 JST 09:00 に日次パイプラインを実行する
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")


async def _run_pipeline_job() -> None:
    """スケジューラから呼び出されるジョブ"""
    from app.services.pipeline import run_daily_pipeline
    logger.info("スケジューラ: 日次パイプライン実行開始")
    try:
        await run_daily_pipeline()
    except Exception as e:
        logger.error(f"スケジューラ: パイプライン実行失敗: {e}")


def start_scheduler() -> None:
    """スケジューラを開始する（FastAPI lifespan から呼ぶ）"""
    scheduler.add_job(
        _run_pipeline_job,
        trigger=CronTrigger(
            hour=settings.schedule_hour,
            minute=settings.schedule_minute,
            timezone="Asia/Tokyo",
        ),
        id="daily_pipeline",
        name="AI Daily Survey Pipeline",
        replace_existing=True,
        misfire_grace_time=3600,  # 1 時間以内のズレは実行
    )
    scheduler.start()
    logger.info(
        f"スケジューラ起動: 毎日 JST {settings.schedule_hour:02d}:{settings.schedule_minute:02d} に実行"
    )


def stop_scheduler() -> None:
    """スケジューラを停止する"""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("スケジューラ停止")
