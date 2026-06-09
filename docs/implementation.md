# 実装詳細ドキュメント: AI Daily Survey

**バージョン**: 現行実装
**最終更新**: 2026-03-22

---

## 目次

1. [概要](#1-概要)
2. [ディレクトリ構成](#2-ディレクトリ構成)
3. [技術スタック](#3-技術スタック)
4. [日次パイプライン（ワークフロー）](#4-日次パイプラインワークフロー)
5. [データ収集](#5-データ収集)
6. [要約処理（LLM）](#6-要約処理llm)
7. [ダイジェスト生成](#7-ダイジェスト生成)
8. [データモデル](#8-データモデル)
9. [Web ルーティング](#9-web-ルーティング)
10. [フロントエンド UI](#10-フロントエンド-ui)
11. [設定・環境変数](#11-設定環境変数)
12. [管理者エンドポイント](#12-管理者エンドポイント)

---

## 1. 概要

毎日 JST 正午 (12:00) に自動実行し、前日に公開された AI 関連の論文・記事・サービス情報を収集・要約して 1 ページで閲覧できる個人向け Web アプリ。（実行時刻は arXiv の索引反映待ちのため正午。`SCHEDULE_HOUR` で変更可）

```
収集 → 重複除去 → 要約（Gemini） → JSON保存 → DB登録 → ダイジェスト生成 → メール通知
```

リモートサーバ上の Docker コンテナで動作。SSH トンネル経由で `http://localhost:8000` にアクセス。

---

## 2. ディレクトリ構成

```
everyday-survey/
├── docker-compose.yml
├── Dockerfile                     # python:3.12-slim ベース
├── .env                           # 環境変数（API キー等）
├── .env.example
├── pyproject.toml                 # uv プロジェクト設定
├── uv.lock
│
├── app/
│   ├── main.py                    # FastAPI エントリポイント・lifespan・管理エンドポイント
│   ├── config.py                  # 全設定（Settings クラス、.env 読み込み）
│   ├── schemas.py                 # Pydantic モデル（ArticleItem, DailyCollection）
│   ├── jinja.py                   # Jinja2 テンプレートエンジン設定（カスタムフィルタ含む）
│   ├── scheduler.py               # APScheduler（JST 12:00 自動実行）
│   │
│   ├── routers/
│   │   ├── main_page.py           # GET /
│   │   ├── archive.py             # GET /archive/{date_str}
│   │   ├── summaries.py           # GET /summaries, /summaries/{date_str}
│   │   ├── chat.py                # チャット API（HTMX 対応）
│   │   ├── tags.py                # GET /tags/, /tags/{tag_name}
│   │   └── user_tags.py           # POST/DELETE /user-tags/{article_id}
│   │
│   ├── services/
│   │   ├── pipeline.py            # 日次パイプライン統括（収集→要約→保存→通知）
│   │   ├── summarizer.py          # Gemini 要約処理
│   │   ├── digest.py              # 一面まとめ生成・保存 + inject_citations
│   │   ├── notifier.py            # SMTP メール通知
│   │   ├── rag.py                 # チャット用 URL フェッチ・RAG コンテキスト構築
│   │   └── collector/
│   │       ├── arxiv.py           # arXiv API（cs.CV / cs.LG / cs.AI / cs.CL）
│   │       ├── openreview.py      # OpenReview API v2（CVPR/NeurIPS/ICLR 等10学会）
│   │       ├── industry.py        # 企業公式ブログ RSS（自社発表）
│   │       ├── industry_news.py   # 海外大手ニュースサイト RSS（その他報道）
│   │       ├── community.py       # Qiita API / Zenn RSS / Reddit JSON API
│   │       ├── python_news.py     # (旧) Python 限定 GitHub Trending（後方互換用）
│   │       └── github_trending.py # GitHub Trending 全言語 AI/LLM フィルタ付きスクレイパー
│   │
│   ├── db/
│   │   ├── database.py            # SQLAlchemy async セッション・init_db・migrate_db
│   │   └── models.py              # ORM モデル（Article, ChatSession, ChatMessage, UserTag）
│   │
│   └── templates/
│       ├── base.html              # 共通レイアウト（ナビ・スティッキーバー JS・引用スクロール JS）
│       ├── pages/
│       │   ├── index.html         # トップページ（今日の一面）
│       │   ├── summaries.html     # サマリー履歴一覧
│       │   ├── summary_detail.html # 個別サマリー詳細
│       │   ├── tags_list.html     # タグ一覧
│       │   ├── tags.html          # タグ別記事一覧
│       │   ├── chat_search.html   # チャット検索
│       │   └── error.html         # 404 / 500 エラーページ
│       └── components/
│           ├── article/
│           │   ├── section.html   # セクション（折りたたみトグル）
│           │   └── card.html      # 記事カード（要約・チャット・タグ UI）
│           ├── chat/
│           │   ├── panel.html     # チャットパネル（インライン展開）
│           │   ├── messages.html  # メッセージ一覧
│           │   └── message_item.html
│           └── tags/
│               └── user_tags.html # ユーザータグ一覧 HTML（HTMX スワップ対象）
│
├── data/                          # 日次収集 JSON データ（永続化）
│   └── YYYY-MM-DD/
│       ├── papers_cv.json
│       ├── papers_openreview.json
│       ├── papers_lg.json
│       ├── papers_ai.json
│       ├── papers_cl.json
│       ├── papers_industry.json
│       ├── papers_industry_news.json
│       ├── papers_community.json
│       └── papers_python.json
│
├── summaries/                     # 日次一面まとめ（Markdown）
│   └── YYYY-MM-DD.md
│
├── db/
│   └── survey.db                  # SQLite データベース
│
├── logs/
│   └── app.log
│
└── docs/
    ├── requirements.md            # 要件定義書
    ├── implementation.md          # 本ドキュメント
    ├── article_format.md          # 記事フォーマット定義書
    └── env.md                     # 環境変数の設定ガイド
```

---

## 3. 技術スタック

| レイヤー | 技術 | 備考 |
|----------|------|------|
| コンテナ | Docker / Docker Compose | |
| Python 環境 | uv | `pyproject.toml` でパッケージ管理 |
| バックエンド | Python 3.12 + FastAPI | |
| テンプレート | Jinja2 | Python ベースの HTML 生成 |
| フロントエンド | HTMX + Alpine.js | CDN 経由（ビルドなし） |
| CSS | Tailwind CSS | CDN 経由（Play CDN） |
| DB | SQLite | aiosqlite + SQLAlchemy async |
| データ保存 | JSON ファイル | `data/YYYY-MM-DD/` |
| LLM | Google Gemini API | 個別記事要約・チャット: `gemini-3.1-flash-lite`（`GEMINI_CHAT_MODEL`）、一面まとめ: `gemini-3-flash-preview`（`GEMINI_SUMMARY_MODEL`）。チャットは `google-genai` SDK で Google Search グラウンディング付き |
| スケジューラ | APScheduler (AsyncIOScheduler) | `Asia/Tokyo` JST 12:00 実行（arXiv 索引反映待ち） |
| 通知 | SMTP | 収集完了時にメール送信 |

---

## 4. 日次パイプライン（ワークフロー）

`app/services/pipeline.py:run_daily_pipeline()` が全工程を統括する。

```
JST 12:00 (APScheduler)
    │
    ▼
① 収集
    [直列] collect_all_arxiv_serial(target_date)
    │   └── 1クライアントで cs.CV → cs.LG → cs.AI → cs.CL を直列取得（カテゴリ間5秒待機）
    [直列] 各ソースを順次収集（ソース間3秒待機）
    ├── collect_openreview(target_date)      → OpenReview（10学会）
    ├── collect_industry(target_date)        → 企業公式 RSS（自社発表）
    ├── collect_industry_news(target_date)   → 海外ニュース RSS（その他報道）
    ├── collect_community(target_date)       → Qiita / Zenn / Reddit
    ├── collect_github_trending(target_date)  → GitHub Trending（全言語, AI/LLMキーワードフィルタ, 3期間スクレイピング）
    └── collect_ai_dev(target_date)          → LLM・AIエージェント動向（公式アップデート + 性能ニュース）
    │
    ▼
② 重複除去（論文系のみ: cv / openreview / lg / ai / cl）
    └── 過去の全 papers_*.json を走査して既出 ID をスキップ
    │
    ▼
③ 並列要約 (asyncio.gather, Gemini)
    ├── 論文カテゴリ: summarize_items(items, "paper")
    └── 記事カテゴリ: summarize_items(items, "article")
    │
    ▼
④ JSON 保存
    └── data/YYYY-MM-DD/papers_*.json に書き出し
    │
    ▼
⑤ DB 登録（チャット機能のために Article レコードを upsert）
    │
    ▼
⑥ ダイジェスト生成（Gemini）
    └── summaries/YYYY-MM-DD.md に保存
    │
    ▼
⑦ メール通知（SMTP）
    └── 収集件数・処理時間・エラー・ダイジェスト冒頭を送信
```

**収集日と対象日の関係**:
- `collection_date` = 実行日（JST の今日、ディレクトリ名）
- `target_date` = `collection_date - 1日`（前日、実際に収集する日付範囲）

---

## 5. データ収集

### 5.1 arXiv（cs.CV / cs.LG / cs.AI / cs.CL）

- API: `http://export.arxiv.org/api/query`
- 日付フィルタ: **JST 前日の投稿のみ**
  UTC に変換して `submittedDate:[from TO to]` でクエリ、さらに `published_date` が JST 前日かを再チェック
- cs.CV: 優先度付きで最大40件取得（優先キーワードに一致する論文を上位に並び替え）
- cs.LG / cs.AI / cs.CL: 各最大20件
- 重複除去: 過去データと照合（ID: `arxiv:{id}v{ver}` 形式）

### 5.2 OpenReview

- API: `https://api2.openreview.net/notes`
- 対象学会（10学会）: CVPR, NeurIPS, ICLR, ICCV, ICML, AAAI, ACL, ECCV, EMNLP, IJCAI
- 収集基準: `tmdate`（最終更新日）が前日 JST の論文
- ID: `openreview:{forum_id}`

### 5.3 企業動向（自社発表）

- ソース: OpenAI / Google / Anthropic / Meta / Amazon / Alibaba の公式ブログ RSS
- 各社最大5件、合計最大30件
- `published_date` が前日 JST のもののみ

### 5.4 企業動向（その他報道）

- ソース: BBC / CNN / Reuters / TechCrunch 等の海外大手ニュースサイト RSS
- AI 関連キーワードでフィルタリング
- 上限15件

### 5.5 コミュニティ（Qiita / Zenn / Reddit）

- **Qiita**: Qiita API v2 (`/api/v2/items`) → `tag:機械学習` / `tag:LLM` 等
- **Zenn**: RSS フィード → `https://zenn.dev/topics/機械学習/feed`
- **Reddit**: JSON API → `r/MachineLearning` / `r/artificial` / `r/LocalLLaMA`

### 5.6 GitHub Trending

- **GitHub Trending**: HTML スクレイピング（BeautifulSoup）+ GitHub REST API → 全言語の AI/LLM 関連トレンドリポジトリ
  - `https://github.com/trending` を `since=daily`, `weekly`, `monthly` の3期間で**直列スクレイピング**（ページ間10秒待機）
  - 各ページ取得は最大3回リトライ（429/5xx 時は指数バックオフ + `Retry-After` 対応）
  - 各期間最大20件取得し、キーワードフィルタ（AI, LLM, agent 等）で絞り込み
  - 4つの独立したランキングビュー: Daily ★ / Weekly ★ / Monthly ★ / Total ★
  - **GitHub REST API** で全リポジトリの正確な累計スター数を取得（`GITHUB_TOKEN` 設定でレートリミット緩和可能）
  - **スマート再収集**: 過去に調査済みのリポジトリは `github_trending_index.json` で追跡
    - description 変更なし & 30日以内 → 前回のカードを再利用（`reused_from` タグ付与）
    - description 変更あり or 30日超経過 → 新たに要約を生成
  - キーワードは `data/github_trending_keywords.json` でカスタマイズ可能（UI からも変更可能）
  - 詳細は [docs/github_trending.md](github_trending.md) を参照

### 5.7 LLM・AIエージェント動向（`ai_dev`）

- **公式アップデート（Pass A）**: `settings.ai_dev_rss_feeds` の RSS/Atom を並列取得
  - Claude Code / OpenAI Codex（GitHub releases Atom）、Cursor / GitHub Copilot（changelog RSS）、Mistral / Hugging Face / Google DeepMind（blog RSS）
  - 前日分のみ採用。バージョンタイトルが alpha/beta/rc/dev/nightly のプレリリースは除外。1ソース最大 `ai_dev_max_per_source` 件
- **性能・ベンチマークニュース（Pass B）**: `settings.ai_dev_news_feeds`（Simon Willison / VentureBeat AI / Import AI）を取得し、`ai_dev_filter_keywords`（LLM/agent/coding-AI 関連語）でフィルタ。最大 `ai_dev_news_max_results` 件
- 2パスを `id` で重複除去してマージ。要約は `"industry"` リテラル（定量指標を抽出）
- 収集元は `app/config.py` で定義（環境変数ではない）。トップ/アーカイブの「LLM・AIエージェント動向」セクション（violet）に表示

---

## 6. 要約処理（LLM）

### 6.0 モデル割り当て

| 処理 | モジュール | モデル | 設定変数 |
|------|-----------|--------|----------|
| 個別記事・論文の要約 | `summarizer.py` | `gemini-3.1-flash-lite` | `GEMINI_CHAT_MODEL` |
| 一面まとめ生成 | `digest.py` | `gemini-3-flash-preview` | `GEMINI_SUMMARY_MODEL` |
| チャット応答 | `chat.py` | `gemini-3.1-flash-lite` + Google Search | `GEMINI_CHAT_MODEL` |

### 6.1 個別記事要約

`app/services/summarizer.py:summarize_items(items, category)`

- モデル: `gemini-3.1-flash-lite`（`settings.gemini_chat_model` — `.env` の `GEMINI_CHAT_MODEL`）
- 処理: 未要約（`summarized=False`）のアイテムのみ対象

### 論文の出力フィールド（`category="paper"`）

| フィールド | 内容 |
|-----------|------|
| `title_ja` | 日本語タイトル |
| `summary_ja` | 日本語概要 |
| `novelty_ja` | 新規性・貢献（番号付き箇条書き） |
| `meta_learning_ja` | **メタ的な学び**（問題定式化・アプローチ・評価手法の観点） |
| `hashtags` | 内容タグ（例: `["深層学習", "物体検出"]`） |

### 企業動向記事の出力フィールド（`category="industry"`）

| フィールド | 内容 |
|-----------|------|
| `title_ja` | 日本語タイトル |
| `summary_ja` | 日本語概要 |
| `key_points_ja` | ポイント（3箇条） |
| `quantitative_metrics_ja` | **定量指標**（ベンチマーク名・スコア・従来手法比など。ない場合は空文字） |
| `hashtags` | 内容タグ |

### 一般記事の出力フィールド（`category="article"`）

| フィールド | 内容 |
|-----------|------|
| `title_ja` | 日本語タイトル |
| `summary_ja` | 日本語概要 |
| `key_points_ja` | ポイント（3箇条） |
| `hashtags` | 内容タグ |

→ 詳細フォーマットは `docs/article_format.md` を参照。

---

## 7. ダイジェスト生成

`app/services/digest.py:generate_digest()`

- モデル: `gemini-3-flash-preview`（`settings.gemini_summary_model` — `.env` の `GEMINI_SUMMARY_MODEL`）
- 入力: 全カテゴリの要約データ（要約テキスト + `[ref:safe_id]` 形式の引用タグ付き）
- 出力: Markdown 形式（`summaries/YYYY-MM-DD.md`）

### 引用リンク変換（`inject_citations`）

ダイジェスト本文中の `[ref:safe_id]` を実際のリンクに変換する。

- `is_archive=True`（アーカイブページ）: `#article-{safe_id}` へのページ内リンク
- `is_archive=False`（サマリーページ）: `/archive/{date_str}#article-{safe_id}` へのリンク

`safe_id` の生成: `item.id` の `:` / `/` / `.` を `-` に置換

---

## 8. データモデル

### 8.1 JSON スキーマ（`ArticleItem`）

```python
class ArticleItem(BaseModel):
    id: str                          # "arxiv:2603.12345v1", "openreview:abc123"
    title_en: str                    # 英語タイトル（原文）
    title_ja: str                    # 日本語タイトル（LLM生成）
    authors: list[str]
    abstract_en: str                 # 英語アブストラクト（論文のみ）
    summary_ja: str                  # 日本語要約（LLM生成）
    novelty_ja: str                  # 新規性・貢献（論文のみ）
    meta_learning_ja: str            # メタ的な学び（論文のみ）
    key_points_ja: list[str]         # ポイント箇条書き（記事・企業動向のみ）
    quantitative_metrics_ja: str     # 定量指標（企業動向のみ、ない場合は空文字）
    published_date: str              # "YYYY-MM-DD"
    url: str
    pdf_url: str                     # 論文のみ
    source_type: str                 # "arxiv" / "openreview" / "rss" / "qiita" / ...
    source_name: str                 # "OpenAI", "r/MachineLearning" 等
    tags: list[str]                  # arXiv カテゴリ等
    hashtags: list[str]              # LLM生成の内容タグ
    summarized: bool                 # 要約済みフラグ
```

**ファイル一覧（1日分）** → `data/YYYY-MM-DD/papers_{category}.json`
`category`: `cv`, `openreview`, `lg`, `ai`, `cl`, `industry`, `industry_news`, `community`, `python`

### 8.2 SQLite スキーマ

チャット機能とユーザータグの永続化に使用。
`db/survey.db`（SQLAlchemy async + aiosqlite）

```sql
-- 記事テーブル（チャットとユーザータグの紐付け用・on-demand 登録）
CREATE TABLE articles (
    id          TEXT PRIMARY KEY,   -- "arxiv:2603.12345v1"
    date        TEXT NOT NULL,      -- "YYYY-MM-DD"（収集日）
    category    TEXT NOT NULL,
    title_ja    TEXT NOT NULL,
    title_en    TEXT NOT NULL,
    url         TEXT NOT NULL,
    summary_ja  TEXT NOT NULL,
    created_at  DATETIME DEFAULT (CURRENT_TIMESTAMP)
);

-- チャットセッション（1記事に複数作成可）
CREATE TABLE chat_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id),
    title       TEXT NOT NULL DEFAULT '新しいチャット',  -- LLM 自動生成
    rag_context TEXT,           -- キャッシュされた RAG コンテキスト
    created_at  DATETIME DEFAULT (CURRENT_TIMESTAMP),
    updated_at  DATETIME DEFAULT (CURRENT_TIMESTAMP)
);

-- チャットメッセージ
CREATE TABLE chat_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES chat_sessions(id),
    role            TEXT NOT NULL,  -- "user" | "assistant"
    content         TEXT NOT NULL,
    used_search     BOOLEAN DEFAULT 0,   -- Google Search グラウンディング使用フラグ
    search_sources  TEXT,                 -- 検索ソース JSON ([{"title": "...", "uri": "..."}])
    created_at      DATETIME DEFAULT (CURRENT_TIMESTAMP)
);

-- ユーザータグ（手動付与、article_id + tag でユニーク）
CREATE TABLE user_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id),
    tag         TEXT NOT NULL,
    created_at  DATETIME DEFAULT (CURRENT_TIMESTAMP),
    UNIQUE(article_id, tag)
);
```

**Article の on-demand 登録**: パイプライン実行時に全記事を登録するほか、チャットやタグ追加で DB に未登録の記事があった場合は JSON ファイルを走査して自動登録する。

---

## 9. Web ルーティング

| メソッド | パス | 説明 |
|----------|------|------|
| GET | `/` | トップページ（最新日のデータ） |
| GET | `/archive/{date_str}` | 過去日付アーカイブ |
| GET | `/summaries` | サマリー履歴一覧（最新3日分 or 全件） |
| GET | `/summaries/{date_str}` | 個別サマリー詳細 |
| GET | `/tags/` | タグ一覧（AI タグ + ユーザータグ混在） |
| GET | `/tags/{tag_name}` | タグ別記事一覧 |
| GET | `/chats` | チャット検索・一覧 |
| POST | `/chat/{article_id}` | チャット新規作成（HTMX） |
| GET/POST | `/chat/{session_id}/...` | チャット操作（HTMX） |
| POST | `/user-tags/{article_id}` | ユーザータグ追加（HTMX、Form: `tag`） |
| DELETE | `/user-tags/{article_id}/{tag}` | ユーザータグ削除（HTMX） |
| POST | `/admin/run-pipeline` | パイプライン手動実行 |
| POST | `/admin/reprocess-summaries` | 未要約アイテムの再要約 |

---

## 10. フロントエンド UI

### 10.1 ページ構成

トップページ（`/` と `/archive/{date_str}`）の表示セクション（上から順）:

1. **本日の一面まとめ** — Markdown レンダリング（引用リンク付き）
2. **CV 関連論文**（親セクション）
   - OpenReview（サブセクション）
   - arXiv cs.CV（サブセクション）
3. **AI 全般論文**（親セクション）
   - cs.LG / cs.AI / cs.CL（各サブセクション）
4. **AI 企業動向**（親セクション）
   - 自社発表 / その他報道（各サブセクション）
5. **SNS・コミュニティ**（単体セクション: Qiita / Zenn / Reddit）
6. **GitHub Trending**（単体セクション: ソートUI付き — Daily/Weekly/Monthly/Total ★ 切替）

### 10.2 記事カード（`components/article/card.html`）

各記事カードの構成:
- タイトル（日本語 + 英語）、ソース・日付バッジ、元リンク
- **AI ハッシュタグ** (`indigo` スタイル) + **ユーザータグ** (`emerald` スタイル)
- 要約パネル（Alpine.js `x-show` で折りたたみ）:
  - 日本語概要 / 新規性・貢献（論文）/ ポイント（記事・企業動向）
  - **メタ的な学び**（論文のみ、緑ボックス）
  - **定量指標**（企業動向のみ、amber ボックス）: ベンチマーク名・スコア・従来手法比
- チャットパネル（HTMX でインライン展開、セッション切り替え可）
- ユーザータグ操作（追加フォーム / 削除モードトグル）

#### チャット HTMX パターン

Alpine の `@click` から `open-chat` カスタムイベントを dispatch し、HTMX がそれを受け取って POST する。これにより「初回クリック時のみ」チャットを読み込む。

```html
x-data="{ showChat: false, chatLoaded: false }"
@click="showChat=!showChat; if(showChat&&!chatLoaded){chatLoaded=true; htmx.trigger($el,'open-chat');}"
hx-trigger="open-chat"
hx-post="/chat/{{ item.id }}"
```

#### ID の CSS セーフ変換

arXiv ID の `.`（例: `2603.03283v1`）が CSS セレクタを壊すため:
```
item.id → safe_id: `:` → `-`、`/` → `-`、`.` → `-`
```
テンプレートでは `item.id | replace(':', '-') | replace('/', '-') | replace('.', '-')` を使用。

### 10.3 スティッキーセクションバー（`base.html`）

セクションをスクロールで通り過ぎたとき、画面上部に現在のセクション名を固定表示する機能。

#### 動作概要

1. `scroll` イベントで全 `section[data-section-title]` の位置を監視
2. セクションのボタン（トグル）が `getBoundingClientRect().top < threshold` になったら「貼りつき」状態に移行
3. クローンボタンを `position:fixed; top:52px` の `stickyWrap` に表示
4. クローンをクリックするとセクションが折りたたまれ、元の位置にスクロール

#### 閾値（threshold）

- **メインセクション**: `NAV_H = 52px`（ナビバーの高さ）
- **サブセクション**: `NAV_H + 親セクションのボタン高さ + 4px`
  → サブトグルがメインクローンの裏に入らないように親分だけずらす

#### 自然なスクロールアウト（push ロジック）

次のセクションに差し掛かったとき、CSS アニメーションを使わず **scroll と同期した proportional translateY** で押し出す:

```javascript
var pushPx = Math.min(triggerY - nextTop, stickyH);
stickyWrap.style.transition = 'none';
stickyWrap.style.transform = 'translateY(-' + pushPx + 'px)';
```

#### 2層構造（main + sub-wrap）

```
stickyWrap
├── [main clone]     z-index:1  ← メインセクションのクローン
└── [data-sub-wrap]  z-index:0  ← サブセクションのクローン群
      ├── [sub clone A]
      └── [sub clone B]
```

- メインが次のメインに押し出される: `stickyWrap` 全体を translateY
- サブが次のサブに押し出される: `[data-sub-wrap]` だけを translateY（メインクローンの裏に滑り込む）

### 10.4 引用リンクのスムーズスクロール（`base.html`）

一面まとめ内の引用リンク（`[↗]`）をクリックしたとき、対象記事カードまでスムーズにスクロールする。

#### 処理フロー

1. `a[href^="#article-"]` または `/archive/...#article-...` リンクをインターセプト
2. 対象セクションを `Alpine.$data(sEl).open = true` で展開
3. スクロール位置を動的に計算してオフセットを適用

#### スクロールオフセット計算

```javascript
var stickyOffset = 52;  // NAV_H
// 対象要素の先祖 section[data-section-title] を列挙
sectionStack.reverse().forEach(function(sec, idx) {
    var btn = sec.querySelector(':scope > button');
    if (btn) {
        if (idx > 0) stickyOffset += 4;  // セクション間 gap
        stickyOffset += btn.offsetHeight; // 各クローンの高さ
    }
});
stickyOffset += sectionStack.length >= 2 ? 40 : 8;  // バッファ
```

- サブセクション付き（2段階）: `+40px` の余裕
- 単体セクション: `+8px` の余裕

### 10.5 ユーザータグ（HTMX）

- **追加**: `POST /user-tags/{article_id}` にフォーム送信 → `#user-tags-{safe_id}` を innerHTML スワップ
- **削除モード**: Alpine の `deleteMode` フラグで × ボタンを表示/非表示
- **削除**: `hx-delete` で `DELETE /user-tags/{article_id}/{tag}` → 同じくスワップ
- バリデーション: 50文字以内、`^[\w\u3000-\u9FFF\-]+$` パターン（サーバサイド）

---

## 11. 設定・環境変数

`app/config.py` の `Settings` クラスで `.env` から読み込む。

| 変数名 | 説明 |
|--------|------|
| `GEMINI_API_KEY` | Google Gemini API キー |
| `GEMINI_SUMMARY_MODEL` | 一面まとめ生成モデル（デフォルト: `gemini-3-flash-preview`）— `digest.py` で使用 |
| `GEMINI_CHAT_MODEL` | 個別記事要約・チャット応答モデル（デフォルト: `gemini-3.1-flash-lite`）— `summarizer.py` / `chat.py` で使用 |
| `GEMINI_SEARCH_THRESHOLD` | チャット時の Google Search グラウンディング閾値（デフォルト: `0.3`、0.0=常に検索、1.0=検索しない） |
| `SMTP_HOST` | SMTP サーバーホスト |
| `SMTP_PORT` | SMTP ポート |
| `SMTP_USER` | SMTP ユーザー名 |
| `SMTP_PASSWORD` | SMTP パスワード |
| `NOTIFY_EMAIL` | 通知先メールアドレス |
| `DATA_DIR` | JSON 保存ディレクトリ（デフォルト: `./data`） |
| `SUMMARIES_DIR` | Markdown 保存ディレクトリ（デフォルト: `./summaries`） |
| `DB_PATH` | SQLite パス（デフォルト: `./db/survey.db`） |
| `LOG_DIR` | ログディレクトリ（デフォルト: `./logs`） |

---

## 12. 管理者エンドポイント

認証なし（個人利用のため）。UI 上の「今すぐ収集」ボタンからも呼び出せる。

### `POST /admin/run-pipeline`

パイプラインを非同期で即時実行する。

```
パラメータ: date_str (optional, YYYY-MM-DD)
省略時: 今日を collection_date として実行（target_date = 前日）
```

### `POST /admin/reprocess-summaries`

既存 JSON の未要約（`summarized=False`）アイテムのみ再要約する（収集はスキップ）。

```
パラメータ: date_str (optional, YYYY-MM-DD)
省略時: 今日の JSON を対象
```

---

---

## ページ別機能ガイド

### `/` — トップページ（今日の一面）

当日のパイプライン実行結果を表示するメインページ。

- **一面まとめ**: Gemini で生成された Markdown 形式の日次まとめ。引用リンク `[↗]` をクリックすると対象記事カードまでスムーズスクロール
- **記事カード**: 各カテゴリの記事をセクション・サブセクション単位で折りたたみ表示
  - 「要約を見る」で日本語要約・新規性・メタ的な学び・定量指標を展開
  - 「チャットを開く」で記事に関する AI チャットをインライン展開
  - 「タグを管理」で任意のタグを追加・削除
- **スティッキーセクションバー**: スクロール中でも現在のセクション名を画面上部に固定表示

### `/archive/YYYY-MM-DD` — 過去日付アーカイブ

過去の特定日の記事一覧。トップページと同じレイアウトで、一面まとめの引用リンクも `/archive/` 内のページ内リンクとして機能する。

### `/summaries` — サマリー履歴一覧

- **最新3日分ビュー**: 直近3日分の一面まとめを縦並びでプレビュー表示
- **全件ビュー**: 全日付を日付降順のリストで表示。各行をクリックで詳細ページへ遷移

### `/summaries/YYYY-MM-DD` — サマリー詳細

特定日の一面まとめを Markdown レンダリングして表示。引用リンクは対応アーカイブページへのリンクとして機能。

### `/tags/` — タグ一覧

- **AI 生成タグ** (indigo): LLM が生成した `hashtags` フィールドのタグをタグクラウド形式で表示
- **マイタグ** (emerald): ユーザーが手動で追加したタグを別セクションで表示
- 出現回数に応じてタグのサイズ・色の濃さが変化

### `/tags/{tag_name}` — タグ別記事一覧

指定したタグを持つ記事を全期間・全カテゴリから横断検索して表示。AI タグ・マイタグの両方を対象に検索する。

### `/chats` — チャット検索・一覧

全チャット履歴をキーワード検索・一覧表示。チャットタイトル・メッセージ内容・記事タイトルで検索可能。

---

*最終更新: 2026-03-22 — Google Search グラウンディング統合・chat_messages スキーマ更新・GEMINI_SEARCH_THRESHOLD 追加・docs/env.md 追加を反映。*
