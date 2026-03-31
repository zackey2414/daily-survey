"""
Jinja2Templates のシングルトン（フィルター登録済み）
全ルーターはここからインポートして使う
"""

import markdown as markdown_lib
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["markdown"] = lambda text: markdown_lib.markdown(
    text or "", extensions=["nl2br"], tab_length=2
)
