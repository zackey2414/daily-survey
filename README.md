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
| **チャット検索** | `/chats` | 全チャット履歴の一覧とキーワード検索 |

### 収集カテゴリ

| カテゴリ | 内容 |
|----------|------|
| CV 論文 | arXiv `cs.CV` + OpenReview（CVPR / NeurIPS / ICLR 等10学会） |
| AI 全般論文 | arXiv `cs.LG` / `cs.AI` / `cs.CL` |
| AI 企業動向（自社発表） | OpenAI / Google / Anthropic / Meta / Amazon / Alibaba 公式ブログ RSS |
| AI 企業動向（その他報道） | BBC / TechCrunch / The Verge / Wired 等の海外ニュース RSS |
| SNS・コミュニティ | Qiita / Zenn / Reddit |
| Python 情報 | PyPI RSS / GitHub Trending |

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

## セットアップ（初回・サーバ側）

```bash
# 1. リポジトリをクローン
git clone <repo-url> everyday-survey
cd everyday-survey

# 2. 環境変数を設定
cp .env.example .env
# .env を編集して GEMINI_API_KEY 等を入力

# 3. Docker で起動
docker compose up --build -d
```

## 起動・停止（サーバ側）

```bash
# 起動
docker compose up -d

# 停止
docker compose down

# ログ確認
docker compose logs -f
```

---

## 手動収集

ブラウザで「今すぐ収集」ボタンを押すか、以下のコマンドを実行:

```bash
curl -X POST http://localhost:8000/admin/run-pipeline
```

---

## 詳細ドキュメント

- `docs/implementation.md` — 実装詳細・システムワークフロー
- `docs/article_format.md` — 記事フォーマット定義
- `docs/requirements.md` — 要件定義書
