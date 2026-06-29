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
from typing import Literal

import pytz

from app.config import settings
from app.schemas import ArticleItem, DailyCollection, ThemeCollection
from app.services.collector.arxiv import collect_all_arxiv_serial
from app.services.collector.openreview import collect_openreview
from app.services.collector.industry import collect_industry
from app.services.collector.industry_news import collect_industry_news
from app.services.collector.community import collect_community
from app.services.collector.github_trending import collect_github_trending
from app.services.collector.ai_dev import collect_ai_dev
from app.services.summarizer import summarize_items
from app.services.digest import generate_digest, load_digest
from app.services.english_digest import generate_english_digest
from app.services.tts import synthesize_english_audio
from app.services.notifier import CollectionReport, send_completion_email

logger = logging.getLogger(__name__)
JST = pytz.timezone("Asia/Tokyo")


async def run_daily_pipeline(collection_date: date | None = None) -> None:
    """日次（既定 JST 12:00）に実行されるメインパイプライン"""
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

    # ── 1. 収集 ─────────────────────────────────────────────────
    logger.info("収集開始...")

    # arXiv は全カテゴリを1クライアントで直列収集（API レートリミット対策）
    cv_arxiv_papers: list[ArticleItem] = []
    arxiv_results: dict[str, list[ArticleItem]] = {}
    try:
        cv_arxiv_papers, arxiv_results = await collect_all_arxiv_serial(target_date)
    except Exception as e:
        errors.append(f"arXiv: {e}")
        logger.error(f"arXiv 収集失敗: {e}")

    # 他ソースも直列収集（並列実行によるレートリミット・リソース競合を回避）
    _INTER_SOURCE_DELAY = 3  # ソース間の待機秒数

    openreview_items: list[ArticleItem] = []
    try:
        openreview_items = await collect_openreview(target_date)
    except Exception as e:
        errors.append(f"OpenReview: {e}")
        logger.error(f"OpenReview 収集失敗: {e}")
    await asyncio.sleep(_INTER_SOURCE_DELAY)

    industry_items: list[ArticleItem] = []
    try:
        industry_items = await collect_industry(target_date)
    except Exception as e:
        errors.append(f"Industry: {e}")
        logger.error(f"Industry 収集失敗: {e}")
    await asyncio.sleep(_INTER_SOURCE_DELAY)

    industry_news_items: list[ArticleItem] = []
    try:
        industry_news_items = await collect_industry_news(target_date)
    except Exception as e:
        errors.append(f"Industry News: {e}")
        logger.error(f"Industry News 収集失敗: {e}")
    await asyncio.sleep(_INTER_SOURCE_DELAY)

    community_items: list[ArticleItem] = []
    try:
        community_items = await collect_community(target_date)
    except Exception as e:
        errors.append(f"Community: {e}")
        logger.error(f"Community 収集失敗: {e}")
    await asyncio.sleep(_INTER_SOURCE_DELAY)

    github_trending_items: list[ArticleItem] = []
    try:
        github_trending_items = await collect_github_trending(target_date)
    except Exception as e:
        errors.append(f"GitHub Trending: {e}")
        logger.error(f"GitHub Trending 収集失敗: {e}")
    await asyncio.sleep(_INTER_SOURCE_DELAY)

    ai_dev_items: list[ArticleItem] = []
    try:
        ai_dev_items = await collect_ai_dev(target_date)
    except Exception as e:
        errors.append(f"LLM・AIエージェント動向: {e}")
        logger.error(f"LLM・AIエージェント動向 収集失敗: {e}")

    lg_papers = arxiv_results.get("cs.LG", [])
    ai_papers = arxiv_results.get("cs.AI", [])
    cl_papers = arxiv_results.get("cs.CL", [])

    # ── 1.5. 重複除去 ──────────────────────────────────────────
    data_for_dedup = {
        "cv": cv_arxiv_papers,
        "openreview": openreview_items,
        "lg": lg_papers,
        "ai": ai_papers,
        "cl": cl_papers,
    }
    seen_ids = _load_seen_article_ids(settings.data_dir, collection_date_str)
    for key, items_list in data_for_dedup.items():
        before = len(items_list)
        data_for_dedup[key] = [p for p in items_list if p.id not in seen_ids]
        removed = before - len(data_for_dedup[key])
        if removed:
            logger.info(f"重複除去: {key} {removed} 件スキップ")
    cv_arxiv_papers = data_for_dedup["cv"]
    openreview_items = data_for_dedup["openreview"]
    lg_papers = data_for_dedup["lg"]
    ai_papers = data_for_dedup["ai"]
    cl_papers = data_for_dedup["cl"]

    # ── 2. 並列要約 ────────────────────────────────────────────
    logger.info("要約開始...")
    (
        cv_arxiv_papers,
        openreview_items,
        lg_papers,
        ai_papers,
        cl_papers,
        industry_items,
        industry_news_items,
        community_items,
        github_trending_items,
        ai_dev_items,
    ) = await asyncio.gather(
        summarize_items(cv_arxiv_papers, "paper"),
        summarize_items(openreview_items, "paper"),
        summarize_items(lg_papers, "paper"),
        summarize_items(ai_papers, "paper"),
        summarize_items(cl_papers, "paper"),
        summarize_items(industry_items, "industry"),
        summarize_items(industry_news_items, "industry"),
        summarize_items(community_items, "article"),
        summarize_items(github_trending_items, "article"),
        summarize_items(ai_dev_items, "industry"),
    )

    # ── 3. JSON 保存 ────────────────────────────────────────────
    logger.info("JSON 保存開始...")
    _save_collection(collection_date_str, target_date_str, "cv", cv_arxiv_papers)
    _save_collection(
        collection_date_str, target_date_str, "openreview", openreview_items
    )
    _save_collection(collection_date_str, target_date_str, "lg", lg_papers)
    _save_collection(collection_date_str, target_date_str, "ai", ai_papers)
    _save_collection(collection_date_str, target_date_str, "cl", cl_papers)
    _save_collection(collection_date_str, target_date_str, "industry", industry_items)
    _save_collection(
        collection_date_str, target_date_str, "industry_news", industry_news_items
    )
    _save_collection(collection_date_str, target_date_str, "community", community_items)
    _save_collection(
        collection_date_str, target_date_str, "github_trending", github_trending_items
    )
    _save_collection(collection_date_str, target_date_str, "ai_dev", ai_dev_items)

    # 収集件数を記録
    report.counts = {
        "CV 論文 arXiv (cs.CV)": len(cv_arxiv_papers),
        "CV 論文 OpenReview": len(openreview_items),
        "機械学習 (cs.LG)": len(lg_papers),
        "AI (cs.AI)": len(ai_papers),
        "自然言語処理 (cs.CL)": len(cl_papers),
        "企業動向（自社発表）": len(industry_items),
        "企業動向（その他報道）": len(industry_news_items),
        "コミュニティ": len(community_items),
        "GitHub Trending": len(github_trending_items),
        "LLM・AIエージェント動向": len(ai_dev_items),
    }

    # 要約失敗件数を集計してレポートに反映（無音の劣化を可視化）
    _all_batches = [
        cv_arxiv_papers,
        openreview_items,
        lg_papers,
        ai_papers,
        cl_papers,
        industry_items,
        industry_news_items,
        community_items,
        github_trending_items,
        ai_dev_items,
    ]
    summarize_failures = sum(
        1 for batch in _all_batches for it in batch if not it.summarized
    )
    if summarize_failures:
        msg = f"要約失敗 {summarize_failures} 件（Gemini エラー等で要約できず）"
        errors.append(msg)
        logger.warning(msg)

    # arXiv カテゴリの 0 件を可視化（遡及フォールバック後も 0 なら障害/異常の兆候）
    empty_arxiv_cats = [
        name
        for name, items in [
            ("cs.CV", cv_arxiv_papers),
            ("cs.LG", lg_papers),
            ("cs.AI", ai_papers),
            ("cs.CL", cl_papers),
        ]
        if not items
    ]
    if len(empty_arxiv_cats) == 4:
        msg = (
            "arXiv 全カテゴリ (cv/lg/ai/cl) が 0 件です。"
            "API インデックス反映遅延または障害の可能性があります。"
        )
        errors.append(msg)
        logger.error(msg)
    elif empty_arxiv_cats:
        msg = (
            f"arXiv カテゴリ {', '.join(empty_arxiv_cats)} が 0 件でした"
            "（遡及フォールバック後）。"
        )
        errors.append(msg)
        logger.warning(msg)

    # DB に記事を登録（チャット機能のため）
    await _register_articles_to_db(
        collection_date_str,
        cv_arxiv_papers,
        openreview_items,
        lg_papers,
        ai_papers,
        cl_papers,
        industry_items,
        industry_news_items,
        community_items,
        github_trending_items,
        ai_dev_items,
    )

    # ── 3.5. テーマ検索 ────────────────────────────────────────
    # 登録テーマごとに、その日の収集済みアイテム（in-memory）+ arXiv 専用検索で
    # 該当論文・記事を集めて保存する。
    await _run_theme_search(
        collection_date_str,
        target_date,
        {
            "cv": cv_arxiv_papers,
            "openreview": openreview_items,
            "lg": lg_papers,
            "ai": ai_papers,
            "cl": cl_papers,
            "industry": industry_items,
            "industry_news": industry_news_items,
            "community": community_items,
            "github_trending": github_trending_items,
            "ai_dev": ai_dev_items,
        },
        report,
        errors,
    )

    # ── 4. ダイジェスト生成 ────────────────────────────────────
    logger.info("ダイジェスト生成開始...")
    try:
        await generate_digest(
            collection_date_str,
            cv_arxiv_papers,
            lg_papers,
            ai_papers,
            cl_papers,
            industry_items,
            community_items,
            github_trending_items,
            ai_dev_items,
            target_date_str=target_date_str,
        )
        digest_content = load_digest(collection_date_str) or ""
        report.digest_preview = digest_content[:500]
    except Exception as e:
        errors.append(f"ダイジェスト生成: {e}")
        logger.error(f"ダイジェスト生成失敗: {e}")

    # ── 4.5. 一面まとめ英語版（英語多読用）生成 ────────────────
    # その日の最重要トピック1本を学術英語化。失敗してもパイプラインは止めない。
    logger.info("英語版（一面まとめ）生成開始...")
    try:
        en_path = await generate_english_digest(
            collection_date_str,
            {
                "cv": cv_arxiv_papers,
                "openreview": openreview_items,
                "lg": lg_papers,
                "ai": ai_papers,
                "cl": cl_papers,
                "ai_dev": ai_dev_items,
                "industry": industry_items,
                "community": community_items,
                "github_trending": github_trending_items,
            },
        )
        # 英語版が生成できたらローカル TTS で音声(mp3)も生成（バックグラウンド・非致命）
        if en_path:
            logger.info("英語版の音声合成開始...")
            await synthesize_english_audio(collection_date_str)
    except Exception as e:
        errors.append(f"英語版生成: {e}")
        logger.error(f"英語版生成失敗: {e}")

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
    category: Literal[
        "cv",
        "openreview",
        "lg",
        "ai",
        "cl",
        "industry",
        "industry_news",
        "community",
        "python",
        "github_trending",
        "ai_dev",
    ],
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

    category_names = [
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
    ]

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


