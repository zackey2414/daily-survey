import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

logger = logging.getLogger(__name__)

# ディレクトリが存在しない場合は作成
settings.db_path.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{settings.db_path}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """テーブルを作成する（起動時に呼び出す）"""
    from app.db.models import Article, ChatSession, ChatMessage, UserTag  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def migrate_db() -> None:
    """既存 DB へのカラム追加マイグレーション（起動時に実行）"""
    async with engine.begin() as conn:
        try:
            await conn.execute(
                text("ALTER TABLE chat_sessions ADD COLUMN rag_context TEXT")
            )
            logger.info("chat_sessions.rag_context カラムを追加しました")
        except Exception:
            pass  # 既に存在する場合は無視

        try:
            await conn.execute(
                text(
                    "ALTER TABLE chat_messages ADD COLUMN used_search BOOLEAN DEFAULT 0"
                )
            )
            logger.info("chat_messages.used_search カラムを追加しました")
        except Exception:
            pass

        try:
            await conn.execute(
                text("ALTER TABLE chat_messages ADD COLUMN search_sources TEXT")
            )
            logger.info("chat_messages.search_sources カラムを追加しました")
        except Exception:
            pass

        try:
            await conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS user_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    article_id VARCHAR NOT NULL REFERENCES articles(id),
                    tag VARCHAR(50) NOT NULL,
                    created_at DATETIME DEFAULT (datetime('now')),
                    UNIQUE (article_id, tag)
                )
            """)
            )
        except Exception:
            pass


async def get_db():
    """FastAPI の Depends で使う DB セッション"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
