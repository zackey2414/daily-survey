"""
メインページ（今日の一面）ルーター
ホームは今日の日付のアーカイブページへリダイレクトする。
日本時間で日付が変わったら今日のページを表示し、データがなければ「まだ記事はありません」を表示。
"""

from datetime import datetime

import pytz
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

JST = pytz.timezone("Asia/Tokyo")

router = APIRouter()


@router.get("/")
@router.get("/today")
async def today(request: Request):
    today_str = datetime.now(JST).date().isoformat()
    return RedirectResponse(url=f"/archive/{today_str}")


@router.get("/health")
async def health():
    return {"status": "ok"}
