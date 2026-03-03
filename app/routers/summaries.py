"""
サマリー履歴フィードページルーター
- /summaries        : 最新3日分 / 全件一覧ビュー
- /summaries/{date} : 特定日のダイジェスト詳細
"""
import markdown as md
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.digest import load_digest, list_digests
from app.schemas import DailySummaryMeta

router = APIRouter(prefix="/summaries")
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def summaries_list(request: Request):
    all_dates = list_digests()
    metas = _build_metas(all_dates)
    latest_3 = metas[:3]

    return templates.TemplateResponse(
        "summaries.html",
        {
            "request": request,
            "metas": metas,
            "latest_3": latest_3,
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
        raise HTTPException(status_code=404, detail=f"{date_str} のダイジェストが見つかりません。")

    html_content = md.markdown(
        content,
        extensions=["fenced_code", "tables", "toc", "nl2br"],
    )

    return templates.TemplateResponse(
        "summary_detail.html",
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
            line.strip() for line in lines[1:] if line.strip() and not line.startswith("#")
        )[:200]
        metas.append(DailySummaryMeta(
            date=date_str,
            title=title,
            preview=preview,
            file_path=f"summaries/{date_str}.md",
        ))
    return metas
