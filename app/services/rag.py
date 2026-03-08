"""
RAG (Retrieval-Augmented Generation) サービス

チャット応答生成時に記事・論文の関連テキストを取得・抽出してコンテキストを構築する。
- 論文 (arXiv / OpenReview): JSON に保存済みの abstract_en + 要約フィールドを使用
- 記事 (RSS / Qiita / Zenn 等): URL から本文を取得し、ユーザー質問に関連するチャンクを抽出
"""

import json
import logging
import re

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.db.models import Article
from app.schemas import ArticleItem, DailyCollection

logger = logging.getLogger(__name__)

# RAG チューニングパラメータ
_MAX_CHUNK_CHARS = 800  # チャンク最大文字数
_TOP_K_CHUNKS = 8  # 返す関連チャンク数
_MIN_SCORE = 0.0  # スコア閾値（0.0 = 常にトップK を返す）
_MAX_FETCH_CHARS = 40_000  # URL フェッチ後のテキスト上限
_INTRO_CHUNKS = 2  # スコアに関わらず先頭から必ず含めるチャンク数

# 論文ソースタイプ（URL フェッチ不要）
_PAPER_SOURCES = {"arxiv", "openreview"}

# URL フェッチキャッシュ（記事ごとに1回のみ取得、プロセス再起動でリセット）
_page_text_cache: dict[str, str] = {}


# ──────────────────────────────────────────────
# 内部ユーティリティ
# ──────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    """英語単語（3文字以上）と日本語トークンを抽出"""
    en = re.findall(r"[a-zA-Z]{3,}", text.lower())
    ja = re.findall(r"[\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ff]+", text)
    # 日本語は bi-gram で近似
    ja_bigrams: list[str] = []
    for w in ja:
        ja_bigrams += [w[i : i + 2] for i in range(len(w) - 1)]
    return set(en) | set(ja_bigrams)


def _score(chunk: str, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    chunk_tokens = _tokenize(chunk)
    return len(query_tokens & chunk_tokens) / len(query_tokens)


def _split_paragraphs(text: str) -> list[str]:
    """段落単位でテキストを分割し、長すぎる段落は文で再分割"""
    raw_paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in raw_paras:
        if len(buf) + len(para) + 2 <= _MAX_CHUNK_CHARS:
            buf = (buf + "\n\n" + para).strip() if buf else para
        else:
            if buf:
                chunks.append(buf)
            # 段落が単体で長すぎる場合、文区切り
            if len(para) > _MAX_CHUNK_CHARS:
                sentences = re.split(r"(?<=[。．！？.!?])\s*", para)
                buf = ""
                for s in sentences:
                    if len(buf) + len(s) <= _MAX_CHUNK_CHARS:
                        buf = (buf + " " + s).strip()
                    else:
                        if buf:
                            chunks.append(buf)
                        buf = s[:_MAX_CHUNK_CHARS]
            else:
                buf = para
    if buf:
        chunks.append(buf)
    return chunks


async def _fetch_page_text(url: str) -> str:
    """URL から本文テキストを取得する（BeautifulSoup でスクレイピング）"""
    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AI-Daily-Survey/1.0)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        text = soup.get_text(separator="\n")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text[:_MAX_FETCH_CHARS]
    except Exception as e:
        logger.warning(f"URL フェッチ失敗 ({url}): {e}")
        return ""


# ──────────────────────────────────────────────
# 公開 API
# ──────────────────────────────────────────────


