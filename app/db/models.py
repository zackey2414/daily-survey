from datetime import datetime
import json as _json

from sqlalchemy import (
    Boolean,
    String,
    Text,
    Integer,
    ForeignKey,
    DateTime,
    func,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.database import Base


class Article(Base):
    """チャットと記事を紐付けるテーブル"""

    __tablename__ = "articles"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # "arxiv:2603.12345"
    date: Mapped[str] = mapped_column(String(10), nullable=False)  # "YYYY-MM-DD"
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    title_ja: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary_ja: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chat_sessions: Mapped[list["ChatSession"]] = relationship(
        "ChatSession", back_populates="article", cascade="all, delete-orphan"
    )
    user_tags: Mapped[list["UserTag"]] = relationship(
        "UserTag", back_populates="article", cascade="all, delete-orphan"
    )
    favorites: Mapped[list["Favorite"]] = relationship(
        "Favorite", back_populates="article", cascade="all, delete-orphan"
    )


class ChatSession(Base):
    """1記事または1日全体に対するチャットセッション

    article_id がセットされていれば記事チャット、
    date のみセットされていれば日毎チャット。
    """

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("articles.id"), nullable=True
    )
    date: Mapped[str | None] = mapped_column(String(10), nullable=True, default=None)
    title: Mapped[str] = mapped_column(
        String(100), nullable=False, default="新しいチャット"
    )
    rag_context: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    article: Mapped["Article | None"] = relationship(
        "Article", back_populates="chat_sessions"
    )
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )

    @property
    def is_daily(self) -> bool:
        """日毎チャットかどうか"""
        return self.article_id is None and self.date is not None


class ChatMessage(Base):
    """チャットの1メッセージ"""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chat_sessions.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    used_search: Mapped[bool] = mapped_column(Boolean, default=False)
    search_sources: Mapped[str | None] = mapped_column(
        Text, nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    session: Mapped["ChatSession"] = relationship(
        "ChatSession", back_populates="messages"
    )

    @property
    def search_sources_parsed(self) -> list[dict]:
        """JSON 文字列をパースしてソース一覧を返す"""
        if not self.search_sources:
            return []
        try:
            return _json.loads(self.search_sources)
        except (_json.JSONDecodeError, TypeError):
            return []


class UserTag(Base):
    """ユーザーが手動で付与するタグ"""

    __tablename__ = "user_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[str] = mapped_column(
        String, ForeignKey("articles.id"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    article: Mapped["Article"] = relationship("Article", back_populates="user_tags")

    __table_args__ = (UniqueConstraint("article_id", "tag"),)


class Favorite(Base):
    """ユーザーがお気に入り登録した記事（1記事につき1件）"""

    __tablename__ = "favorites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[str] = mapped_column(
        String, ForeignKey("articles.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    article: Mapped["Article"] = relationship("Article", back_populates="favorites")

    __table_args__ = (UniqueConstraint("article_id"),)
