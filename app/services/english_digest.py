"""
一面まとめ「英語版」（英語多読用）の生成モジュール。

その日の最重要トピック1本を、安価な flash-lite モデルで明瞭な学術英語に書き起こし、
文単位の全訳・チャンク単位の語義を付与した構造化 JSON を summaries/{date}.en.json に保存する。

設計方針（ユーザー要望: トークン最小化）:
- LLM 呼び出しは1日1回のみ。入力は候補を「タイトル＋短縮要約」に絞った小さなリスト。
- 文章生成（英文＋訳＋語義）以外（候補整形・JSON 検証・保存・描画）はすべてコードで行う。

入出力パターンは app/services/digest.py / themes.py のヘルパー流儀を踏襲する。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

import pytz

from app.config import settings
from app.gemini import get_client
from app.schemas import ArticleItem, EnglishDigest

logger = logging.getLogger(__name__)
JST = pytz.timezone("Asia/Tokyo")

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# 候補に含めるカテゴリの優先順位（論文を優先 → 「論文らしい」英文になりやすい）
_CANDIDATE_PRIORITY = ["cv", "lg", "ai", "cl", "openreview"]
# 論文が無い日のフォールバック（企業動向・コミュニティ等）
_CANDIDATE_FALLBACK = [
    "ai_dev",
    "industry",
    "industry_news",
    "community",
    "github_trending",
]
_PER_CATEGORY = 3  # 各カテゴリから拾う最大件数
_MAX_CANDIDATES = 10  # 候補リスト全体の上限（トークン削減）
_SUMMARY_TRIM = 120  # 候補要約の最大文字数（トークン削減）


def _en_path(date_str: str) -> Path:
    return settings.summaries_dir / f"{date_str}.en.json"


def english_digest_exists(date_str: str) -> bool:
    """その日の英語版が生成済みか。"""
    return _en_path(date_str).exists()


def load_english_digest(date_str: str) -> EnglishDigest | None:
    """保存済みの英語版を読み込む。破損・未生成時は None。"""
    path = _en_path(date_str)
    if not path.exists():
        return None
    try:
        return EnglishDigest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning(f"英語版読み込み失敗 ({date_str}): {e}")
        return None


# ── 生成 ───────────────────────────────────────────────────────


def _load_template(name: str) -> str:
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning(f"プロンプトテンプレートが見つかりません: {path}")
    return ""


def _build_candidates(
    items_by_category: dict[str, list[ArticleItem]],
) -> list[ArticleItem]:
    """カテゴリ別アイテムから候補リストを作る（論文優先・上位のみ・重複除去）。"""
    candidates: list[ArticleItem] = []
    seen: set[str] = set()

    def add_from(cats: list[str]) -> None:
        for cat in cats:
            for item in (items_by_category.get(cat) or [])[:_PER_CATEGORY]:
                if item.id in seen:
                    continue
                seen.add(item.id)
                candidates.append(item)

    add_from(_CANDIDATE_PRIORITY)
    if not candidates:
        add_from(_CANDIDATE_FALLBACK)
    return candidates[:_MAX_CANDIDATES]


def _candidates_text(candidates: list[ArticleItem]) -> str:
    """候補を「番号. タイトル: 短い要約」の素朴なテキストに整形（トークン削減）。"""
    lines: list[str] = []
    for i, item in enumerate(candidates, 1):
        title = item.title_en or item.title_ja or "(no title)"
        summary = (item.summary_ja or item.abstract_en or "").strip().replace("\n", " ")
        if len(summary) > _SUMMARY_TRIM:
            summary = summary[:_SUMMARY_TRIM] + "…"
        lines.append(f"{i}. {title}: {summary}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """LLM 出力から最初の JSON オブジェクトを取り出す。

    ```json フェンスや前後の余分なテキスト、JSON 後ろの余計な出力（Extra data）にも
    耐えるよう、最初の `{` から JSONDecoder.raw_decode で1オブジェクトだけ読む。
    """
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t).strip()
    start = t.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(t[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _call_gemini_json(prompt: str) -> str:
    """flash-lite に JSON 出力を要求して呼ぶ（response_mime_type で JSON を促す）。"""
    from google.genai import types

    response = get_client().models.generate_content(
        model=settings.gemini_chat_model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return (getattr(response, "text", None) or "").strip()


def _call_with_retry(prompt: str, max_retries: int = 3) -> str:
    """一時的な Gemini エラーをバックオフ付きでリトライ（themes.py と同等）。"""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return _call_gemini_json(prompt)
        except Exception as e:  # noqa: BLE001 — 種別を問わず一時障害として扱う
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))  # 2s, 4s
    assert last_exc is not None
    raise last_exc


def _save(date_str: str, digest: EnglishDigest) -> str:
    """アトミック保存（themes.py の save_themes パターン: tmp→os.replace）。"""
    settings.summaries_dir.mkdir(parents=True, exist_ok=True)
    path = _en_path(date_str)
    payload = digest.model_dump_json(indent=2)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)  # POSIX 上でアトミック
    return str(path)


async def generate_english_digest(
    date_str: str,
    items_by_category: dict[str, list[ArticleItem]],
) -> str | None:
    """その日の最重要トピックの英語版を生成して保存する。

    保存パスを返す。候補なし・生成失敗・検証失敗時は None（呼び出し側で非致命扱い）。
    """
    candidates = _build_candidates(items_by_category)
    if not candidates:
        logger.info(f"英語版: 候補がないためスキップ ({date_str})")
        return None

    template = _load_template("english_digest.md")
    if not template:
        return None
    # プロンプトには JSON 例（波括弧）が含まれるため .format は使わず .replace で埋める
    prompt = template.replace("{coverage_date}", date_str).replace(
        "{candidates}", _candidates_text(candidates)
    )

    try:
        raw = await asyncio.get_event_loop().run_in_executor(
            None, _call_with_retry, prompt
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"英語版生成失敗（Gemini, {date_str}）: {e}")
        return None

    data = _extract_json(raw)
    if data is None:
        logger.error(f"英語版 JSON パース失敗 ({date_str})")
        return None

    # メタ情報をサーバ側で確定（モデルの自己申告に依存しない）
    data["date"] = date_str
    data["model"] = settings.gemini_chat_model
    data["generated_at"] = datetime.now(JST).isoformat()

    try:
        digest = EnglishDigest.model_validate(data)
    except Exception as e:  # noqa: BLE001
        logger.error(f"英語版スキーマ検証失敗 ({date_str}): {e}")
        return None

    if not digest.paragraphs:
        logger.warning(f"英語版: 段落が空のため保存しない ({date_str})")
        return None

    save_path = _save(date_str, digest)
    logger.info(f"英語版保存完了: {save_path}")
    return save_path
