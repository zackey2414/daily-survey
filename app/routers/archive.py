"""
アーカイブページルーター（過去日付の記事表示）
"""
import markdown as md
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.pipeline import load_daily_data, list_available_dates
from app.services.digest import load_digest

router = APIRouter(prefix="/archive")
templates = Jinja2Templates(directory="app/templates")


@router.get("/{date_str}", response_class=HTMLResponse)
async def archive_day(request: Request, date_str: str):
    # 日付フォーマット検証
    try:
        from datetime import date, timedelta
        collection_date = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

    target_date_str = (collection_date - timedelta(days=1)).isoformat()
    data = load_daily_data(date_str)
    digest_raw = load_digest(date_str)
    digest_html = (
        md.markdown(digest_raw, extensions=["fenced_code", "tables", "nl2br"])
        if digest_raw else None
    )
    available_dates = list_available_dates()

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "date_str": date_str,
            "target_date_str": target_date_str,
            "is_today": False,
            "digest_html": digest_html,
            "cv_papers": data.get("cv", []),
            "lg_papers": data.get("lg", []),
            "ai_papers": data.get("ai", []),
            "cl_papers": data.get("cl", []),
            "industry_items": data.get("industry", []),
            "community_items": data.get("community", []),
            "python_items": data.get("python", []),
            "available_dates": available_dates,
        },
    )
