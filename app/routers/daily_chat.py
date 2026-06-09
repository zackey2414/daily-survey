"""
日毎チャット機能ルーター（HTMX 対応）
その日の全記事を対象にしたチャット
- GET  /daily-chat/{date}/sessions/latest   : 最新セッション取得
- POST /daily-chat/{date}/sessions          : 新規セッション作成
- GET  /daily-chat/{date}/sessions/{sid}    : セッション読み込み
- POST /daily-chat/{date}/sessions/{sid}/messages : メッセージ送信
- DELETE /daily-chat/{date}/sessions/{sid}  : セッション削除
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
from app.db.models import ChatMessage, ChatSession
from app.services.pipeline import load_daily_data

from app.jinja import templates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/daily-chat")

_genai_client = genai_new.Client(api_key=settings.gemini_api_key)
genai.configure(api_key=settings.gemini_api_key)


def _get_chat_model() -> genai.GenerativeModel:
    return genai.GenerativeModel(settings.gemini_chat_model)


def _build_daily_rag_context(date_str: str) -> str:
    """その日の全記事の要約を結合してRAGコンテキストを構築する"""
    data = load_daily_data(date_str)
    parts: list[str] = []

    category_labels = {
        "cv": "CV論文 (cs.CV)",
        "openreview": "CV論文 (OpenReview)",
        "lg": "機械学習 (cs.LG)",
        "ai": "人工知能 (cs.AI)",
        "cl": "自然言語処理 (cs.CL)",
        "industry": "企業動向（自社発表）",
        "industry_news": "企業動向（その他報道）",
        "community": "コミュニティ",
        "github_trending": "GitHub Trending",
    }

    for cat, items in data.items():
        if not items:
            continue
        label = category_labels.get(cat, cat)
        parts.append(f"\n## {label}")
        for item in items:
            title = item.title_ja or item.title_en
            summary = item.summary_ja or item.abstract_en or ""
            parts.append(f"### {title}")
            if summary:
                parts.append(summary[:500])
            if item.novelty_ja:
                parts.append(f"新規性: {item.novelty_ja[:200]}")
            if item.key_points_ja:
                parts.append("要点: " + " / ".join(item.key_points_ja[:3]))
            parts.append("")

    return "\n".join(parts) if parts else "この日の記事データはありません。"


# ── 最新セッション取得 ─────────────────────────────────────────────
@router.get("/{date_str}/sessions/latest", response_class=HTMLResponse)
async def get_latest_session(
    request: Request,
    date_str: str,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ChatSession)
        .where(ChatSession.date == date_str, ChatSession.article_id.is_(None))
        .options(selectinload(ChatSession.messages))
        .order_by(ChatSession.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        # セッションがない場合は空パネルを表示（セッションは初回メッセージ時に作成）
        return await _render_daily_chat_panel(request, date_str, None, [], db)

    return await _render_daily_chat_panel(
        request, date_str, session, session.messages, db
    )


# ── セッション作成 ─────────────────────────────────────────────────
@router.post("/{date_str}/sessions", response_class=HTMLResponse)
async def create_session(
    request: Request,
    date_str: str,
    db: AsyncSession = Depends(get_db),
):
    # 最新セッションが空なら新規作成を拒否
    stmt_latest = (
        select(ChatSession)
        .where(ChatSession.date == date_str, ChatSession.article_id.is_(None))
        .options(selectinload(ChatSession.messages))
        .order_by(ChatSession.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt_latest)
    latest = result.scalar_one_or_none()
    if latest is not None and len(latest.messages) == 0:
        return await _render_daily_chat_panel(request, date_str, latest, [], db)

    session = ChatSession(date=date_str, title="新しいチャット")
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return await _render_daily_chat_panel(request, date_str, session, [], db)


# ── 初回メッセージ（セッション作成 + メッセージ送信） ─────────────────
@router.post("/{date_str}/first-message", response_class=HTMLResponse)
async def first_message(
    request: Request,
    date_str: str,
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """セッションがない状態から初回メッセージを送信する。
    セッション作成 → メッセージ送信 → パネル全体を返す。"""
    session = ChatSession(date=date_str, title="新しいチャット")
    db.add(session)
    await db.flush()

    # ユーザーメッセージを保存
    user_msg = ChatMessage(session_id=session.id, role="user", content=message)
    db.add(user_msg)
    await db.flush()

    # RAG コンテキストを構築
    rag_context = await asyncio.get_event_loop().run_in_executor(
        None, _build_daily_rag_context, date_str
    )
    session.rag_context = rag_context

    # AI 応答を生成
    gen_result = await _generate_daily_response(
        date_str, [user_msg], message, rag_context
    )

    # AI メッセージを保存
    ai_msg = ChatMessage(
        session_id=session.id,
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

    # タイトルを自動生成
    session.title = await _generate_title(message)

    await db.commit()
    await db.refresh(session, attribute_names=["id"])

    # パネル全体を返す（セッション情報 + メッセージ付き）
    return await _render_daily_chat_panel(
        request, date_str, session, [user_msg, ai_msg], db
    )


# ── セッション読み込み ─────────────────────────────────────────────
@router.get("/{date_str}/sessions/{session_id}", response_class=HTMLResponse)
async def get_session(
    request: Request,
    date_str: str,
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.id == session_id,
            ChatSession.date == date_str,
            ChatSession.article_id.is_(None),
        )
        .options(selectinload(ChatSession.messages))
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    return await _render_daily_chat_panel(
        request, date_str, session, session.messages, db
    )


# ── メッセージ送信 ─────────────────────────────────────────────────
@router.post("/{date_str}/sessions/{session_id}/messages", response_class=HTMLResponse)
async def send_message(
    request: Request,
    date_str: str,
    session_id: int,
    message: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(ChatSession)
        .where(
            ChatSession.id == session_id,
            ChatSession.date == date_str,
            ChatSession.article_id.is_(None),
        )
        .options(selectinload(ChatSession.messages))
    )
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    # ユーザーメッセージを保存
    user_msg = ChatMessage(session_id=session_id, role="user", content=message)
    db.add(user_msg)
    await db.flush()

    # RAG コンテキストをキャッシュ（初回のみ構築）
    if not session.rag_context:
        rag_context = await asyncio.get_event_loop().run_in_executor(
            None, _build_daily_rag_context, date_str
        )
        session.rag_context = rag_context
    else:
        rag_context = session.rag_context

    # AI 応答を生成
    gen_result = await _generate_daily_response(
        date_str, session.messages + [user_msg], message, rag_context
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
    new_title = None
    if len(session.messages) == 0:
        new_title = await _generate_title(message)
        session.title = new_title

    await db.commit()

    ctx: dict = {
        "request": request,
        "messages": [ai_msg],
    }
    if new_title:
        ctx["new_title"] = new_title
        ctx["title_element_id"] = f"chat-title-{session_id}"
    return templates.TemplateResponse("components/chat/messages.html", ctx)


# ── セッション削除 ─────────────────────────────────────────────────
@router.delete("/{date_str}/sessions/{session_id}", response_class=HTMLResponse)
async def delete_session(
    request: Request,
    date_str: str,
    session_id: int,
    db: AsyncSession = Depends(get_db),
):
    session = await db.get(ChatSession, session_id)
    if not session or session.date != date_str or session.article_id is not None:
        raise HTTPException(status_code=404, detail="セッションが見つかりません")

    await db.delete(session)
    await db.commit()

    # 残りのセッションがあれば最新を表示、なければ新規作成
    stmt = (
        select(ChatSession)
        .where(ChatSession.date == date_str, ChatSession.article_id.is_(None))
        .options(selectinload(ChatSession.messages))
        .order_by(ChatSession.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    remaining = result.scalar_one_or_none()

    if remaining:
        return await _render_daily_chat_panel(
            request, date_str, remaining, remaining.messages, db
        )

    # セッションがなくなった場合は空パネルを表示（初回メッセージ時に作成）
    return await _render_daily_chat_panel(request, date_str, None, [], db)


# ── 内部ヘルパー ───────────────────────────────────────────────────


async def _render_daily_chat_panel(
    request: Request,
    date_str: str,
    session: ChatSession | None,
    messages: list[ChatMessage],
    db: AsyncSession,
) -> HTMLResponse:
    """日毎チャットパネル HTML を生成する"""
    if session is None:
        return templates.TemplateResponse(
            "components/chat/daily_panel.html",
            {
                "request": request,
                "date_str": date_str,
                "session": None,
                "messages": [],
                "all_sessions": [],
                "current_index": 0,
                "total_sessions": 0,
            },
        )

    stmt = (
        select(ChatSession)
        .where(ChatSession.date == date_str, ChatSession.article_id.is_(None))
        .order_by(ChatSession.created_at)
    )
    result = await db.execute(stmt)
    all_sessions = result.scalars().all()
    current_index = next(
        (i for i, s in enumerate(all_sessions) if s.id == session.id), 0
    )

    return templates.TemplateResponse(
        "components/chat/daily_panel.html",
        {
            "request": request,
            "date_str": date_str,
            "session": session,
            "messages": messages,
            "all_sessions": all_sessions,
            "current_index": current_index,
            "total_sessions": len(all_sessions),
        },
    )


def _extract_grounding_info(response) -> tuple[bool, list[dict], str]:
    """レスポンスからグラウンディング情報を抽出する"""
    text = response.text or ""
    try:
        meta = response.candidates[0].grounding_metadata
        if not meta or not meta.grounding_chunks:
            return False, [], text
    except (AttributeError, IndexError):
        return False, [], text

    sources: list[dict] = []
    for chunk in meta.grounding_chunks:
        web = getattr(chunk, "web", None)
        if web:
            sources.append({"title": web.title or "", "uri": web.uri or ""})

    if not sources:
        return False, [], text
    supports = meta.grounding_supports or []
    if supports:
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
            seg_text = seg.text.strip()
            pos = text.find(seg_text)
            if pos == -1:
                continue
            end_pos = pos + len(seg_text)
            citation_marks = "".join(f"[{i + 1}]" for i in indices if i < len(sources))
            indexed.append((end_pos, citation_marks))

        seen_positions: set[int] = set()
        for end_pos, marks in sorted(indexed, key=lambda x: x[0], reverse=True):
            if end_pos in seen_positions:
                continue
            seen_positions.add(end_pos)
            text = text[:end_pos] + marks + text[end_pos:]

    return True, sources, text


async def _generate_daily_response(
    date_str: str,
    messages: list[ChatMessage],
    user_message: str,
    rag_context: str,
) -> dict:
    """日毎チャット用の Gemini 応答生成"""
    system_instruction = f"""あなたは {date_str} の AI 関連ニュース・論文全体についての質問に答える専門AIアシスタントです。
ユーザーの質問には、以下に示すその日の全記事コンテキストを根拠にして日本語で回答してください。
コンテキストに記載のない概念・背景知識・最新情報について質問された場合は、Google検索ツールを使って正確な情報を取得してから回答してください。
コンテキスト内の情報だけで回答できる場合は検索を使わないでください。
複数の記事を横断的に比較・整理する質問にも対応してください。

# 対象日
{date_str}

# その日の全記事コンテキスト
{rag_context}"""

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
        logger.error(f"日毎チャット応答生成失敗: {e}")
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
