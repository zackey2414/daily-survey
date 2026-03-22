from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()


class Settings:
    # Gemini API
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_summary_model: str = os.getenv("GEMINI_SUMMARY_MODEL", "gemini-2.5-pro")
    gemini_chat_model: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
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
    schedule_hour: int = int(os.getenv("SCHEDULE_HOUR", "9"))
    schedule_minute: int = int(os.getenv("SCHEDULE_MINUTE", "0"))

    # ディレクトリ
    data_dir: Path = Path(os.getenv("DATA_DIR", "data"))
    summaries_dir: Path = Path(os.getenv("SUMMARIES_DIR", "summaries"))
    db_path: Path = Path(os.getenv("DB_PATH", "db/survey.db"))
    log_dir: Path = Path(os.getenv("LOG_DIR", "logs"))

    # 収集設定
    arxiv_max_results: int = 20
    industry_max_per_company: int = 5
    community_max_results: int = 20  # SNS 全ソース合計上限
    python_max_results: int = 10  # Python 情報合計上限
    openreview_max_results: int = 20

    # 企業ブログ RSS
    industry_rss_feeds: dict[str, str] = {
        "OpenAI": "https://openai.com/blog/rss.xml",
        "Google": "https://blog.google/technology/ai/rss/",
        "Anthropic": "https://www.anthropic.com/rss.xml",
        "Meta": "https://ai.meta.com/blog/rss/",
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

    # OpenReview 対象学会
    openreview_venues: list[str] = [
        "CVPR",
        "NeurIPS",
        "ICLR",
        "ICCV",
        "ICML",
        "AAAI",
        "ACL",
        "ECCV",
        "EMNLP",
        "IJCAI",
    ]

    # Reddit 対象サブレディット
    reddit_subreddits: list[str] = [
        "MachineLearning",
        "artificial",
        "LocalLLaMA",
    ]


settings = Settings()