async def _run_theme_search(
    collection_date_str: str,
    target_date: date,
    source_items: dict[str, list[ArticleItem]],
    report: CollectionReport,
    errors: list[str],
) -> None:
    """登録された有効テーマごとに検索・保存する（日次パイプライン用）。"""
    from app.services.themes import load_themes
    from app.services.theme_search import (
        collect_theme_from_sources,
        save_theme_collection,
        generate_theme_overview,
    )

    themes = [t for t in load_themes() if t.enabled]
    if not themes:
        return

    logger.info(f"テーマ検索開始... ({len(themes)} 件)")
    collected: list[ThemeCollection] = []
    for i, theme in enumerate(themes):
        try:
            tc = await collect_theme_from_sources(theme, target_date, source_items)
            save_theme_collection(collection_date_str, theme.id, tc)
            collected.append(tc)
            report.counts[f"テーマ: {theme.name}"] = tc.total
        except Exception as e:
            errors.append(f"テーマ {theme.name}: {e}")
            logger.error(f"テーマ検索失敗 ({theme.name}): {e}")
        # テーマ間に待機を入れて arXiv API レートリミットに配慮
        if i < len(themes) - 1:
            await asyncio.sleep(3)

    # テーマ別論文セクション全体の総括を生成（一面まとめと同様、LLM 生成）
    try:
        await generate_theme_overview(
            collection_date_str, target_date.isoformat(), collected
        )
    except Exception as e:
        errors.append(f"テーマ総括生成: {e}")
        logger.error(f"テーマ総括生成失敗: {e}")