def load_article_item(article: Article) -> ArticleItem | None:
    """
    DB の Article レコードに対応する JSON の ArticleItem を返す。
    登録日の JSON が見つからない場合は全日付ディレクトリを検索する。
    """
    # まず登録日 + カテゴリで検索（高速パス）
    file_path = settings.data_dir / article.date / f"papers_{article.category}.json"
    if file_path.exists():
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
            collection = DailyCollection.model_validate(raw)
            item = next((it for it in collection.items if it.id == article.id), None)
            if item:
                return item
        except Exception as e:
            logger.warning(f"ArticleItem 読み込み失敗 ({article.id}): {e}")

    # フォールバック: 全日付ディレクトリを検索
    if not settings.data_dir.exists():
        return None
    categories = [
        "cv",
        "openreview",
        "lg",
        "ai",
        "cl",
        "industry",
        "community",
        "python",
    ]
    date_dirs = sorted(
        [d for d in settings.data_dir.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    for day_dir in date_dirs:
        if day_dir.name == article.date:
            continue  # 既に試した
        for category in categories:
            fp = day_dir / f"papers_{category}.json"
            if not fp.exists():
                continue
            try:
                raw = json.loads(fp.read_text(encoding="utf-8"))
                collection = DailyCollection.model_validate(raw)
                item = next(
                    (it for it in collection.items if it.id == article.id), None
                )
                if item:
                    return item
            except Exception:
                continue
    return None


async def build_rag_context(
    article: Article,
    query: str,
    full_item: ArticleItem | None = None,
) -> str:
    """
    ユーザーの質問 `query` に関連するコンテキストを構築して返す。

    論文 (arXiv / OpenReview):
        abstract_en + summary_ja + novelty_ja をすべて含める
        （これで通常の質問には十分な情報が揃う）

    記事 (RSS / Qiita / Zenn / Reddit 等):
        URL から本文を取得し、質問との関連スコアが高いチャンクを選択する
    """
    source_type = article.id.split(":")[0] if ":" in article.id else "unknown"
    parts: list[str] = []

    # ── 論文: 保存済みフィールドを全量使用 ───────────────────────
    if source_type in _PAPER_SOURCES:
        if full_item:
            if full_item.abstract_en:
                parts.append(f"## Abstract (原文)\n{full_item.abstract_en}")
            if full_item.summary_ja:
                parts.append(f"## 概要（日本語）\n{full_item.summary_ja}")
            if full_item.novelty_ja:
                parts.append(f"## 新規性・貢献\n{full_item.novelty_ja}")
            if full_item.key_points_ja:
                parts.append(
                    "## ポイント\n"
                    + "\n".join(f"- {p}" for p in full_item.key_points_ja)
                )
        elif article.summary_ja:
            parts.append(f"## 要約\n{article.summary_ja}")
        return "\n\n".join(parts)

    # ── 記事: URL フェッチ + 関連チャンク抽出（軽量 RAG） ────────
    # まず保存済みデータをベースに
    if full_item:
        if full_item.abstract_en:
            parts.append(f"## 記事概要\n{full_item.abstract_en}")
        if full_item.summary_ja:
            parts.append(f"## 要約（日本語）\n{full_item.summary_ja}")
        if full_item.key_points_ja:
            parts.append(
                "## ポイント\n" + "\n".join(f"- {p}" for p in full_item.key_points_ja)
            )
    elif article.summary_ja:
        parts.append(f"## 要約\n{article.summary_ja}")

    # URL から本文を取得してチャンク選択（キャッシュ済みなら再取得しない）
    if article.url not in _page_text_cache:
        _page_text_cache[article.url] = await _fetch_page_text(article.url)
    raw_text = _page_text_cache[article.url]
    if raw_text:
        chunks = _split_paragraphs(raw_text)
        # 先頭チャンク（記事のイントロ）は必ず含める
        intro = chunks[:_INTRO_CHUNKS]
        # 残りをスコアリングし、上位を追加（イントロ分を差し引いたK枚）
        query_tokens = _tokenize(query)
        scored = sorted(
            [(c, _score(c, query_tokens)) for c in chunks[_INTRO_CHUNKS:]],
            key=lambda x: -x[1],
        )
        extra = [c for c, _ in scored[: max(0, _TOP_K_CHUNKS - len(intro))]]
        top = intro + extra
        if top:
            parts.append("## 本文（関連箇所）\n" + "\n\n---\n\n".join(top))

    return "\n\n".join(parts)
