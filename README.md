# AI Daily Survey

毎朝 JST 09:00 に AI 関連の論文・記事を自動収集・要約して 1 ページで閲覧できる Web アプリ。

## 機能概要

| ページ | URL | 説明 |
|--------|-----|------|
| **トップページ** | `/` | 当日の一面まとめ + 全カテゴリの記事一覧。記事ごとに要約・チャット・タグ管理が可能 |
| **アーカイブ** | `/archive/YYYY-MM-DD` | 過去日付の記事一覧。トップページと同じレイアウト |
| **サマリー履歴** | `/summaries` | 過去の一面まとめを一覧表示。最新3日分ビューと全件ビューを切り替え可能 |
| **サマリー詳細** | `/summaries/YYYY-MM-DD` | 特定日の一面まとめを Markdown でレンダリング表示 |
| **タグ一覧** | `/tags/` | AI 生成タグとユーザー追加タグを別セクションで一覧表示。出現回数でサイズが変わるタグクラウド形式 |
| **タグ別記事** | `/tags/{tag_name}` | 指定タグを持つ記事を全期間・全カテゴリから横断検索して表示 |
| **チャット検索** | `/chat/search` | 記事チャットと日毎チャットを分けて一覧・キーワード検索 |

### 収集カテゴリ

| カテゴリ | 内容 | 収集方法 |
|----------|------|----------|
| CV 論文 | arXiv `cs.CV` + OpenReview（CVPR / NeurIPS / ICLR 等10学会） | arXiv API + OpenReview API |
| AI 全般論文 | arXiv `cs.LG` / `cs.AI` / `cs.CL` | arXiv API |
| AI 企業動向（自社発表） | OpenAI / Google / Anthropic / Meta / Amazon / Alibaba 公式ブログ | RSS フィード |
| AI 企業動向（その他報道） | BBC / TechCrunch / The Verge / Wired | RSS フィード + キーワードフィルタ |
| Qiita | AI・機械学習・LLM 関連記事 | REST API |
| Zenn | AI・機械学習・LLM 関連記事 | RSS フィード |
| Reddit | r/MachineLearning / r/artificial / r/LocalLLaMA | JSON API |
| Python 情報 | GitHub Trending (Python) | Web スクレイピング |

> GitHub Trending は `github.com/trending/python?since=daily` を BeautifulSoup でパースし、リポジトリ名・説明・スター数を抽出しています。

---

## 技術スタック

| レイヤー | 技術 |
|----------|------|
| Backend | Python 3.12 + FastAPI |
| Frontend | Jinja2 + HTMX + Alpine.js + Tailwind CSS (CDN) |
| DB | SQLite (aiosqlite + SQLAlchemy async) |
| LLM | Google Gemini API |
| スケジューラ | APScheduler (AsyncIOScheduler, Asia/Tokyo) |
| コンテナ | Docker + uv |
| 通知 | SMTP メール |

### LLM 利用詳細

| 用途 | モデル | 説明 |
|------|--------|------|
| 個別記事の要約 | gemini-2.5-flash | 各記事の要約・タグ生成・メタ的な学びの抽出 |
| 一面まとめ（ダイジェスト） | gemini-2.5-pro | 全カテゴリの記事を俯瞰した日次サマリーを生成 |
| 記事チャット | gemini-2.5-flash + RAG + Google Search | 記事本文を RAG コンテキストとし、必要に応じて Google 検索で補完して回答 |
| 日毎チャット | gemini-2.5-flash + RAG + Google Search | その日の全記事要約をコンテキストとし、横断的な質問に回答 |

#### チャット Web 検索グラウンディング

チャット機能は Gemini の **Google Search グラウンディング**を統合しています。RAG コンテキスト（記事本文）だけでは回答できない基礎概念・背景知識・最新動向の質問に対して、Gemini が自動的に Google 検索を実行し、検索結果を根拠にした回答を生成します。

- 検索の実行判断は Gemini 自身が行う（`dynamic_threshold` で頻度を調整可能）
- 検索が使われた場合、回答の下にソースリンクが折りたたみ表示される
- `GEMINI_SEARCH_THRESHOLD` 環境変数で閾値を制御（0.0=常に検索, 1.0=検索しない, デフォルト 0.3）

