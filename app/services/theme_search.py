"""
検索テーマのハイブリッド収集モジュール

「全ソース横断」をソースの検索可否に合わせて実現する:
  - arXiv: テーマキーワードで専用全文検索クエリ（カテゴリ上位サンプルに埋もれる論文も拾う）
  - その他全ソース: その日に収集済みのアイテムをキーワードでフィルタ

結果は data/{date}/themes/{theme_id}.json (ThemeCollection) に保存する。
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.schemas import ArticleItem, Theme, ThemeCollection
from app.services.summarizer import summarize_items

logger = logging.getLogger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}
_JST = timezone(timedelta(hours=9))

MAX_ARXIV_PER_THEME = 30  # 1テーマ・1検索あたりの arXiv 取得上限
_MAX_RETRIES = 4


# ── キーワードマッチ ──────────────────────────────────────────


def _compile_patterns(keywords: list[str]) -> list[re.Pattern]:
    """キーワードを正規表現にコンパイルする。

    短い英単語（AI/RAG/ML 等）の誤マッチを防ぐため、語の端が英数字なら
    単語境界 \\b を付与する。日本語キーワードは CJK 間に \\b が無いため
    実質 substring マッチとなり、これは望ましい挙動。
    """
    patterns: list[re.Pattern] = []
    for raw in keywords:
        kw = raw.strip()
        if not kw:
            continue
        esc = re.escape(kw)
        left = r"\b" if kw[0].isalnum() else ""
        right = r"\b" if kw[-1].isalnum() else ""
        patterns.append(re.compile(left + esc + right, re.IGNORECASE))
    return patterns


def _match(item: ArticleItem, patterns: list[re.Pattern]) -> bool:
    text = " ".join(
        [item.title_en, item.title_ja, item.abstract_en, " ".join(item.hashtags)]
    )
    return any(p.search(text) for p in patterns)


# ── arXiv 専用キーワード検索 ──────────────────────────────────


async def _search_arxiv(
    keywords: list[str],
    jst_from: date,
    jst_to: date,
    max_results: int = MAX_ARXIV_PER_THEME,
) -> list[ArticleItem]:
    """テーマキーワードで arXiv を全文検索し、[jst_from, jst_to] の論文を返す。"""
    if not keywords:
        return []

    kw_clause = " OR ".join(f'all:"{kw}"' for kw in keywords)
    # JST [from 00:00, to 23:59] を UTC submittedDate ウィンドウに変換
    # JST 00:00 = UTC 前日 15:00 / JST 23:59:59 = UTC 当日 14:59:59
    from_str = (jst_from - timedelta(days=1)).strftime("%Y%m%d") + "150000"
    to_str = jst_to.strftime("%Y%m%d") + "145959"
    search_query = f"({kw_clause}) AND submittedDate:[{from_str} TO {to_str}]"

    params: dict[str, Any] = {
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max(100, max_results * 3),
        "start": 0,
    }

    logger.info(
        f"テーマ arXiv 検索: {len(keywords)} ワード / 期間(JST) {jst_from}〜{jst_to}"
    )

    xml_text = await _fetch_arxiv(params)
    if not xml_text:
        return []

    items = _parse_arxiv(xml_text, jst_from, jst_to)
    return items[:max_results]


async def _fetch_arxiv(params: dict[str, Any]) -> str | None:
    """arXiv API をリトライ付きで取得し XML テキストを返す。"""
    async with httpx.AsyncClient(timeout=90.0) as client:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.get(ARXIV_API_URL, params=params)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                retryable = status == 429 or status >= 500
                if attempt < _MAX_RETRIES - 1 and retryable:
                    retry_after = e.response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait = int(retry_after) + 5
                    else:
                        wait = 15 * (2**attempt)
                    logger.warning(
                        f"テーマ arXiv 検索 {status}: {wait}秒後にリトライ "
                        f"({attempt + 1}/{_MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"テーマ arXiv 検索エラー: {e}")
                return None
            except httpx.HTTPError as e:
                logger.error(f"テーマ arXiv 検索エラー: {e}")
                return None
    return None


def _parse_arxiv(xml_text: str, jst_from: date, jst_to: date) -> list[ArticleItem]:
    """arXiv の Atom XML をパースし、JST 公開日が範囲内の論文を ArticleItem 化する。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"テーマ arXiv XML パース失敗: {e}")
        return []

    items: list[ArticleItem] = []
    for entry in root.findall("atom:entry", _NS):
        published_raw = entry.findtext("atom:published", "", _NS)
        if not published_raw:
            continue
        try:
            pub_dt = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            pub_jst_date = pub_dt.astimezone(_JST).date()
        except ValueError:
            continue
        if not (jst_from <= pub_jst_date <= jst_to):
            continue

        arxiv_id_raw = entry.findtext("atom:id", "", _NS)
        arxiv_id = arxiv_id_raw.split("/abs/")[-1].strip()
        title = (entry.findtext("atom:title", "", _NS) or "").replace("\n", " ").strip()
        abstract = (
            (entry.findtext("atom:summary", "", _NS) or "").replace("\n", " ").strip()
        )
        authors = [
            a.findtext("atom:name", "", _NS) for a in entry.findall("atom:author", _NS)
        ]
        pdf_url = ""
        for link in entry.findall("atom:link", _NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break
        primary_cat = entry.find("arxiv:primary_category", _NS)
        cat_tag = primary_cat.get("term", "") if primary_cat is not None else ""

        items.append(
            ArticleItem(
                id=f"arxiv:{arxiv_id}",
                title_en=title,
                authors=authors,
                abstract_en=abstract,
                published_date=pub_jst_date.isoformat(),
                url=f"https://arxiv.org/abs/{arxiv_id}",
                pdf_url=pdf_url or f"https://arxiv.org/pdf/{arxiv_id}",
                source_type="arxiv",
                source_name="arXiv",
                tags=[cat_tag] if cat_tag else [],
            )
        )
    return items


# ── テーマ収集（中核） ────────────────────────────────────────


async def collect_theme_from_sources(
    theme: Theme,
    target_date: date,
    source_items: dict[str, list[ArticleItem]],
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ThemeCollection:
    """与えられた収集済みアイテム + arXiv 専用検索からテーマ結果を組み立てる。

    source_items: その期間に収集済みの {category: [ArticleItem]}（既に要約済み想定）
    date_from/date_to: arXiv 検索の JST 期間。省略時は target_date 単日。
    """
    jst_from = date_from or target_date
    jst_to = date_to or target_date

    if not theme.keywords:
        logger.info(f"テーマ '{theme.name}': キーワード未設定のためスキップ")
        return _build_collection(theme, target_date, [], [])

    patterns = _compile_patterns(theme.keywords)

    # 1. その日の全収集アイテムからキーワード一致を抽出（既に要約済み）
    matched: list[ArticleItem] = []
    seen: set[str] = set()
    available_sources: set[str] = set()
    for category, items in source_items.items():
        if items:
            available_sources.add(category)
        for item in items:
            if item.id in seen:
                continue
            if _match(item, patterns):
                copied = item.model_copy(deep=True)
                _add_theme_tag(copied, theme.id)
                matched.append(copied)
                seen.add(item.id)

    # 2. arXiv 専用キーワード検索（深掘り。1.で拾えていない論文を追加）
    arxiv_hits = await _search_arxiv(theme.keywords, jst_from, jst_to)
    new_arxiv: list[ArticleItem] = []
    for hit in arxiv_hits:
        if hit.id in seen:
            continue
        _add_theme_tag(hit, theme.id)
        new_arxiv.append(hit)
        seen.add(hit.id)
    if arxiv_hits:
        available_sources.add("arxiv:search")

    # 3. 要約（収集済みアイテムは summarized=True で no-op。新規 arXiv のみ課金）
    matched, new_arxiv = await asyncio.gather(
        summarize_items(matched, "article"),  # 既要約は素通り
        summarize_items(new_arxiv, "paper"),
    )

    result = matched + new_arxiv
    result.sort(key=lambda i: i.published_date, reverse=True)

    return _build_collection(theme, target_date, result, sorted(available_sources))


async def collect_theme(
    theme: Theme,
    target_date: date,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ThemeCollection:
    """disk からその日の収集済みデータを読み込んでテーマ収集する（オンデマンド用）。

    収集データは collection_date（= target_date + 1日）ディレクトリに保存されているため、
    その名前で load_daily_data を呼ぶ。
    """
    from app.services.pipeline import load_daily_data

    collection_date = target_date + timedelta(days=1)
    source_items = load_daily_data(collection_date.isoformat())
    return await collect_theme_from_sources(
        theme, target_date, source_items, date_from=date_from, date_to=date_to
    )


def _add_theme_tag(item: ArticleItem, theme_id: str) -> None:
    tag = f"theme:{theme_id}"
    if tag not in item.tags:
        item.tags.append(tag)


def _build_collection(
    theme: Theme,
    target_date: date,
    items: list[ArticleItem],
    source_coverage: list[str],
) -> ThemeCollection:
    collection_date = target_date + timedelta(days=1)
    return ThemeCollection(
        theme_id=theme.id,
        theme_name=theme.name,
        keywords_snapshot=list(theme.keywords),
        date=target_date.isoformat(),
        collection_date=collection_date.isoformat(),
        collected_at=datetime.now(timezone.utc).isoformat(),
        source_coverage=source_coverage,
        items=items,
    )


# ── 保存・読込 ────────────────────────────────────────────────


def save_theme_collection(
    collection_date_str: str, theme_id: str, tc: ThemeCollection
) -> Path:
    """ThemeCollection を data/{collection_date}/themes/{theme_id}.json に保存する。"""
    themes_dir = settings.data_dir / collection_date_str / "themes"
    themes_dir.mkdir(parents=True, exist_ok=True)
    file_path = themes_dir / f"{theme_id}.json"
    file_path.write_text(
        tc.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
    )
    logger.info(f"テーマ保存: {file_path} ({tc.total} 件)")
    return file_path


def load_theme_results(theme_id: str) -> list[ThemeCollection]:
    """全日付の data/*/themes/{theme_id}.json を読み込み、対象日降順で返す。"""
    data_dir = settings.data_dir
    if not data_dir.exists():
        return []
    results: list[ThemeCollection] = []
    for day_dir in data_dir.iterdir():
        if not day_dir.is_dir() or day_dir.name.count("-") != 2:
            continue
        file_path = day_dir / "themes" / f"{theme_id}.json"
        if not file_path.exists():
            continue
        try:
            raw = file_path.read_text(encoding="utf-8")
            results.append(ThemeCollection.model_validate_json(raw))
        except Exception as e:
            logger.warning(f"テーマ結果読み込み失敗 ({file_path}): {e}")
    results.sort(key=lambda c: c.date, reverse=True)
    return results
