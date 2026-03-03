"""
Gemini API を使った要約処理モジュール
要約・翻訳には gemini-2.5-pro を使用する
"""
import asyncio
import logging
from typing import Literal

import google.generativeai as genai

from app.config import settings
from app.schemas import ArticleItem

logger = logging.getLogger(__name__)

# Gemini API の設定
genai.configure(api_key=settings.gemini_api_key)

# 1 分あたりの並列リクエスト上限（レート制限対策）
_SEMAPHORE = asyncio.Semaphore(5)
_REQUEST_DELAY = 1.0  # 秒


def _get_summary_model() -> genai.GenerativeModel:
    return genai.GenerativeModel(settings.gemini_summary_model)


async def summarize_item(
    item: ArticleItem,
    category: Literal["paper", "article"],
) -> ArticleItem:
    """1 件のアイテムを Gemini Pro で要約する（非同期・スレッドプール経由）"""
    if item.summarized:
        return item

    prompt = _build_prompt(item, category)

    async with _SEMAPHORE:
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                None, _call_gemini, prompt
            )
            _parse_result(item, result, category)
            item.summarized = True
        except Exception as e:
            logger.error(f"要約失敗 ({item.id}): {e}")
        await asyncio.sleep(_REQUEST_DELAY)

    return item


def _call_gemini(prompt: str) -> str:
    model = _get_summary_model()
    response = model.generate_content(prompt)
    return response.text


def _build_prompt(item: ArticleItem, category: Literal["paper", "article"]) -> str:
    if category == "paper":
        return f"""以下の論文を日本語で詳しく要約してください。
必ず以下のフォーマットで出力してください（Markdown 形式）。

【日本語タイトル】
（論文タイトルの自然な日本語訳）

【概要】
（何をした研究か、2〜3文で説明）

【新規性・貢献】
（既存研究との違いや本論文の貢献を具体的に説明）

【手法の概要】
（提案手法を簡潔に説明）

【実験結果のポイント】
（主な実験結果や性能向上の数値など）

【タグ】
以下のルールに従ってタグを生成し、スペース区切りで列挙すること。
1. 内容を表すキーワードを合計5個程度生成する
2. タイトルに含まれる技術的固有名詞（モデル名・手法名・データセット名など）は必ず含める
3. LLM・VLM・拡散モデルなど特定のモデルカテゴリに該当する場合、そのモデル名と「LLM」「VLM」「拡散モデル」等のカテゴリ名を両方含める
例: GPT-4 LLM 画像キャプション マルチモーダル ベンチマーク

---
タイトル: {item.title_en}
著者: {', '.join(item.authors[:5])}
アブストラクト:
{item.abstract_en}
"""
    else:
        return f"""以下の記事・ニュースを日本語で要約してください。
必ず以下のフォーマットで出力してください（Markdown 形式）。

【日本語タイトル】
（タイトルの自然な日本語訳、または日本語の場合はそのまま）

【概要】
（何が発表・議論されているか、2〜3文で説明）

【ポイント】
- （重要ポイント1）
- （重要ポイント2）
- （重要ポイント3）

【タグ】
以下のルールに従ってタグを生成し、スペース区切りで列挙すること。
1. 内容を表すキーワードを合計5個程度生成する
2. タイトルに含まれる技術的固有名詞（モデル名・サービス名・フレームワーク名など）は必ず含める
3. LLM・VLM・画像生成など特定のモデルカテゴリに該当する場合、そのモデル名と「LLM」「VLM」等のカテゴリ名を両方含める
例: Claude3.5 LLM Anthropic APIリリース マルチモーダル

---
タイトル: {item.title_en or item.title_ja}
ソース: {item.source_name}
内容:
{item.abstract_en[:1000]}
"""


def _parse_result(item: ArticleItem, text: str, category: Literal["paper", "article"]) -> None:
    """LLM の出力テキストを ArticleItem の各フィールドに格納する"""
    lines = text.strip().split("\n")

    def extract_section(marker: str) -> str:
        collecting = False
        result_lines = []
        for line in lines:
            if marker in line:
                collecting = True
                continue
            if collecting:
                if line.startswith("【") and line.endswith("】"):
                    break
                if line.strip() == "---":
                    break
                result_lines.append(line)
        return "\n".join(result_lines).strip()

    title_ja = extract_section("【日本語タイトル】")
    if title_ja:
        item.title_ja = title_ja

    summary = extract_section("【概要】")
    if summary:
        item.summary_ja = summary

    if category == "paper":
        novelty = extract_section("【新規性・貢献】")
        if novelty:
            item.novelty_ja = novelty
    else:
        points_text = extract_section("【ポイント】")
        if points_text:
            item.key_points_ja = [
                line.lstrip("・- ").strip()
                for line in points_text.split("\n")
                if line.strip().startswith(("・", "-"))
            ]

    # タグを抽出して hashtags に格納
    tags_text = extract_section("【タグ】")
    if tags_text:
        item.hashtags = [
            t.strip().lstrip("#")
            for t in tags_text.split()
            if t.strip()
        ][:5]

    # フォールバック: タイトルが取れなかった場合
    if not item.title_ja and item.title_en:
        item.title_ja = item.title_en


async def summarize_items(
    items: list[ArticleItem],
    category: Literal["paper", "article"],
) -> list[ArticleItem]:
    """複数アイテムを並列要約する"""
    tasks = [summarize_item(item, category) for item in items]
    return await asyncio.gather(*tasks)
