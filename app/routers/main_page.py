"""
メインページ（今日の一面）ルーター
ホームは最新の収集日のアーカイブページへリダイレクトする
"""

from datetime import datetime

import pytz
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.services.pipeline import list_available_dates

JST = pytz.timezone("Asia/Tokyo")

router = APIRouter()


@router.get("/")
@router.get("/today")
async def today(request: Request):
    available = list_available_dates()
    today_str = datetime.now(JST).date().isoformat()
    # 今日のデータがあればそこへ、なければ最新のデータへ
    if today_str in available:
        redirect_date = today_str
    elif available:
        redirect_date = available[0]
    else:
        redirect_date = today_str
    return RedirectResponse(url=f"/archive/{redirect_date}")


@router.get("/health")
async def health():
    return {"status": "ok"}
