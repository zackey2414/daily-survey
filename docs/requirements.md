# 要件定義書: AI Daily Survey Web Application

**バージョン**: 1.0
**作成日**: 2026-03-03
**ステータス**: ドラフト

---

## 目次

1. [プロジェクト概要](#1-プロジェクト概要)
2. [システム構成・技術スタック](#2-システム構成技術スタック)
3. [機能要件](#3-機能要件)
4. [画面設計](#4-画面設計)
5. [データモデル](#5-データモデル)
6. [ディレクトリ構成](#6-ディレクトリ構成)
7. [外部API・収集ソース一覧](#7-外部api収集ソース一覧)
8. [非機能要件](#8-非機能要件)
9. [未確定事項・前提条件](#9-未確定事項前提条件)

---

## 1. プロジェクト概要

### 1.1 目的

毎朝 JST 09:00 に自動実行し、前日1日に公開された AI 関連の論文・記事・サービス情報を収集・要約して、1ページで最新の AI 動向をチェックできる個人向け Web アプリケーションを構築する。

### 1.2 対象ユーザー

開発者本人のみ（リモートサーバに SSH トンネルでアクセス）。認証機構の実装は不要。

### 1.3 収集対象カテゴリと表示順

| 優先順 | カテゴリ | 概要 |
|--------|----------|------|
| 1 | **CV論文** | arXiv `cs.CV` + OpenReview 対象学会 |
| 2 | **AI全般論文** | arXiv `cs.LG` / `cs.AI` / `cs.CL` |
| 3 | **AI企業動向** | OpenAI, Google, Anthropic, Meta, Amazon, Alibaba |
| 4 | **SNS・コミュニティ** | Qiita, Zenn, Reddit |
| 5 | **Python情報** | PyPI, GitHub Trending, ライブラリ更新情報 |

---

## 2. システム構成・技術スタック

### 2.1 全体アーキテクチャ

```
┌─────────────────────────────────────────────────────┐
│                  Docker Container                    │
│                                                     │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │  Scheduler   │    │      FastAPI App           │  │
│  │  (cron/      │    │   Jinja2 + HTMX           │  │
│  │  APScheduler)│    │                           │  │
│  └──────┬───────┘    └─────────────┬─────────────┘  │
│         │                          │                 │
│         ▼                          ▼                 │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │  Collector   │    │         SQLite             │  │
│  │  (各種API/  │    │      (チャット履歴)         │  │
│  │   RSS/スクレ │    └───────────────────────────┘  │
│  │   イピング)  │                                    │
│  └──────┬───────┘    ┌───────────────────────────┐  │
│         │            │       JSON ファイル         │  │
│         ▼            │    (日次収集データ)         │  │
│  ┌──────────────┐    └───────────────────────────┘  │
│  │  Summarizer  │                                    │
│  │  (Gemini API)│    ┌───────────────────────────┐  │
│  └──────────────┘    │    Markdown ファイル        │  │
│                      │    (日次一面まとめ)         │  │
│                      └───────────────────────────┘  │
└─────────────────────────────────────────────────────┘
         │
         ▼
    メール通知 (SMTP)
```

### 2.2 技術スタック

| レイヤー | 技術 | 備考 |
|----------|------|------|
| コンテナ | Docker / Docker Compose | 必須 |
| Python 環境管理 | **uv** | pip の代替 |
| バックエンド | **Python 3.12+ / FastAPI** | |
| フロントエンド | **Jinja2 + HTMX** | Python ベースのテンプレート + 軽量インタラクション |
| CSS フレームワーク | **Tailwind CSS** | CDN 経由 or PostCSS |
| データベース | **SQLite** | チャット履歴のみ |
| データ保存 | **JSON ファイル** | 日次収集データ（再利用性重視） |
| サマリー保存 | **Markdown ファイル** | 日次一面まとめ |
| LLM API | **Google Gemini API** | 個別記事要約・チャット: `gemini-2.5-flash`、一面まとめ生成: `gemini-2.5-pro` |
| スケジューラ | **APScheduler**（FastAPI 組み込み）または **cron**（Docker 内） | JST 09:00 実行 |
| 通知 | SMTP（メール） | 収集完了時 |

### 2.3 Gemini API モデル選定方針

| 用途 | モデル | 設定変数 | 理由 |
|------|--------|----------|------|
| 個別記事・論文の要約 | `gemini-2.5-flash` | `GEMINI_CHAT_MODEL` | 件数が多く高速処理を優先 |
| 一面まとめ生成（日次ダイジェスト） | `gemini-2.5-pro` | `GEMINI_SUMMARY_MODEL` | 全体を見渡す高品質な要約が必要 |
| チャット応答 | `gemini-2.5-flash` | `GEMINI_CHAT_MODEL` | 対話的応答はコスト・速度を優先 |

- モデル名は設定ファイル（`.env`）で個別に切り替え可能

---

## 3. 機能要件

### 3.1 データ収集機能

#### 3.1.1 収集全体仕様

- **実行タイミング**: 毎日 JST 09:00
- **収集期間**: 前日 00:00〜23:59 JST に公開・更新されたもの
- **上限件数**: 各カテゴリ・各ソースごとに最大 20 件
- **出力形式**: JSON ファイル（`data/YYYY-MM-DD/` ディレクトリ以下）

#### 3.1.2 CV 論文収集（`cs.CV`）

**ソース1: arXiv**
- API: arXiv API (`http://export.arxiv.org/api/query`)
- カテゴリ: `cs.CV`
- 取得フィールド: タイトル, 著者, アブストラクト, arXiv ID, 公開日, PDF URL
- 上限: 20件/日

**ソース2: OpenReview**
- API: OpenReview API v2 (`https://api2.openreview.net`)
- 対象学会（優先順位順）:
  1. CVPR, NeurIPS, ICLR, ICCV, ICML, AAAI, ACL, ECCV, EMNLP, IJCAI（必須）
  2. WACV, ICIP, BMVC, ICPR, 3DV, ICDAR, FGR, ACCV（余力があれば）
- 収集基準: **前日（JST 00:00〜23:59）に新たな投稿・更新があった論文**を対象とする
  - 該当日に投稿・更新がない場合はその学会の項目をスキップする
- 上限: 20件/日（全学会合計）
- 取得フィールド: タイトル, 著者, アブストラクト, venue, 投稿日, URL

#### 3.1.3 AI 全般論文収集

- ソース: arXiv API
- カテゴリ（各カテゴリ独立して収集し、個別に表示）:
  - `cs.LG`（機械学習）: 上限 20件/日
  - `cs.AI`（人工知能）: 上限 20件/日
  - `cs.CL`（自然言語処理）: 上限 20件/日
- 取得フィールド: CV と同様

#### 3.1.4 AI 企業動向収集

- ソース: 各社公式ブログの RSS フィード / API
- 対象企業と RSS URL（確認が必要なものは調査の上設定）:

| 企業 | ソース |
|------|--------|
| OpenAI | `https://openai.com/blog/rss.xml` |
| Google DeepMind / Google AI | Google AI Blog RSS |
| Anthropic | `https://www.anthropic.com/rss.xml` |
| Meta AI | Meta AI Blog RSS |
| Amazon AWS AI | AWS News Blog RSS |
| Alibaba / DAMO Academy | 公式ブログ RSS（要調査） |

- 取得フィールド: タイトル, 公開日, 概要, URL
- 上限: 各社 5件/日（合計最大 30件）

#### 3.1.5 SNS・コミュニティ収集

**Qiita**
- API: Qiita API v2 (`https://qiita.com/api/v2/items`)
- 絞り込み: `tag:AI`, `tag:機械学習`, `tag:LLM` 等のトレンド記事
- 上限: 20件/日

**Zenn**
- ソース: Zenn RSS フィード（API 非公開のため RSS 使用）
- `https://zenn.dev/topics/機械学習/feed`  等
- 上限: 20件/日

**Reddit**
- API: Reddit API (`https://www.reddit.com/r/MachineLearning/.json` 等)
- 対象サブレディット: `r/MachineLearning`, `r/artificial`, `r/LocalLLaMA`
- 上限: 各 10件/日（合計 30件）

#### 3.1.6 Python 情報収集

- ソース（複数組み合わせ）:
  - PyPI RSS: `https://pypi.org/rss/updates.xml`
  - GitHub Trending（スクレイピング or 非公式 API）: Python カテゴリの当日トレンド
  - Python 公式サポート: Python.org ニュース RSS
- 取得内容: ライブラリ名, バージョン, 更新内容, URL
- 上限: 20件/日

---

### 3.2 要約・LLM 処理機能

#### 3.2.1 個別記事の要約

- 使用モデル: Gemini API（`gemini-2.5-flash`）— 件数が多く高速処理を優先
- 出力言語: **日本語**
- 論文（arXiv / OpenReview）の場合に含める内容:
  - 研究概要（何をしたか）
  - 新規性・貢献（既存手法との差異）
  - メタ的な学び（問題定式化・アプローチ・評価手法の観点）
  - 元論文リンク（arXiv / OpenReview URL）
- AI 企業動向記事の場合に含める内容:
  - 概要（何が発表されたか）
  - ポイント（3点）
  - **定量指標**（ベンチマーク名・スコア・従来手法比など）
  - 元記事リンク
- コミュニティ・Python 記事の場合に含める内容:
  - 概要（何が発表・議論されているか）
  - ポイント（3点）
  - 元記事リンク

#### 3.2.2 一面まとめ生成（新聞一面）

- トリガー: 全カテゴリの収集・要約完了後に自動生成
- 使用モデル: Gemini API（`gemini-2.5-pro`）— 全カテゴリを俯瞰する高品質な要約が必要
- 入力: 全カテゴリの要約データ（JSON）
- 出力形式: **Markdown**（`summaries/YYYY-MM-DD.md`）
- 出力内容:
  - 日付とタイトル
  - 本日の主要トピック（ハイライト）
  - 各カテゴリの注目情報（2〜3点ずつ）
  - 全体的な AI 動向の所感
- 文字数: 最大 2000文字
- 表示言語: 日本語

---

### 3.3 Web アプリケーション機能

#### 3.3.1 メインページ（今日の一面）

- URL: `/` または `/today`
- 表示内容（上から順に）:
  1. 一面まとめセクション（Markdown レンダリング）
  2. CV 論文セクション（arXiv cs.CV + OpenReview）
  3. AI 全般論文セクション（cs.LG / cs.AI / cs.CL 各サブセクション）
  4. AI 企業動向セクション
  5. SNS・コミュニティセクション（Qiita / Zenn / Reddit）
  6. Python 情報セクション

- 各記事カードに表示する情報:
  - タイトル（日本語タイトルも表示）
  - 要約（折りたたみ可能）
  - 元リンク
  - 「チャットを開く」ボタン

#### 3.3.2 チャット機能

- 各記事ごとに独立したチャットを持つ
- **1記事に対して複数チャット**を作成可能
  - チャット間の切り替え: 記事カード下部の `<` `>` ボタン（ページネーション形式）
  - 新規チャット作成ボタン（`+` アイコン等）
- チャット応答の参照範囲: 対象記事の全文・要約データ（RAG 的に Gemini API に渡す）
- チャットタイトル: 初回メッセージをもとに **LLM が自動生成**（最大 30文字程度）
- チャット履歴の保存: **SQLite**（後述のデータモデル参照）
- セッションをまたいでも続きから回答可能

**チャット検索機能**
- URL: `/chats`
- 全チャット一覧表示
- キーワード検索（タイトル・本文対象）
- 記事タイトルでフィルタリング

#### 3.3.3 日次サマリーフィードページ

- URL: `/summaries?page=N`
- 全一面まとめを**日付降順**で表示（最新が先頭）
- **ページネーション**: 1ページ10件、`?page=N` クエリで切り替え
- 各カードにタイトル・冒頭プレビュー（200文字）・「続きを読む」リンクを表示
- 各日付のカードをクリックすると、その日のまとめページに遷移（`/summaries/YYYY-MM-DD`）
- サマリーは Markdown ファイルをレンダリングして表示

#### 3.3.4 過去日付の記事ページ

- URL: `/archive/YYYY-MM-DD`
- 特定日の全収集データを表示（JSON から読み込み）
- メインページと同じレイアウト

---

### 3.4 通知機能

- **トリガー**: 日次収集・要約・一面まとめ生成の全工程完了後
- **手段**: メール（SMTP）
- **通知内容**:
  - 実行日時
  - 各カテゴリの収集件数
  - 処理時間
  - エラーがあれば内容
  - 一面まとめの冒頭（プレビュー）
- **設定**: SMTP サーバ・認証情報は `.env` ファイルで管理

---

## 4. 画面設計

### 4.1 メインページ構成（ワイヤーフレーム）

```
┌──────────────────────────────────────────────────────┐
│  AI Daily Survey         📅 2026-03-03  [アーカイブ]  │
│  [今日] [サマリー履歴] [チャット一覧]                  │
├──────────────────────────────────────────────────────┤
│ ▼ 本日の一面まとめ                                    │
│  ─────────────────────────────────────────────────── │
│  （Markdown レンダリング / 2000文字以内）              │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ CV 論文（cs.CV + OpenReview）              [20件]   │
│  ┌────────────────────────────────────────────────┐  │
│  │ [arXiv] タイトル                    2026-03-02  │  │
│  │ 著者: ...                           [元論文↗]  │  │
│  │ ▶ 要約を見る                                   │  │
│  │                              [💬 チャットを開く] │  │
│  └────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────┐  │
│  │ ...（繰り返し）                                 │  │
│  └────────────────────────────────────────────────┘  │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ AI 全般論文                                        │
│   ▼ cs.LG（機械学習）                       [20件]   │
│   ▼ cs.AI（人工知能）                       [20件]   │
│   ▼ cs.CL（自然言語処理）                   [20件]   │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ AI 企業動向                                        │
│   OpenAI / Google / Anthropic / Meta / Amazon / Ali  │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ SNS・コミュニティ                                   │
│   Qiita / Zenn / Reddit                              │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ Python 情報                                        │
│   PyPI / GitHub Trending                             │
└──────────────────────────────────────────────────────┘
```

### 4.2 チャットパネル構成

```
記事カードの下部に展開するインラインチャットパネル：

┌────────────────────────────────────────────────────┐
│ [論文タイトル] のチャット                            │
│  チャット 2/3    [< 前のチャット] [次のチャット >]   │
│  "この手法の計算量は？"              [+ 新規チャット] │
├────────────────────────────────────────────────────┤
│ You: この手法の計算量はどのくらいですか？            │
│                                                    │
│ AI:  論文によると、提案手法の計算量は...             │
│      （対象論文の内容を参照した回答）               │
│                                                    │
│ You: ...                                           │
├────────────────────────────────────────────────────┤
│ [テキスト入力欄                          ] [送信]   │
└────────────────────────────────────────────────────┘
```

### 4.3 サマリー履歴ページ

```
まとめ履歴          全 N 件 — 最新から降順

┌──────────────────────────────────────────────────────┐
│  2026-03-03  本日の AI 動向まとめ            [全文 →]  │
│  ──────────────────────────────────────────────────  │
│  （冒頭プレビュー 200文字）                            │
│  続きを読む →                                         │
└──────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────┐
│  2026-03-02  ...                             [全文 →]  │
└──────────────────────────────────────────────────────┘
...（合計10件）

← 前へ  1  2  3  …  次へ →
```

---

## 5. データモデル

### 5.1 JSON データ構造（日次収集データ）

**ファイルパス**: `data/YYYY-MM-DD/papers_cv.json`

```json
{
  "date": "2026-03-02",
  "category": "cs.CV",
  "source": "arxiv",
  "collected_at": "2026-03-03T09:00:00+09:00",
  "total": 20,
  "items": [
    {
      "id": "arxiv:2603.12345",
      "title_en": "Original Title in English",
      "title_ja": "日本語タイトル（LLM生成）",
      "authors": ["Author A", "Author B"],
      "abstract_en": "Original abstract...",
      "summary_ja": "日本語要約（LLM生成）...",
      "novelty_ja": "新規性・貢献の説明...",
      "published_date": "2026-03-02",
      "url": "https://arxiv.org/abs/2603.12345",
      "pdf_url": "https://arxiv.org/pdf/2603.12345",
      "source_type": "arxiv",
      "tags": ["cs.CV"]
    }
  ]
}
```

**ファイル一覧（1日分）**:
```
data/YYYY-MM-DD/
├── papers_cv.json           # cs.CV（arXiv + OpenReview 統合）
├── papers_lg.json           # cs.LG
├── papers_ai.json           # cs.AI
├── papers_cl.json           # cs.CL
├── industry_news.json       # 企業動向
├── community.json           # SNS・コミュニティ
└── python_news.json         # Python 情報
```

**サマリーファイル**:
```
summaries/
└── YYYY-MM-DD.md
```

### 5.2 SQLite スキーマ（チャット履歴）

```sql
-- 記事テーブル（チャットと記事の紐付け用）
CREATE TABLE articles (
    id          TEXT PRIMARY KEY,   -- "arxiv:2603.12345" 等
    date        TEXT NOT NULL,      -- "2026-03-02"
    category    TEXT NOT NULL,      -- "cv", "lg", "ai", "cl", "industry", "community", "python"
    title_ja    TEXT NOT NULL,
    url         TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- チャットセッションテーブル
CREATE TABLE chat_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id),
    title       TEXT,               -- LLM が自動生成（最大30文字）
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- チャットメッセージテーブル
CREATE TABLE chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES chat_sessions(id),
    role        TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chat_sessions_article ON chat_sessions(article_id);
CREATE INDEX idx_chat_messages_session ON chat_messages(session_id);
```

---

## 6. ディレクトリ構成

```
everyday-survey/
├── docker-compose.yml
├── Dockerfile
├── .env                          # 環境変数（Gemini API キー, SMTP 設定等）
├── .env.example
├── pyproject.toml                # uv プロジェクト設定
├── uv.lock
│
├── app/                          # FastAPI アプリケーション
│   ├── main.py                   # FastAPI エントリポイント
│   ├── scheduler.py              # APScheduler 設定
│   ├── routers/
│   │   ├── main_page.py          # メインページ（今日の一面）
│   │   ├── archive.py            # 過去日付アーカイブ
│   │   ├── summaries.py          # サマリー履歴フィード
│   │   └── chat.py               # チャット API
│   ├── services/
│   │   ├── collector/
│   │   │   ├── arxiv.py          # arXiv 収集
│   │   │   ├── openreview.py     # OpenReview 収集
│   │   │   ├── industry.py       # 企業 RSS 収集
│   │   │   ├── community.py      # Qiita / Zenn / Reddit 収集
│   │   │   └── python_news.py    # Python 情報収集
│   │   ├── summarizer.py         # Gemini API 要約処理
│   │   ├── digest.py             # 一面まとめ生成
│   │   └── notifier.py           # メール通知
│   ├── db/
│   │   ├── database.py           # SQLite 接続管理
│   │   └── models.py             # SQLAlchemy モデル（または生 SQL）
│   └── templates/                # Jinja2 テンプレート
│       ├── base.html
│       ├── index.html
│       ├── archive.html
│       ├── summaries.html
│       ├── summary_detail.html
│       └── components/
│           ├── article_card.html
│           └── chat_panel.html
│
├── data/                         # 日次収集 JSON データ
│   └── YYYY-MM-DD/
│       ├── papers_cv.json
│       ├── papers_lg.json
│       ├── papers_ai.json
│       ├── papers_cl.json
│       ├── industry_news.json
│       ├── community.json
│       └── python_news.json
│
├── summaries/                    # 日次一面まとめ（Markdown）
│   └── YYYY-MM-DD.md
│
├── db/
│   └── survey.db                 # SQLite データベース
│
└── logs/
    └── collector.log             # 収集ログ
```

---

## 7. 外部API・収集ソース一覧

### 7.1 API キー・認証が必要なもの

| サービス | 認証方式 | 備考 |
|----------|----------|------|
| Google Gemini API | API キー | `.env` に保存 |
| Reddit API | OAuth2 (Client ID / Secret) | `praw` ライブラリ使用 |
| Qiita API | アクセストークン（任意） | 未認証でも一部利用可能 |

### 7.2 認証不要（RSS / 公開 API）

| サービス | エンドポイント |
|----------|---------------|
| arXiv API | `http://export.arxiv.org/api/query` |
| OpenReview API v2 | `https://api2.openreview.net/notes` |
| Zenn RSS | `https://zenn.dev/topics/機械学習/feed` 等 |
| PyPI RSS | `https://pypi.org/rss/updates.xml` |
| 各社公式 RSS | 各社ブログの RSS URL（設定ファイルで管理） |

### 7.3 スクレイピングが必要なもの

| サービス | 備考 |
|----------|------|
| GitHub Trending | 非公式、HTML スクレイピング（`BeautifulSoup`） |

---

## 8. 非機能要件

### 8.1 スケジューリング

- 実行タイミング: 毎日 JST 09:00（`Asia/Tokyo`）
- 方式: APScheduler（FastAPI アプリ内に組み込み）または Docker コンテナ内 cron
- タイムアウト: 全工程 60分以内（超過時はエラー通知）
- エラー時の挙動: エラーをログに記録し、完了通知メールにエラー内容を含めて送信

### 8.2 インフラ・環境

- コンテナ: **Docker 必須**（`docker-compose.yml` でサービス定義）
- Python 環境管理: **uv 必須**（`pyproject.toml` でパッケージ管理）
- Dockerfile ベースイメージ: `python:3.12-slim`
- ポート: `8000`（ローカル SSH トンネル経由でアクセス）

### 8.3 データ保存・永続化

| データ | 形式 | 保存場所 | 保持期間 |
|--------|------|----------|----------|
| 収集データ | JSON | `data/YYYY-MM-DD/` | 無期限（手動削除） |
| 一面まとめ | Markdown | `summaries/` | 無期限 |
| チャット履歴 | SQLite | `db/survey.db` | 無期限 |
| ログ | テキスト | `logs/` | 30日ローテーション |

### 8.4 レスポンシブ対応

- PC（1200px 以上）: 必須対応
- スマートフォン: できれば対応（必須ではない）

### 8.5 API コスト管理

- Gemini API の 1日あたりの使用量をログに記録
- モデルは `.env` の設定で切り替え可能にし、コスト最適化を容易にする

---

## 9. 未確定事項・前提条件

### 9.1 前提条件

- リモートサーバ上に Docker がインストール済みであること
- Gemini API キーを取得済みであること
- SMTP サーバ（Gmail 等）の設定情報を保有していること
- Reddit API の Client ID / Secret を取得済みであること

### 9.2 未確定事項（実装時に確認・決定が必要）

| 項目 | 内容 | 優先度 |
|------|------|--------|
| Alibaba の RSS URL | 公式ブログ RSS の存在確認が必要 | 中 |
| OpenReview の学会 venue 名 | API で使用する正式な venue ID の確認が必要 | 高 |
| Qiita 未認証 API の取得上限 | レート制限の確認が必要 | 中 |
| GitHub Trending のスクレイピング安定性 | 定期的な HTML 構造変更に注意 | 低 |
| arXiv AI全般 20件の単位 | カテゴリ別に各 20件（合計最大 60件）で実装 | 確定 |

### 9.3 将来拡張の可能性（スコープ外）

- Slack / LINE 通知対応
- 複数ユーザー対応・認証機構
- モバイルアプリ対応
- カスタムキーワードフィルタリング機能
- 論文の重要度スコアリング（引用数・いいね数等）

---

*本ドキュメントは要件定義のドラフトであり、実装開始前に最終確認を行うこと。*
