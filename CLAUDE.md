# プロジェクト概要
毎日日本時間9時に、前日（日本時間での前日0:00から23:59）に新たに投稿されたAI系の論文や、AI企業のWEBページ情報などをまとめる自動サーベイページを作る。
各記事・論文などの要約やチャット機能の実装などを施し、毎日の研究的キャッチアップを容易にすることを目指す。

# 技術スタック・コードスタイル
基本的にPythonベースで進める。ページもjinja2などを使用することで、できる限りPython以外を使用しない状態で実装を行う。

- Backend: Python 3.12 + FastAPI
- Frontend: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- DB: SQLite (aiosqlite + SQLAlchemy async) — チャット履歴・ユーザータグのみ
- LLM: Google Gemini API (要約: gemini-2.5-pro、チャット: gemini-2.5-flash)
- Container: Docker + uv

# 重要な実装ルール
- 要約カテゴリは3種: `"paper"` / `"industry"` / `"article"` (summarizer.py の Literal 型)
- 企業動向 (industry / industry_news) は `"industry"` カテゴリで要約し、定量指標を抽出する
- タグ一覧ページ (/tags/) は AI 生成タグとユーザー追加タグを別セクションで表示する
- `article_id` が CSS セレクタ安全でない文字 (`:`, `/`, `.`) を含む場合は `safe_id` フィルタを使う

# アクセス禁止ディレクトリ
- .git/

# 現在の既知バグ・TODO
（現在未解決の項目なし）

