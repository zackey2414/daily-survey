"""
Gemini API を使った要約処理モジュール
個別記事・論文の要約には gemini-2.5-flash を使用する（一面まとめは digest.py で gemini-2.5-pro を使用）
プロンプトテンプレートは prompts/ ディレクトリの .md ファイルから読み込む
"""

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Literal

import google.generativeai as genai

from app.config import settings
from app.schemas import ArticleItem

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"


def _load_template(name: str) -> str:
    """prompts/ ディレクトリからテンプレートを読み込む。ファイルがなければ空文字を返す。"""
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning(f"プロンプトテンプレートが見つかりません: {path}")
    return ""


# Gemini API の設定
genai.configure(api_key=settings.gemini_api_key)

# 1 分あたりの並列リクエスト上限（レート制限対策）
_SEMAPHORE = asyncio.Semaphore(5)
_REQUEST_DELAY = 1.0  # 秒


def _get_summary_model() -> genai.GenerativeModel:
    return genai.GenerativeModel(settings.gemini_chat_model)


async def summarize_item(
    item: ArticleItem,
    category: Literal["paper", "article", "industry"],
) -> ArticleItem:
    """1 件のアイテムを Gemini Pro で要約する（非同期・スレッドプール経由）"""
    if item.summarized:
        return item

    prompt = _build_prompt(item, category)

    async with _SEMAPHORE:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, _call_gemini_with_retry, prompt
            )
            _parse_result(item, result, category)
            item.summarized = True
        except Exception as e:
            # 失敗時は summarized=False のまま残す（呼び出し側で失敗件数を集計可能）
            logger.error(f"要約失敗 ({item.id}): {e}")
        await asyncio.sleep(_REQUEST_DELAY)

    return item


def _call_gemini(prompt: str) -> str:
    model = _get_summary_model()
    response = model.generate_content(prompt)
    # safety ブロック等で candidate が無いと response.text は None を返しうる
    return getattr(response, "text", None) or ""


def _call_gemini_with_retry(prompt: str, max_retries: int = 3) -> str:
    """一時的な Gemini エラー（quota/429/5xx/ネットワーク）や空応答をリトライする。

    すべてのリトライで失敗・空応答なら例外を送出し、呼び出し側で要約失敗として扱う。
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            text = _call_gemini(prompt)
            if text.strip():
                return text
            last_exc = ValueError("Gemini が空レスポンスを返しました")
        except Exception as e:  # noqa: BLE001 — 種別を問わず一時障害として扱う
            last_exc = e
        if attempt < max_retries - 1:
            time.sleep(2 * (attempt + 1))  # 2s, 4s
    raise last_exc if last_exc is not None else RuntimeError("要約失敗")


def _build_prompt(
    item: ArticleItem, category: Literal["paper", "article", "industry"]
) -> str:
    if category == "paper":
        template = _load_template("summary_paper.md")
        return template.format(
            title_en=item.title_en,
            authors=", ".join(item.authors[:5]),
            abstract_en=item.abstract_en,
        )
    elif category == "industry":
        template = _load_template("summary_industry.md")
        return template.format(
            title=item.title_en or item.title_ja,
            source_name=item.source_name,
            content=item.abstract_en[:1500],
        )
    else:
        template = _load_template("summary_article.md")
        return template.format(
            title=item.title_en or item.title_ja,
            source_name=item.source_name,
            content=item.abstract_en[:1000],
        )


def _parse_result(
    item: ArticleItem, text: str, category: Literal["paper", "article", "industry"]
) -> None:
    """LLM の出力テキストを ArticleItem の各フィールドに格納する。

    Gemini は 【見出し】 を ### 【見出し】 / **【見出し】** など
    様々な Markdown 装飾付きで出力するため、全文を一括解析する正規表現アプローチを使う。
    """
    # セクション境界: 行頭の任意の Markdown 装飾 + 【見出し】 を検出
    _SECTION_RE = re.compile(
        r"(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?【([^】]+)】(?:\*{1,2})?[ \t]*\n"
        r"(.*?)(?=\n[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?【|^---$|\Z)",
        re.DOTALL | re.MULTILINE,
    )

    sections: dict[str, str] = {}
    for m in _SECTION_RE.finditer(text):
        key = m.group(1).strip()
        content = m.group(2).strip()
        if key not in sections:  # 最初に現れたセクションを優先
            sections[key] = content

    title_ja = sections.get("日本語タイトル", "")
    if title_ja:
        item.title_ja = title_ja

    summary = sections.get("概要", "")
    if summary:
        item.summary_ja = summary

    if category == "paper":
        novelty = sections.get("新規性・貢献", "")
        if novelty:
            item.novelty_ja = novelty
        meta_learning = sections.get("メタ的な学び", "")
        if meta_learning:
            item.meta_learning_ja = meta_learning
    else:
        points_text = sections.get("ポイント", "")
        if points_text:
            item.key_points_ja = [
                line.lstrip("・- ").strip()
                for line in points_text.split("\n")
                if line.strip().startswith(("・", "-"))
            ]
        if category == "industry":
            metrics_text = sections.get("定量指標", "")
            if metrics_text and metrics_text.strip().lower() != "なし":
                item.quantitative_metrics_ja = metrics_text

    tags_text = sections.get("タグ", "")
    if tags_text:
        item.hashtags = [t.strip().lstrip("#") for t in tags_text.split() if t.strip()][
            :8
        ]

    if not item.title_ja and item.title_en:
        item.title_ja = item.title_en


async def summarize_items(
    items: list[ArticleItem],
    category: Literal["paper", "article", "industry"],
) -> list[ArticleItem]:
    """複数アイテムを並列要約する"""
    tasks = [summarize_item(item, category) for item in items]
    return await asyncio.gather(*tasks)
