"""
Jinja2Templates のシングルトン（フィルター登録済み）
全ルーターはここからインポートして使う
"""

import markdown as markdown_lib
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.markdown_utils import normalize_markdown

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["markdown"] = lambda text: markdown_lib.markdown(
    normalize_markdown(text or ""), extensions=["nl2br"], tab_length=2
)

# 全テンプレートで参照できるグローバル（フッターのモデル名表示等）。
# 機密値（API キー等）は渡さず、現在使用中の Gemini モデル名のみ公開する。
templates.env.globals["gemini_summary_model"] = settings.gemini_summary_model
templates.env.globals["gemini_chat_model"] = settings.gemini_chat_model
