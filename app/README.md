# app/ ディレクトリ構造

FastAPI アプリケーションのソースコード。

## ディレクトリ構成

```
app/
├── main.py              # FastAPI エントリポイント (lifespan, ルーター登録, 管理API)
├── config.py            # 全設定 (環境変数 → Settings クラス)
├── schemas.py           # Pydantic モデル (ArticleItem, DailyCollection)
├── jinja.py             # Jinja2Templates シングルトン + カスタムフィルター
├── scheduler.py         # APScheduler (毎日 JST 09:00 にパイプライン実行)
├── db/
│   ├── database.py      # SQLAlchemy async エンジン, init_db(), migrate_db()
│   └── models.py        # ORM モデル (Article, ChatSession, ChatMessage, UserTag)
├── routers/
│   ├── main_page.py     # GET / — トップページ (当日の記事一覧 + ダイジェスト)
│   ├── archive.py       # GET /archive/{date} — 過去日付の記事一覧
│   ├── summaries.py     # GET /summaries, /summaries/{date} — サマリー閲覧
│   ├── tags.py          # GET /tags/, /tags/{name} — タグ一覧・タグ別記事
│   ├── user_tags.py     # POST/DELETE /user-tags/ — ユーザータグ CRUD (HTMX)
│   └── chat.py          # チャット機能 (セッション管理, メッセージ送受信, RAG + Google Search)
├── services/
│   ├── pipeline.py      # 日次パイプライン統括 (収集 → 要約 → ダイジェスト → 通知)
│   ├── summarizer.py    # Gemini による個別記事要約 (paper / industry / article)
│   ├── digest.py        # 一面まとめ (ダイジェスト) 生成・Markdown 保存
│   ├── rag.py           # RAG コンテキスト構築 (URL フェッチ, チャンク分割, Jaccard スコアリング)
│   ├── notifier.py      # SMTP メール通知
│   └── collector/       # データ収集モジュール群
│       ├── arxiv.py         # arXiv API (cs.CV / cs.LG / cs.AI / cs.CL)
│       ├── openreview.py    # OpenReview API (主要10学会)
│       ├── industry.py      # AI 企業公式ブログ RSS
│       ├── industry_news.py # 海外ニュースメディア RSS + キーワードフィルタ
│       ├── community.py     # Qiita API / Zenn RSS / Reddit JSON API
│       └── python_news.py   # PyPI RSS / GitHub Trending スクレイピング
└── templates/
    ├── base.html        # 共通レイアウト (Tailwind CDN, HTMX, Alpine.js)
    ├── pages/           # フルページテンプレート
    │   ├── index.html
    │   ├── summaries.html
    │   ├── summary_detail.html
    │   ├── tags.html
    │   ├── tags_list.html
    │   ├── chat_search.html
    │   └── error.html
    └── components/      # HTMX swap 用部分テンプレート
        ├── article/     # 記事カード・要約表示
        ├── chat/        # チャットパネル・メッセージ
        │   ├── panel.html
        │   ├── messages.html
        │   └── message_item.html
        └── tags/        # タグ管理 UI
```

## 主要モジュール解説

### `config.py`

環境変数を `Settings` クラスに集約。主な設定:

| 環境変数 | デフォルト | 説明 |
|---------|-----------|------|
| `GEMINI_API_KEY` | (必須) | Gemini API キー |
| `GEMINI_SUMMARY_MODEL` | `gemini-2.5-pro` | ダイジェスト生成用モデル |
| `GEMINI_CHAT_MODEL` | `gemini-2.5-flash` | チャット・個別要約用モデル |
| `GEMINI_SEARCH_THRESHOLD` | `0.3` | チャット時の Google Search グラウンディング閾値 (0.0=常に検索, 1.0=検索しない) |
| `SCHEDULE_HOUR` / `SCHEDULE_MINUTE` | `9` / `0` | 日次パイプライン実行時刻 (JST) |

### `db/models.py`

| モデル | テーブル | 用途 |
|--------|---------|------|
| `Article` | `articles` | 記事マスタ (JSON から on-demand 登録) |
| `ChatSession` | `chat_sessions` | チャットセッション (記事ごと, RAG コンテキストをキャッシュ) |
| `ChatMessage` | `chat_messages` | 個別メッセージ (検索使用有無・ソース情報を含む) |
| `UserTag` | `user_tags` | ユーザー手動タグ |

`ChatMessage` の検索関連カラム:

| カラム | 型 | 説明 |
|--------|---|------|
| `used_search` | `BOOLEAN` | Google Search グラウンディングが使われたか |
| `search_sources` | `TEXT` | 検索ソースの JSON 文字列 (`[{"title": "...", "uri": "..."}]`) |

`search_sources_parsed` プロパティで JSON をパースしてテンプレートから直接利用可能。

### `routers/chat.py`

チャット機能の中核。主な処理フロー:

1. **セッション管理**: 記事ごとにセッションを作成・切り替え・削除
2. **RAG コンテキスト構築**: 初回メッセージ時に記事本文を取得しセッションにキャッシュ
3. **応答生成** (`_generate_response`):
   - Gemini Flash にシステム指示 + RAG コンテキスト + 会話履歴を渡す
   - `google_search_retrieval` ツールを付与し、Gemini が必要と判断した場合に Google 検索を実行
   - レスポンスの `grounding_metadata` から検索ソースを抽出
4. **DB 保存**: メッセージ本文に加え `used_search` / `search_sources` を永続化

### `services/rag.py`

RAG コンテキスト構築の流れ:

1. JSON に保存済みの記事メタ情報 (abstract, summary, novelty, key_points) を収集
2. 記事 URL から httpx + BeautifulSoup で本文テキストをフェッチ (キャッシュ付き)
3. テキストをチャンク分割し、ユーザー質問との Jaccard 類似度でスコアリング
4. 上位チャンクを選択してコンテキスト文字列を構築

### `services/pipeline.py`

日次パイプラインの実行順序:

1. 全カテゴリの記事を並列収集 (`collector/*`)
2. 収集結果を JSON 保存 + 重複除去
3. 未要約アイテムを Gemini で要約 (`summarizer.py`)
4. 全カテゴリ横断の一面まとめを生成 (`digest.py`)
5. メール通知 (`notifier.py`)

### `db/database.py` マイグレーション

`migrate_db()` で `ALTER TABLE` による incremental マイグレーションを実行。
既存カラムの場合は `try/except` で無視する方式。起動時に毎回実行される。

現在のマイグレーション:
- `chat_sessions.rag_context` (TEXT) — RAG コンテキストキャッシュ
- `chat_messages.used_search` (BOOLEAN) — Google Search 使用フラグ
- `chat_messages.search_sources` (TEXT) — 検索ソース JSON
- `user_tags` テーブル作成
