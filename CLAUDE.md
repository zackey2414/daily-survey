# プロジェクト概要
毎日日本時間9時に、前日（日本時間での前日0:00から23:59）に新たに投稿されたAI系の論文や、AI企業のWEBページ情報などをまとめる自動サーベイページを作る。
各記事・論文などの要約やチャット機能の実装などを施し、毎日の研究的キャッチアップを容易にすることを目指す。

# 技術スタック・コードスタイル
基本的にPythonベースで進める。ページもjinja2などを使用することで、できる限りPython以外を使用しない状態で実装を行う。

- Backend: Python 3.12 + FastAPI
- Frontend: Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN)
- DB: SQLite (aiosqlite + SQLAlchemy async) — チャット履歴・ユーザータグのみ
- LLM: Google Gemini API (要約: gemini-3-flash-preview、チャット: gemini-3.1-flash-lite)
- Container: Docker + uv

# 重要な実装ルール
- 要約カテゴリは3種: `"paper"` / `"industry"` / `"article"` (summarizer.py の Literal 型)
- 企業動向 (industry / industry_news) は `"industry"` カテゴリで要約し、定量指標を抽出する
- タグ一覧ページ (/tags/) は AI 生成タグとユーザー追加タグを別セクションで表示する
- `article_id` が CSS セレクタ安全でない文字 (`:`, `/`, `.`) を含む場合は `safe_id` フィルタを使う

# アクセス禁止ディレクトリ
- .git/

# 開発時のルール
- gitを用いて開発する。
  - 開発はGit-Flow に従う。基本的には以下のように進める。
    - mainブランチ
      - 開発したアプリの保守用ブランチ
    - developブランチ
      - 開発における集約元のブランチ
    - featureブランチ
      - 機能開発のためのブランチ
      - 名前は"feature/xxx"というフォーマットにする。
  - commit メッセージは原則として日本語で書く。フォーマットは、「1行目、改行、2行目以降箇条書き」とする。
    - 1行目
      - そのcommit 内容全体をまとめたコメントを入れる。
      - 関連のissueがあれば、「#{issue_id} 」を頭に入れて始める。
    - 改行
    - 2行目以降
      - 変更内容を"- "から始める箇条書きで書く。
      - 変更内容ごとに改行を挟む。
- 変更内容がある場合は対応するREADMEやdocs/ のファイルにその内容が書かれているか確認する。
  - 書かれていない、あるいは書かれているが変更内容と齟齬があったり、変更内容を正しく捉えられていない場合は変更する。
- 既存のファイルに変更を加える場合は、必ずdevelopブランチからfeatureブランチを作成して移行してから始める。
  - 移動方法はswitch が推奨されているので、`git switch` を行なって移動する。
  - 新規ブランチ作成の場合は`git switch -c`を使用する。
- 基本的に環境はuv を使う。そのため、pip install などは使用しないで、uv add --group {グループ名}などで対応せよ。