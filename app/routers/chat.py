"""
チャット機能ルーター（HTMX 対応）
- POST /chat/{article_id}/sessions          : 新規チャットセッション作成
- GET  /chat/{article_id}/sessions/{sid}    : セッション読み込み（HTMX swap）
- POST /chat/{article_id}/sessions/{sid}/messages : メッセージ送信
- GET  /chat/search                         : チャット検索
"""
import asyncio
import json
import logging

import google.generativeai as genai
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.database import get_db
from app.db.models import Article, ChatMessage, ChatSession
from app.schemas import DailyCollection
from app.services.pipeline import list_available_dates
from app.services.rag import build_rag_context, load_article_item

from app.jinja import templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat")

genai.configure(api_key=settings.gemini_api_key)


def _get_chat_model() -> genai.GenerativeModel:
    return genai.GenerativeModel(settings.gemini_chat_model)


# ── 最新セッション取得（チャットボタン初回クリック用） ───────────────
@router.get("/{article_id:path}/sessions/latest", response_class=HTMLResponse)
async def get_latest_session(
    request: Request,
    article_id: str,
    db: AsyncSession = Depends(get_db),
):
    article = await _get_or_create_article(article_id, db)
    if not article:
        return HTMLResponse(
            '<div class="px-5 py-4 text-sm text-red-500 text-center">'
            "チャット機能はこの記事では利用できません。"
            "</div>",
            status_code=200,
        )

    stmt = (
        select(ChatSession)
        .where(ChatSession.article_id == article_id)
        .options(selectinload(ChatSession.messages))
        .order_by(ChatSession.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    chat_session = result.scalar_one_or_none()

    if chat_session is None:
        # セッションがなければ自動作成
        chat_session = ChatSession(article_id=article_id, title="新しいチャット")
        db.add(chat_session)
        await db.commit()
        await db.refresh(chat_session)
        messages: list[ChatMessage] = []
    else:
        messages = chat_session.messages

    return await _render_chat_panel(request, article, chat_session, messages, db)


# ── セッション作成 ─────────────────────────────────────────────────
@router.post("/{article_id:path}/sessions", response_class=HTMLResponse)
async def create_session(
    request: Request,
    article_id: str,
    db: AsyncSession = Depends(get_db),
):
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    # 最新セッションが空（メッセージなし）なら新規作成を拒否し、その空セッションを返す
    stmt_latest = (
        select(ChatSession)
        .where(ChatSession.article_id == article_id)
        .options(selectinload(ChatSession.messages))
        .order_by(ChatSession.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt_latest)
    latest = result.scalar_one_or_none()
    if latest is not None and len(latest.messages) == 0:
        return await _render_chat_panel(request, article, latest, [], db)

    session = ChatSession(article_id=article_id, title="新しいチャット")
    db.add(session)
    await db.commit()
    await db.refresh(session)

    return await _render_chat_panel(request, article, session, [], db)


# ── セッション読み込み ──────────────────────────────────────────────
@router.get("/{article_id:path}/sessions/{session_id}", response_class=HTMLResponse)
async def get_session(
    request: Request,
    article_id: str,
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    stmt = (
        select(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.article_id == article_id)
        .options(selectinload(ChatSession.messages))
    )
    result = await db.execute(stmt)
    chat_session = result.scalar_one_or_none()
    if not chat_session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    return await _render_chat_panel(request, article, chat_session, chat_session.messages, db)


# ── メッセージ送信 ──────────────────────────────────────────────────
@router.post("/{article_id:path}/sessions/{session_id}/messages", response_class=HTMLResponse)
async def send_message(
    request: Request,
    article_id: str,
    session_id: int,
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    article = await db.get(Article, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    stmt = (
        select(ChatSession)
        .where(ChatSession.id == session_id, ChatSession.article_id == article_id)
        .options(selectinload(ChatSession.messages))
    )
    result = await db.execute(stmt)
    chat_session = result.scalar_one_or_none()
    if not chat_session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    # ユーザーメッセージを保存
    user_msg = ChatMessage(session_id=session_id, role="user", content=message)
    db.add(user_msg)
    await db.flush()

    # RAG コンテキストをセッションにキャッシュ（初回メッセージ時のみ構築）
    if not chat_session.rag_context:
        full_item = await asyncio.get_event_loop().run_in_executor(
            None, load_article_item, article
        )
        rag_context = await build_rag_context(article, message, full_item)
        chat_session.rag_context = rag_context
    else:
        rag_context = chat_session.rag_context

    # AI 応答を生成
    ai_response = await _generate_response(
        article, chat_session.messages + [user_msg], message, rag_context
    )

    # AI メッセージを保存
    ai_msg = ChatMessage(session_id=session_id, role="assistant", content=ai_response)
    db.add(ai_msg)

    # 初回メッセージのときセッションタイトルを自動生成
    if len(chat_session.messages) == 0:
        chat_session.title = await _generate_title(message)

    await db.commit()

    # 新しいメッセージのみ HTML で返す（HTMX append）
    return templates.TemplateResponse(
        "components/chat/messages.html",
        {
            "request": request,
            "messages": [user_msg, ai_msg],
        },
    )


# ── セッション削除 ──────────────────────────────────────────────────
@router.delete("/{article_id:path}/sessions/{session_id}", response_class=HTMLResponse)
async def delete_session(
    request: Request,
    article_id: str,
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    article = await _get_or_create_article(article_id, db)
    if not article:
        raise HTTPException(status_code=404, detail="記事が見つかりません")

    chat_session = await db.get(ChatSession, session_id)
    if not chat_session or chat_session.article_id != article_id:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    await db.delete(chat_session)
    await db.commit()

    # 残りのセッションがあれば最新を表示、なければ新規作成
    stmt = (
        select(ChatSession)
        .where(ChatSession.article_id == article_id)
        .options(selectinload(ChatSession.messages))
        .order_by(ChatSession.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    remaining = result.scalar_one_or_none()

    if remaining:
        return await _render_chat_panel(request, article, remaining, remaining.messages, db)

    new_session = ChatSession(article_id=article_id, title="新しいチャット")
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)
    return await _render_chat_panel(request, article, new_session, [], db)


# ── チャット検索 ────────────────────────────────────────────────────
@router.get("/search", response_class=HTMLResponse)
async def search_chats(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
):
    sessions = []
    if q:
        stmt = (
            select(ChatSession)
            .join(ChatMessage, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatSession.title.ilike(f"%{q}%")
                | ChatMessage.content.ilike(f"%{q}%")
            )
            .options(selectinload(ChatSession.article))
            .distinct()
            .order_by(ChatSession.updated_at.desc())
            .limit(50)
        )
        result = await db.execute(stmt)
        sessions = result.scalars().all()

    return templates.TemplateResponse(
        "pages/chat_search.html",
        {"request": request, "sessions": sessions, "query": q},
    )


# ── 内部ヘルパー ────────────────────────────────────────────────────

async def _get_or_create_article(article_id: str, db: AsyncSession) -> Article | None:
    """DB から Article を取得し、なければ JSON ファイルから作成する"""
    article = await db.get(Article, article_id)
    if article:
        return article

    # JSON ファイルから検索（最新日付順）
    categories = ["cv", "openreview", "lg", "ai", "cl", "industry", "community", "python"]
    for date_str in list_available_dates():
        for category in categories:
            file_path = settings.data_dir / date_str / f"papers_{category}.json"
            if not file_path.exists():
                continue
            try:
                raw = json.loads(file_path.read_text(encoding="utf-8"))
                collection = DailyCollection.model_validate(raw)
                item = next((it for it in collection.items if it.id == article_id), None)
                if item:
                    article = Article(
                        id=item.id,
                        date=date_str,
                        category=category,
                        title_ja=item.title_ja or item.title_en or "",
                        title_en=item.title_en or "",
                        url=item.url or "",
                        summary_ja=item.summary_ja or "",
                    )
                    db.add(article)
                    await db.commit()
                    await db.refresh(article)
                    logger.info(f"Article {article_id} を JSON から DB に登録しました")
                    return article
            except Exception as e:
                logger.warning(f"JSON 検索中にエラー ({file_path}): {e}")
                continue

    return None


async def _render_chat_panel(
    request: Request,
    article: Article,
    session: ChatSession,
    messages: list[ChatMessage],
    db: AsyncSession,
) -> HTMLResponse:
    """チャットパネル HTML を生成する"""
    # 同記事の全セッション一覧（ナビゲーション用）
    stmt = (
        select(ChatSession)
        .where(ChatSession.article_id == article.id)
        .order_by(ChatSession.created_at)
    )
    result = await db.execute(stmt)
    all_sessions = result.scalars().all()
    current_index = next(
        (i for i, s in enumerate(all_sessions) if s.id == session.id), 0
    )

    return templates.TemplateResponse(
        "components/chat/panel.html",
        {
            "request": request,
            "article": article,
            "session": session,
            "messages": messages,
            "all_sessions": all_sessions,
            "current_index": current_index,
            "total_sessions": len(all_sessions),
        },
    )


async def _generate_response(
    article: Article,
    messages: list[ChatMessage],
    user_message: str,
    rag_context: str,
) -> str:
    """
    Gemini Flash を使ってチャット応答を生成する。

    rag_context はセッション初回メッセージ時に構築済みのものを受け取る。
    （JSON 読み込み・URL フェッチ・チャンク選択はここでは行わない）
    """
    system_instruction = f"""あなたは以下の論文・記事についての質問に答える専門AIアシスタントです。
ユーザーの質問には、以下に示すコンテキストを根拠にして日本語で回答してください。
コンテキストに記載のない情報を求められた場合は、その旨を明示してから一般知識で補足してください。

# 対象記事
タイトル: {article.title_ja or article.title_en}
URL: {article.url}

# コンテキスト
{rag_context}"""

    # 会話履歴（最後のユーザーメッセージを除く）
    history = []
    for msg in messages[:-1]:
        role = "user" if msg.role == "user" else "model"
        history.append({"role": role, "parts": [msg.content]})

    try:
        model = genai.GenerativeModel(
            settings.gemini_chat_model,
            system_instruction=system_instruction,
        )
        chat = model.start_chat(history=history)
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: chat.send_message(user_message)
        )
        return response.text
    except Exception as e:
        logger.error(f"チャット応答生成失敗: {e}")
        return f"申し訳ありません、応答の生成に失敗しました。エラー: {e}"


async def _generate_title(first_message: str) -> str:
    """初回メッセージからセッションタイトルを自動生成する"""
    prompt = f"以下の質問を30文字以内の日本語タイトルにしてください。タイトルのみ出力してください。\n\n{first_message}"
    try:
        model = _get_chat_model()
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: model.generate_content(prompt)
        )
        return response.text.strip()[:100]
    except Exception:
        return first_message[:30]
