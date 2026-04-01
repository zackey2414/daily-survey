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