def load_daily_data(date_str: str) -> dict[str, list[ArticleItem]]:
    """
    指定日の JSON ファイルを全カテゴリ読み込み、辞書で返す。
    キー: "cv", "openreview", "lg", "ai", "cl", "industry", "industry_news",
          "community", "github_trending", "ai_dev"
    """
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
    ]
    result: dict[str, list[ArticleItem]] = {}

    for cat in categories:
        file_path = settings.data_dir / date_str / f"papers_{cat}.json"
        # github_trending → python へのフォールバック（旧データ互換）
        if not file_path.exists() and cat == "github_trending":
            file_path = settings.data_dir / date_str / "papers_python.json"
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


def _load_seen_article_ids(data_dir: Path, exclude_date: str) -> set[str]:
    """過去の JSON ファイルから収集済み論文 ID 一覧を返す（重複除去用）"""
    seen: set[str] = set()
    if not data_dir.exists():
        return seen
    for day_dir in data_dir.iterdir():
        if not day_dir.is_dir() or day_dir.name == exclude_date:
            continue
        for fp in day_dir.glob("papers_*.json"):
            try:
                raw = json.loads(fp.read_text(encoding="utf-8"))
                col = DailyCollection.model_validate(raw)
                seen.update(it.id for it in col.items)
            except Exception:
                continue
    return seen


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
