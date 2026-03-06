"""
Gemini API を使った要約処理モジュール
個別記事・論文の要約には gemini-2.5-flash を使用する（一面まとめは digest.py で gemini-2.5-pro を使用）
"""
import asyncio
import logging
import re
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


def _build_prompt(item: ArticleItem, category: Literal["paper", "article", "industry"]) -> str:
    if category == "paper":
        return f"""以下の論文を日本語で詳しく要約してください。
必ず以下のフォーマットで出力してください（Markdown 形式）。

【日本語タイトル】
（論文タイトルの自然な日本語訳）

【概要】
（何をした研究か、2〜3文で説明）

【新規性・貢献】
（既存研究との違いや本論文の貢献を具体的に説明）

【メタ的な学び】
この論文の内容自体ではなく、以下の観点からメタレベルの学びを2〜3文で具体的に記述してください。
- 問題の定式化の仕方（何を入力・出力とし何を最適化しているか）
- アプローチの独自性（既存手法の組み合わせ方、着眼点）
- 評価手法・指標の選択から学べること

【手法の概要】
（提案手法を簡潔に説明）

【実験結果のポイント】
（主な実験結果や性能向上の数値など）

【タグ】
以下のルールに従ってタグを生成し、スペース区切りで列挙すること。
1. この論文が取り組む**タスク名**を必ず最初に1つ含める（例: 画像検索・物体中心画像検索・動画サンプリング・物体検知・セグメンテーション・動画像分類・姿勢推定・画像生成・テキスト分類・機械翻訳・質問応答・要約・固有表現認識 など、論文内容に最も合致するタスク名を日本語で）
2. 内容を表すキーワードを合計7個程度生成する
3. タイトルに含まれる技術的固有名詞（モデル名・手法名・データセット名など）は必ず含める
4. LLM・VLM・拡散モデルなど特定のモデルカテゴリに該当する場合、そのモデル名と「LLM」「VLM」「拡散モデル」等のカテゴリ名を両方含める
例: 画像検索 CLIP マルチモーダル 物体中心 ベンチマーク 自己教師あり学習 ViT

---
タイトル: {item.title_en}
著者: {', '.join(item.authors[:5])}
アブストラクト:
{item.abstract_en}
"""
    elif category == "industry":
        return f"""以下の AI 企業動向に関する記事・発表を日本語で要約してください。
必ず以下のフォーマットで出力してください（Markdown 形式）。

【日本語タイトル】
（タイトルの自然な日本語訳、または日本語の場合はそのまま）

【概要】
（何が発表・議論されているか、2〜3文で説明）

【ポイント】
- （重要ポイント1）
- （重要ポイント2）
- （重要ポイント3）

【定量指標】
記事内に性能・技術に関する定量的な数値がある場合は、以下の形式で列挙してください。
なければ「なし」と出力してください。
- ベンチマーク名: スコア（従来手法比 +XX% / 従来: YY → 新: ZZ 等）
例:
- MMLU: 92.3%（GPT-4比 +3.1%）
- 推論速度: 従来比 2.4倍高速化
- コンテキスト長: 1M トークン（従来の8倍）

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
{item.abstract_en[:1500]}
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


def _parse_result(item: ArticleItem, text: str, category: Literal["paper", "article", "industry"]) -> None:
    """LLM の出力テキストを ArticleItem の各フィールドに格納する。

    Gemini は 【見出し】 を ### 【見出し】 / **【見出し】** など
    様々な Markdown 装飾付きで出力するため、全文を一括解析する正規表現アプローチを使う。
    """
    # セクション境界: 行頭の任意の Markdown 装飾 + 【見出し】 を検出
    _SECTION_RE = re.compile(
        r'(?:^|\n)[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?【([^】]+)】(?:\*{1,2})?[ \t]*\n'
        r'(.*?)(?=\n[ \t]*(?:#{1,6}[ \t]*)?(?:\*{1,2})?【|^---$|\Z)',
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
        item.hashtags = [
            t.strip().lstrip("#")
            for t in tags_text.split()
            if t.strip()
        ][:8]

    if not item.title_ja and item.title_en:
        item.title_ja = item.title_en


async def summarize_items(
    items: list[ArticleItem],
    category: Literal["paper", "article", "industry"],
) -> list[ArticleItem]:
    """複数アイテムを並列要約する"""
    tasks = [summarize_item(item, category) for item in items]
    return await asyncio.gather(*tasks)
