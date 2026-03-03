"""
日次収集パイプライン
収集 → 要約 → JSON 保存 → ダイジェスト生成 → メール通知 を統括する
"""
import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytz

JST = pytz.timezone("Asia/Tokyo")

from app.config import settings
from app.schemas import ArticleItem, DailyCollection
from app.services.collector.arxiv import collect_all_arxiv
from app.services.collector.openreview import collect_openreview
from app.services.collector.industry import collect_industry
from app.services.collector.community import collect_community
from app.services.collector.python_news import collect_python_news
from app.services.summarizer import summarize_items
from app.services.digest import generate_digest, load_digest
from app.services.notifier import CollectionReport, send_completion_email

logger = logging.getLogger(__name__)


async def run_daily_pipeline(collection_date: date | None = None) -> None:
    """毎朝 09:00 に実行されるメインパイプライン"""
    start_time = time.monotonic()

    if collection_date is None:
        collection_date = datetime.now(JST).date()

    target_date = collection_date - timedelta(days=1)
    collection_date_str = collection_date.isoformat()
    target_date_str = target_date.isoformat()

    logger.info(
        f"=== 日次パイプライン開始: 収集日 {collection_date_str} / 対象日 {target_date_str} ==="
    )

    report = CollectionReport(date_str=collection_date_str)
    errors: list[str] = []

    # ── 1. 並列収集 ────────────────────────────────────────────
    logger.info("収集開始...")
    arxiv_task = collect_all_arxiv(target_date)
    openreview_task = collect_openreview(target_date)
    industry_task = collect_industry(target_date)
    community_task = collect_community(target_date)
    python_task = collect_python_news(target_date)

    (
        arxiv_results,
        openreview_items,
        industry_items,
        community_items,
        python_items,
    ) = await asyncio.gather(
        arxiv_task, openreview_task, industry_task, community_task, python_task,
        return_exceptions=True,
    )

    # 例外処理
    def _safe(result, name: str, default):
        if isinstance(result, Exception):
            errors.append(f"{name}: {result}")
            logger.error(f"{name} 収集失敗: {result}")
            return default
        return result

    arxiv_results = _safe(arxiv_results, "arXiv", {"cs.CV": [], "cs.LG": [], "cs.AI": [], "cs.CL": []})
    openreview_items = _safe(openreview_items, "OpenReview", [])
    industry_items = _safe(industry_items, "Industry", [])
    community_items = _safe(community_items, "Community", [])
    python_items = _safe(python_items, "Python", [])

    cv_papers = arxiv_results.get("cs.CV", []) + openreview_items
    lg_papers = arxiv_results.get("cs.LG", [])
    ai_papers = arxiv_results.get("cs.AI", [])
    cl_papers = arxiv_results.get("cs.CL", [])

    # ── 2. 並列要約 ────────────────────────────────────────────
    logger.info("要約開始...")
    (
        cv_papers,
        lg_papers,
        ai_papers,
        cl_papers,
        industry_items,
        community_items,
        python_items,
    ) = await asyncio.gather(
        summarize_items(cv_papers, "paper"),
        summarize_items(lg_papers, "paper"),
        summarize_items(ai_papers, "paper"),
        summarize_items(cl_papers, "paper"),
        summarize_items(industry_items, "article"),
        summarize_items(community_items, "article"),
        summarize_items(python_items, "article"),
    )

    # ── 3. JSON 保存 ────────────────────────────────────────────
    logger.info("JSON 保存開始...")
    _save_collection(collection_date_str, target_date_str, "cv", cv_papers)
    _save_collection(collection_date_str, target_date_str, "lg", lg_papers)
    _save_collection(collection_date_str, target_date_str, "ai", ai_papers)
    _save_collection(collection_date_str, target_date_str, "cl", cl_papers)
    _save_collection(collection_date_str, target_date_str, "industry", industry_items)
    _save_collection(collection_date_str, target_date_str, "community", community_items)
    _save_collection(collection_date_str, target_date_str, "python", python_items)

    # 収集件数を記録
    report.counts = {
        "CV 論文 (arXiv + OpenReview)": len(cv_papers),
        "機械学習 (cs.LG)": len(lg_papers),
        "AI (cs.AI)": len(ai_papers),
        "自然言語処理 (cs.CL)": len(cl_papers),
        "企業動向": len(industry_items),
        "コミュニティ": len(community_items),
        "Python 情報": len(python_items),
    }

    # DB に記事を登録（チャット機能のため）
    await _register_articles_to_db(
        collection_date_str,
        cv_papers, lg_papers, ai_papers, cl_papers,
        industry_items, community_items, python_items,
    )

    # ── 4. ダイジェスト生成 ────────────────────────────────────
    logger.info("ダイジェスト生成開始...")
    try:
        digest_path = await generate_digest(
            collection_date_str,
            cv_papers, lg_papers, ai_papers, cl_papers,
            industry_items, community_items, python_items,
            target_date_str=target_date_str,
        )
        digest_content = load_digest(collection_date_str) or ""
        report.digest_preview = digest_content[:500]
    except Exception as e:
        errors.append(f"ダイジェスト生成: {e}")
        logger.error(f"ダイジェスト生成失敗: {e}")

    # ── 5. メール通知 ───────────────────────────────────────────
    report.errors = errors
    report.elapsed_seconds = time.monotonic() - start_time
    await send_completion_email(report)

    elapsed_min = report.elapsed_seconds / 60
    logger.info(
        f"=== 日次パイプライン完了: 収集日 {collection_date_str} / 対象日 {target_date_str} "
        f"({elapsed_min:.1f} 分) ==="
    )


