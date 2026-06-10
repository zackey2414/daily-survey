"""
サマリー履歴フィードページルーター
- /summaries        : 全一面まとめを降順・ページネーション表示（10件/ページ）
- /summaries/{date} : 特定日のダイジェスト詳細
"""

import markdown as md
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.jinja import templates
from app.markdown_utils import normalize_markdown
from app.services.digest import load_digest, list_digests, inject_citations
from app.schemas import DailySummaryMeta

router = APIRouter(prefix="/summaries")

PER_PAGE = 10


@router.get("/", response_class=HTMLResponse)
async def summaries_list(request: Request, page: int = Query(default=1, ge=1)):
    all_dates = list_digests()  # 降順（最新が先頭）
    metas = _build_metas(all_dates)

    total = len(metas)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)

    start = (page - 1) * PER_PAGE
    page_metas = metas[start : start + PER_PAGE]

    return templates.TemplateResponse(
        "pages/summaries.html",
        {
            "request": request,
            "metas": page_metas,
            "page": page,
            "total_pages": total_pages,
            "total": total,
        },
    )


@router.get("/{date_str}", response_class=HTMLResponse)
async def summary_detail(request: Request, date_str: str):
    try:
        from datetime import date

        date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format.")

    content = load_digest(date_str)
    if content is None:
        raise HTTPException(
            status_code=404, detail=f"{date_str} のダイジェストが見つかりません。"
        )

    processed = inject_citations(content, date_str, is_archive=False)
    html_content = md.markdown(
        normalize_markdown(processed),
        extensions=["fenced_code", "tables", "toc", "nl2br"],
        tab_length=2,
    )

    return templates.TemplateResponse(
        "pages/summary_detail.html",
        {
            "request": request,
            "date_str": date_str,
            "content_html": html_content,
            "raw_content": content,
        },
    )


def _build_metas(dates: list[str]) -> list[DailySummaryMeta]:
    metas = []
    for date_str in dates:
        content = load_digest(date_str)
        if not content:
            continue
        lines = content.strip().split("\n")
        title = lines[0].lstrip("# ").strip() if lines else date_str
        preview = " ".join(
            line.strip()
            for line in lines[1:]
            if line.strip() and not line.startswith("#")
        )[:200]
        metas.append(
            DailySummaryMeta(
                date=date_str,
                title=title,
                preview=preview,
                file_path=f"summaries/{date_str}.md",
            )
        )
    return metas