### データ保存

| データ | 形式 | 保存先 |
|--------|------|--------|
| 日次収集データ | JSON | `data/YYYY-MM-DD/` |
| 日次サマリー | Markdown | `summaries/YYYY-MM-DD.md` |
| チャット履歴・ユーザータグ | SQLite | `db/survey.db` |

JSON ファイルが正のデータソースであり、DB はチャット履歴とユーザータグの永続化にのみ使用しています。

---

## セットアップ

### 共通手順

```bash
# 1. リポジトリをクローン
git clone <repo-url> everyday-survey
cd everyday-survey

# 2. 環境変数を設定
cp .env.example .env
# .env を編集して必要な値を入力（詳細は docs/env.md を参照）
```

### Docker で起動（推奨）

```bash
# ビルド＆起動
docker compose up --build -d

# ログ確認
docker compose logs -f

# 停止
docker compose down
```

#### コンテナ構成

| サービス名 | イメージ | 説明 |
|-----------|---------|------|
| `app` | `python:3.12-slim` ベース | FastAPI + APScheduler を単一コンテナで実行。ポート 8000 を公開 |

単一コンテナ構成です。SQLite をファイルベースで使用するため DB コンテナは不要です。
データは以下のボリュームマウントでホスト側に永続化されます:

| マウント | 用途 |
|---------|------|
| `./data:/app/data` | 日次収集 JSON |
| `./summaries:/app/summaries` | 日次サマリー Markdown |
| `./db:/app/db` | SQLite DB (チャット履歴・ユーザータグ) |
| `./logs:/app/logs` | アプリログ |
| `./app:/app/app` | 開発時ホットリロード用 |

### ローカルで直接起動

前提: Python 3.12+ と [uv](https://docs.astral.sh/uv/) がインストール済みであること。

```bash
# 依存パッケージをインストール
uv sync

# 起動
TZ=Asia/Tokyo uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

http://localhost:8000 でアクセスできます。`data/` や `db/` などのディレクトリは初回起動時に自動作成されます。

> **注意**: `TZ=Asia/Tokyo` を設定しないと、スケジューラの実行時刻（JST 09:00）がずれます。Docker の場合は Dockerfile 内で設定済みです。

---

## アクセス方法（SSH トンネル）

サーバをリモートに置く場合は、SSH トンネル経由でローカルブラウザからアクセスする。

### 1. SSH トンネルを張る

```bash
ssh -L 8000:localhost:8000 your-username@your-server.example.com
```

| オプション | 説明 |
|-----------|------|
| `-L 8000:localhost:8000` | ローカルの 8000 番をサーバの 8000 番に転送 |
| `your-username@your-server.example.com` | 接続先サーバ（各自の環境に合わせて変更） |

### 2. ブラウザでアクセス

```
http://localhost:8000
```

### バックグラウンドで接続したい場合

```bash
ssh -fNL 8000:localhost:8000 your-username@your-server.example.com
```

| オプション | 説明 |
|-----------|------|
| `-f` | バックグラウンドで実行 |
| `-N` | コマンド実行なし（トンネルのみ） |

切断するには:

```bash
# トンネルの PID を探して kill
lsof -ti:8000 | xargs kill
```

### `~/.ssh/config` に登録しておくと便利

```
Host survey
    HostName your-server.example.com
    User your-username
    LocalForward 8000 localhost:8000
```

登録後は以下だけで接続できる:

```bash
ssh survey
```

---

## 手動収集

ブラウザで「今すぐ収集」ボタンを押すか、以下のコマンドを実行:

```bash
curl -X POST http://localhost:8000/admin/run-pipeline
```

---

## 詳細ドキュメント

- `app/README.md` — アプリケーション構造・モジュール解説
- `docs/env.md` — 環境変数の設定ガイド（`.env` の全項目解説）
- `docs/implementation.md` — 実装詳細・システムワークフロー
- `docs/article_format.md` — 記事フォーマット定義
- `docs/requirements.md` — 要件定義書