def _save_collection(
    collection_date_str: str,
    target_date_str: str,
    category: str,
    items: list[ArticleItem],
) -> None:
    """アイテムリストを JSON ファイルに保存する"""
    from datetime import datetime, timezone
    day_dir = settings.data_dir / collection_date_str
    day_dir.mkdir(parents=True, exist_ok=True)

    collection = DailyCollection(
        date=target_date_str,
        collection_date=collection_date_str,
        category=category,
        collected_at=datetime.now(timezone.utc).isoformat(),
        items=items,
    )
    file_path = day_dir / f"papers_{category}.json"
    file_path.write_text(
        collection.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
    logger.info(f"保存: {file_path} ({len(items)} 件)")


async def _register_articles_to_db(
    date_str: str,
    *categories_items: list[ArticleItem],
) -> None:
    """収集した記事を SQLite に登録する（チャット機能のため）"""
    from app.db.database import AsyncSessionLocal
    from app.db.models import Article
    from sqlalchemy import select

    category_names = ["cv", "lg", "ai", "cl", "industry", "community", "python"]

    async with AsyncSessionLocal() as session:
        for category, items in zip(category_names, categories_items):
            for item in items:
                # 既存チェック
                existing = await session.get(Article, item.id)
                if existing:
                    continue
                article = Article(
                    id=item.id,
                    date=date_str,
                    category=category,
                    title_ja=item.title_ja or item.title_en,
                    title_en=item.title_en,
                    url=item.url,
                    summary_ja=item.summary_ja,
                )
                session.add(article)
        await session.commit()


def load_daily_data(date_str: str) -> dict[str, list[ArticleItem]]:
    """
    指定日の JSON ファイルを全カテゴリ読み込み、辞書で返す。
    キー: "cv", "lg", "ai", "cl", "industry", "community", "python"
    """
    categories = ["cv", "lg", "ai", "cl", "industry", "community", "python"]
    result: dict[str, list[ArticleItem]] = {}

    for cat in categories:
        file_path = settings.data_dir / date_str / f"papers_{cat}.json"
        if not file_path.exists():
            result[cat] = []
            continue
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
            collection = DailyCollection.model_validate(raw)
            result[cat] = collection.items
        except Exception as e:
            logger.warning(f"JSON 読み込み失敗 ({file_path}): {e}")
            result[cat] = []

    return result


def list_available_dates() -> list[str]:
    """収集データが存在する日付一覧（降順）"""
    data_dir = settings.data_dir
    if not data_dir.exists():
        return []
    dates = sorted(
        [d.name for d in data_dir.iterdir() if d.is_dir() and d.name.count("-") == 2],
        reverse=True,
    )
    return dates
