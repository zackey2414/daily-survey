"""
JSON ファイルに保存する収集データの Pydantic スキーマ定義
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Literal


class ArticleItem(BaseModel):
    """個別の論文・記事・ニュースアイテム"""

    id: str  # 例: "arxiv:2603.12345", "openreview:abc123", "qiita:xxxxx"
    title_en: str = ""
    title_ja: str = ""
    authors: list[str] = []
    abstract_en: str = ""
    summary_ja: str = ""  # LLM 生成の日本語要約
    novelty_ja: str = ""  # 論文の場合: 新規性・貢献の説明
    meta_learning_ja: str = ""  # 論文のメタ的な学び（問題定義・手法・評価のメタ視点）
    key_points_ja: list[str] = []  # 記事・ニュースの場合: ポイント箇条書き
    quantitative_metrics_ja: str = (
        ""  # 企業動向の場合: 定量指標（ベンチマーク名・スコア・改善率など）
    )
    published_date: str = ""  # "YYYY-MM-DD"
    url: str = ""
    pdf_url: str = ""
    source_type: Literal[
        "arxiv",
        "openreview",
        "rss",
        "qiita",
        "zenn",
        "reddit",
        "pypi",
        "github_trending",
        "python_news",
    ] = "rss"
    source_name: str = ""  # 例: "OpenAI", "Qiita", "r/MachineLearning"
    tags: list[str] = []
    hashtags: list[str] = []  # LLM 生成の内容タグ（例: ["深層学習", "物体検出"]）
    summarized: bool = False  # 要約済みフラグ


class DailyCollection(BaseModel):
    """1カテゴリの日次収集データ（JSON ファイル 1つ分）"""

    date: str  # "YYYY-MM-DD" (収集対象日 = 前日 JST)
    collection_date: str = ""  # "YYYY-MM-DD" (収集実行日 JST, ディレクトリ名と同じ)
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
    ]
    collected_at: str  # ISO 8601 収集実行日時 (JST)
    total: int = 0
    items: list[ArticleItem] = Field(default_factory=list)

    def model_post_init(self, __context) -> None:
        self.total = len(self.items)


class DailySummaryMeta(BaseModel):
    """サマリー一覧用メタデータ"""

    date: str  # "YYYY-MM-DD"
    title: str = ""
    preview: str = ""  # 冒頭 200文字
    file_path: str = ""


class Theme(BaseModel):
    """ユーザー定義の検索テーマ（data/themes.json に保存）"""

    id: str  # uuid4().hex[:12]（英数字のみ → CSS セレクタ・アンカー安全）
    name: str  # 表示名（例: "Edge-Cloud"）
    keywords: list[str] = []  # 検索に使う関連ワード（Gemini 生成 + 手動編集）
    enabled: bool = True  # 日次パイプラインの検索対象にするか
    created_at: str = ""  # ISO 8601 (JST)


class ThemeCollection(BaseModel):
    """1テーマの1日分の検索結果（data/{date}/themes/{theme_id}.json）"""

    theme_id: str
    theme_name: str
    keywords_snapshot: list[str] = []  # 検索時点のキーワード（後で編集されるため記録）
    date: str  # "YYYY-MM-DD"（検索対象日 = 前日 JST）
    collection_date: str = ""  # "YYYY-MM-DD"（収集実行日 JST, ディレクトリ名）
    collected_at: str = ""  # ISO 8601 収集実行日時
    source_coverage: list[str] = []  # この日に実際に検索/フィルタできたソース名
    total: int = 0
    items: list[ArticleItem] = Field(default_factory=list)

    def model_post_init(self, __context) -> None:
        self.total = len(self.items)


class EnglishChunk(BaseModel):
    """英文を意味のまとまり（チャンク）で区切った1単位。

    t を半角スペースで連結すると元の文 (EnglishSentence.en) に概ね一致する。
    機能語（the/of/and 等）は g を空にして「語義なし（タップ不可）」とする。
    """

    t: str  # 英語チャンク（句読点は直前チャンク末尾に付ける）
    g: str = ""  # 日本語語義（赤シートで表示）。空文字なら語義なし


class EnglishSentence(BaseModel):
    """英文1文と、その全訳・チャンク語義。"""

    en: str  # 英文（通し読み用のフォールバック）
    ja: str = ""  # 文全体の日本語訳（赤シートで表示）
    chunks: list[EnglishChunk] = Field(default_factory=list)


class EnglishParagraph(BaseModel):
    """段落（文のまとまり）。"""

    sentences: list[EnglishSentence] = Field(default_factory=list)


class EnglishDigest(BaseModel):
    """一面まとめの英語版（英語多読用）。summaries/{date}.en.json に保存。

    その日の最重要トピック1本を、有名論文のような明瞭な学術英語で書き起こし、
    文単位の全訳とチャンク単位の語義を付与したもの。
    """

    date: str  # "YYYY-MM-DD"（収集実行日）
    topic_title: str = ""  # 取り上げたトピックの英語タイトル
    reading_minutes: int = 0  # 想定読了時間（分）
    model: str = ""  # 生成に使った Gemini モデル名
    generated_at: str = ""  # ISO 8601 (JST)
    paragraphs: list[EnglishParagraph] = Field(default_factory=list)
