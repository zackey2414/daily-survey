from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()


class Settings:
    # Gemini API
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    # ダイジェスト（一面まとめ）生成用。flash-preview を使用
    gemini_summary_model: str = os.getenv(
        "GEMINI_SUMMARY_MODEL", "gemini-3-flash-preview"
    )
    # 個別記事要約・チャット・キーワード生成用。最安の flash-lite を使用
    gemini_chat_model: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.1-flash-lite")
    gemini_search_threshold: float = float(os.getenv("GEMINI_SEARCH_THRESHOLD", "0.3"))

    # Reddit API
    reddit_client_id: str = os.getenv("REDDIT_CLIENT_ID", "")
    reddit_client_secret: str = os.getenv("REDDIT_CLIENT_SECRET", "")
    reddit_user_agent: str = os.getenv("REDDIT_USER_AGENT", "AI-Daily-Survey/1.0")

    # Qiita API
    qiita_access_token: str = os.getenv("QIITA_ACCESS_TOKEN", "")

    # SMTP
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_username: str = os.getenv("SMTP_USERNAME", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")
    smtp_to: str = os.getenv("SMTP_TO", "")

    # スケジューラ
    # 12:00 JST (= 03:00 UTC) 実行。arXiv の announcement は約 00:00 UTC で、
    # submittedDate インデックス反映に時間がかかるため、9時(=00:00 UTC)実行だと
    # 当日分が 0 件になりやすい。3時間後の正午にずらして索引反映を待つ。
    schedule_hour: int = int(os.getenv("SCHEDULE_HOUR", "12"))
    schedule_minute: int = int(os.getenv("SCHEDULE_MINUTE", "0"))

    # ディレクトリ
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    summaries_dir: Path = Path(os.getenv("SUMMARIES_DIR", "summaries"))
    db_path: Path = Path(os.getenv("DB_PATH", "db/survey.db"))
    log_dir: Path = Path(os.getenv("LOG_DIR", "logs"))
    models_dir: Path = Path(os.getenv("MODELS_DIR", "models"))

    # ローカル TTS（英語版の音声合成。Kokoro-82M を onnxruntime で実行 = API 課金なし）
    kokoro_voice: str = os.getenv("KOKORO_VOICE", "af_heart")
    kokoro_speed: float = float(os.getenv("KOKORO_SPEED", "1.0"))

    # 収集設定
    arxiv_max_results: int = 20
    industry_max_per_company: int = 5
    community_max_results: int = 20  # SNS 全ソース合計上限
    python_max_results: int = 10  # Python 情報合計上限（後方互換用）
    openreview_max_results: int = 20

    # GitHub API（トークンがあればレートリミット緩和: 60→5000 req/h）
    github_token: str = os.getenv("GITHUB_TOKEN", "")

    # GitHub Trending 設定
    github_trending_max_results: int = 10  # 各期間あたりの取得上限（各タブ10件表示）
    github_trending_stale_days: int = 30  # 再収集の閾値（日数）
    github_trending_keywords: list[str] = [
        "AI",
        "LLM",
        "ML",
        "deep learning",
        "machine learning",
        "GPT",
        "transformer",
        "neural",
        "NLP",
        "agent",
        "RAG",
        "diffusion",
        "fine-tuning",
        "fine tuning",
        "inference",
        "embedding",
        "langchain",
        "llama",
        "mistral",
        "ollama",
        "vector",
        "chatbot",
        "generative",
        "multimodal",
        "vision",
        "reinforcement learning",
        "computer vision",
        "stable diffusion",
    ]

    # 企業ブログ RSS
    # 注: Anthropic は公式 RSS を廃止（anthropic.com/rss.xml 等が 404）したため、
    #     anthropic.com を対象にした Google News RSS で自社発表を拾う。
    #     Meta も AI ブログ (ai.meta.com/blog/rss) が 404 化したため、公式の
    #     Meta Engineering ブログ RSS に差し替え（AI/システム系を扱い、企業ニュースの
    #     ノイズが少ない）。
    industry_rss_feeds: dict[str, str] = {
        "OpenAI": "https://openai.com/blog/rss.xml",
        "Google": "https://blog.google/technology/ai/rss/",
        "Anthropic": "https://news.google.com/rss/search?q=site:anthropic.com&hl=en-US&gl=US&ceid=US:en",
        "Meta": "https://engineering.fb.com/feed/",
        "Amazon": "https://aws.amazon.com/blogs/machine-learning/feed/",
        "Alibaba": "https://www.alibabacloud.com/blog/feed/tag/ai",
    }

    # 海外ニュースメディア RSS（AI企業関連報道収集用）
    news_rss_feeds: list[str] = [
        "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "https://techcrunch.com/feed/",
        "https://www.theverge.com/rss/index.xml",
        "https://www.wired.com/feed/tag/artificial-intelligence/rss",
    ]
    news_max_results: int = 15
    # フィルタリングキーワード（AI企業・製品名）
    news_filter_keywords: list[str] = [
        "OpenAI",
        "Google",
        "Anthropic",
        "Meta",
        "Amazon",
        "Microsoft",
        "Alibaba",
        "xAI",
        "Grok",
        "ChatGPT",
        "Gemini",
        "Claude",
        "Copilot",
        "GPT",
        "DeepMind",
        "Llama",
        "Mistral",
        "Cohere",
        "Perplexity",
    ]

    # ── LLM・AIエージェント動向（ai_dev カテゴリ） ──────────────
    # コーディングAI ツール・LLM ベンダーの公式アップデート（changelog/release/blog）RSS。
    # 既存 industry とは別に、Claude Code / Codex / Cursor / Copilot などの開発ツールや
    # Mistral / HuggingFace / DeepMind のモデルリリースを横断収集する。
    # （URL は 2026-06 時点で feed XML を返すことを確認済み）
    ai_dev_rss_feeds: dict[str, str] = {
        "Claude Code": "https://github.com/anthropics/claude-code/releases.atom",
        "OpenAI Codex": "https://github.com/openai/codex/releases.atom",
        "Cursor": "https://www.cursor.com/changelog/rss.xml",
        "GitHub Copilot": "https://github.blog/changelog/label/copilot/feed/",
        "Mistral": "https://mistral.ai/rss.xml",
        "Hugging Face": "https://huggingface.co/blog/feed.xml",
        "Google DeepMind": "https://deepmind.google/blog/rss.xml",
    }
    ai_dev_max_per_source: int = 5  # 公式フィード1ソースあたりの上限

    # LLM/エージェント/コーディングAI の性能・ベンチマーク記事を扱う実務寄りニュース源。
    # ai_dev_filter_keywords でフィルタする。
    ai_dev_news_feeds: list[str] = [
        "https://simonwillison.net/atom/everything/",
        "https://venturebeat.com/category/ai/feed/",
        "https://jack-clark.net/feed/",
    ]
    ai_dev_news_max_results: int = 15
    # LLM/AIエージェント/コーディングAI 関連かを判定するキーワード
    ai_dev_filter_keywords: list[str] = [
        "LLM",
        "large language model",
        "frontier model",
        "foundation model",
        "GPT",
        "ChatGPT",
        "Claude",
        "Claude Code",
        "Anthropic",
        "OpenAI",
        "Codex",
        "Gemini",
        "Gemma",
        "DeepMind",
        "Llama",
        "Mistral",
        "Qwen",
        "DeepSeek",
        "Grok",
        "coding agent",
        "AI agent",
        "agentic",
        "agent",
        "LangChain",
        "Cursor",
        "Copilot",
        "Windsurf",
        "Aider",
        "Devin",
        "code generation",
        "MCP",
        "Model Context Protocol",
        "tool use",
        "benchmark",
        "SWE-bench",
        "HumanEval",
        "LiveCodeBench",
        "leaderboard",
        "reasoning model",
        "context window",
        "open weights",
        "model release",
    ]

    # OpenReview 対象学会
    # NeurIPS / ICLR / ICML は OpenReview 上に投稿を公開している（取得可能）。
    # CVPR / ICCV / ECCV は CV の主要学会だが現状は投稿を非公開（将来公開時に備えて残す）。
    # AAAI / ACL / EMNLP / IJCAI は OpenReview 上に公開投稿が無く常に 0 件のため除外。
    openreview_venues: list[str] = [
        "NeurIPS",
        "ICLR",
        "ICML",
        "CVPR",
        "ICCV",
        "ECCV",
    ]

    # 検索テーマのデフォルト（初回起動時に data/themes.json へ投入される）
    # data/ は gitignore 対象のため、シード定義はコード側 (config) に置く。
    # キーワードは静的定義（起動時に外部 API へ依存しない）。後から UI で編集可能。
    default_themes: list[dict] = [
        {
            "name": "画像検索",
            "keywords": [
                "image retrieval",
                "image search",
                "content-based image retrieval",
                "content-based retrieval",
                "visual search",
                "image-to-image retrieval",
                "video retrieval",
                "cross-modal retrieval",
                "instance retrieval",
            ],
        },
        {
            "name": "物体中心画像検索",
            "keywords": [
                "object-centric",
                "object-centric retrieval",
                "object-centric image retrieval",
                "object-centric learning",
                "object retrieval",
                "object-level retrieval",
                "instance retrieval",
                "compositional retrieval",
            ],
        },
        {
            "name": "エッジクラウド協調AI",
            "keywords": [
                "edge-cloud",
                "edge computing",
                "cloud-edge",
                "edge-cloud collaboration",
                "collaborative inference",
                "split computing",
                "split inference",
                "on-device inference",
                "edge AI",
                "edge intelligence",
                "model partitioning",
                "device-edge-cloud",
            ],
        },
    ]

    # Reddit 対象サブレディット
    reddit_subreddits: list[str] = [
        "MachineLearning",
        "artificial",
        "LocalLLaMA",
    ]


settings = Settings()
