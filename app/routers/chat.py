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
from google import genai as genai_new
from google.genai.types import (
    Content,
    GenerateContentConfig,
    GoogleSearch,
    Part,
    Tool,
)
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

# 新 SDK クライアント（チャット用）
_genai_client = genai_new.Client(api_key=settings.gemini_api_key)

# 旧 SDK（タイトル生成用に維持）
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

    return await _render_chat_panel(
        request, article, chat_session, chat_session.messages, db
    )


# ── メッセージ送信 ──────────────────────────────────────────────────
@router.post(
    "/{article_id:path}/sessions/{session_id}/messages", response_class=HTMLResponse
)
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
    gen_result = await _generate_response(
        article, chat_session.messages + [user_msg], message, rag_context
    )

    # AI メッセージを保存
    ai_msg = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=gen_result["text"],
        used_search=gen_result["used_search"],
        search_sources=(
            json.dumps(gen_result["sources"], ensure_ascii=False)
            if gen_result["sources"]
            else None
        ),
    )
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
            "messages": [ai_msg],
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
        return await _render_chat_panel(
            request, article, remaining, remaining.messages, db
        )

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
    if q:
        stmt = (
            select(ChatSession)
            .join(ChatMessage, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatSession.title.ilike(f"%{q}%") | ChatMessage.content.ilike(f"%{q}%")
            )
            .options(selectinload(ChatSession.article))
            .distinct()
            .order_by(ChatSession.updated_at.desc())
            .limit(50)
        )
    else:
        # 検索なし: 更新日時降順で最新50件を表示
        stmt = (
            select(ChatSession)
            .options(selectinload(ChatSession.article))
            .order_by(ChatSession.updated_at.desc())
            .limit(50)
        )

    result = await db.execute(stmt)
    sessions = result.scalars().all()

    article_sessions = [s for s in sessions if s.article_id is not None]
    daily_sessions = [
        s for s in sessions if s.article_id is None and s.date is not None
    ]

    return templates.TemplateResponse(
        "pages/chat_search.html",
        {
            "request": request,
            "sessions": sessions,
            "article_sessions": article_sessions,
            "daily_sessions": daily_sessions,
            "query": q,
        },
    )


# ── 内部ヘルパー ────────────────────────────────────────────────────


async def _get_or_create_article(article_id: str, db: AsyncSession) -> Article | None:
    """DB から Article を取得し、なければ JSON ファイルから作成する"""
    article = await db.get(Article, article_id)
    if article:
        return article

    # JSON ファイルから検索（最新日付順）
    categories = [
        "cv",
        "openreview",
        "lg",
        "ai",
        "cl",
        "industry",
        "industry_news",
        "community",
        "github_trending",
        "python",
    ]
    for date_str in list_available_dates():
        for category in categories:
            file_path = settings.data_dir / date_str / f"papers_{category}.json"
            if not file_path.exists():
                continue
            try:
                raw = json.loads(file_path.read_text(encoding="utf-8"))
                collection = DailyCollection.model_validate(raw)
                item = next(
                    (it for it in collection.items if it.id == article_id), None
                )
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


def _extract_grounding_info(response) -> tuple[bool, list[dict], str]:
    """レスポンスからグラウンディング情報を抽出する。

    Returns:
        (used_search, sources, cited_text)
        - sources: [{"title": str, "uri": str}, ...]
        - cited_text: インライン引用 [1][2] を埋め込んだテキスト
    """
    try:
        meta = response.candidates[0].grounding_metadata
        if not meta or not meta.grounding_chunks:
            return False, [], response.text
    except (AttributeError, IndexError):
        return False, [], response.text

    # ソース一覧を構築
    sources: list[dict] = []
    for chunk in meta.grounding_chunks:
        web = getattr(chunk, "web", None)
        if web:
            sources.append({"title": web.title or "", "uri": web.uri or ""})

    if not sources:
        return False, [], response.text

    # grounding_supports からインライン引用を挿入
    text = response.text
    supports = meta.grounding_supports or []
    if supports:
        # end_index 降順でソート（後ろから挿入して位置ズレを防ぐ）
        indexed = []
        for s in supports:
            seg = s.segment
            if not seg or not seg.text:
                continue
            indices = (
                list(s.grounding_chunk_indices) if s.grounding_chunk_indices else []
            )
            if not indices:
                continue
            # テキスト中の該当箇所を特定
            seg_text = seg.text.strip()
            pos = text.find(seg_text)
            if pos == -1:
                continue
            end_pos = pos + len(seg_text)
            citation_marks = "".join(f"[{i + 1}]" for i in indices if i < len(sources))
            indexed.append((end_pos, citation_marks))

        # 重複除去・降順ソートして後ろから挿入
        seen_positions: set[int] = set()
        for end_pos, marks in sorted(indexed, key=lambda x: x[0], reverse=True):
            if end_pos in seen_positions:
                continue
            seen_positions.add(end_pos)
            text = text[:end_pos] + marks + text[end_pos:]

    return True, sources, text


async def _generate_response(
    article: Article,
    messages: list[ChatMessage],
    user_message: str,
    rag_context: str,
) -> dict:
    """
    Gemini Flash を使ってチャット応答を生成する。
    Google Search グラウンディング付き (google-genai SDK)。

    Returns:
        {"text": str, "used_search": bool, "sources": list[dict]}
    """
    system_instruction = f"""あなたは以下の論文・記事についての質問に答える専門AIアシスタントです。
ユーザーの質問には、以下に示すコンテキストを根拠にして日本語で回答してください。
コンテキストに記載のない概念・背景知識・最新情報について質問された場合は、Google検索ツールを使って正確な情報を取得してから回答してください。
コンテキスト内の情報だけで回答できる場合は検索を使わないでください。

# 対象記事
タイトル: {article.title_ja or article.title_en}
URL: {article.url}

# コンテキスト
{rag_context}"""

    # 会話履歴を新 SDK 形式に変換
    contents: list[Content] = []
    for msg in messages[:-1]:
        role = "user" if msg.role == "user" else "model"
        contents.append(Content(role=role, parts=[Part(text=msg.content)]))
    contents.append(Content(role="user", parts=[Part(text=user_message)]))

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _genai_client.models.generate_content(
                model=settings.gemini_chat_model,
                contents=contents,
                config=GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=[Tool(google_search=GoogleSearch())],
                ),
            ),
        )
        used_search, sources, cited_text = _extract_grounding_info(response)
        return {
            "text": cited_text,
            "used_search": used_search,
            "sources": sources,
        }
    except Exception as e:
        logger.error(f"チャット応答生成失敗: {e}")
        return {
            "text": f"申し訳ありません、応答の生成に失敗しました。エラー: {e}",
            "used_search": False,
            "sources": [],
        }


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
