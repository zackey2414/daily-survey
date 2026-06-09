# 環境変数の設定ガイド

`.env.example` を `.env` にコピーし、必要な値を設定してください。

```bash
cp .env.example .env
```

## 変更の必要度

| 変更必要度 | 意味 |
|-----------|------|
| **必須** | デフォルト値では動作しない。自分の値に書き換える必要がある |
| **任意** | デフォルトで動作するが、用途に応じて変更可能 |
| **原則そのまま** | 特別な理由がない限り変更不要。変更すると動作に影響する可能性がある |

## 一覧

### Google Gemini API

| 変数名 | デフォルト | 変更必要度 | 説明 |
|--------|-----------|-----------|------|
| `GEMINI_API_KEY` | `your_gemini_api_key_here` | **必須** | Gemini API キー。[Google AI Studio](https://aistudio.google.com/apikey) で取得する。全ての LLM 機能（要約・チャット・ダイジェスト生成）に使用される |
| `GEMINI_SUMMARY_MODEL` | `gemini-3-flash-preview` | 原則そのまま | ダイジェスト（一面まとめ）生成に使用するモデル。全カテゴリを俯瞰する品質重視のため、個別要約より高性能なモデルを使う |
| `GEMINI_CHAT_MODEL` | `gemini-3.1-flash-lite` | 原則そのまま | 個別記事の要約・チャット応答・タイトル生成・テーマキーワード生成に使用するモデル。件数が多いためトークン単価が最も安い flash-lite を使う |
| `GEMINI_SEARCH_THRESHOLD` | `0.3` | 任意 | チャット時の Google Search グラウンディング閾値。`0.0` で常に検索、`1.0` で検索しない。低いほど検索が発動しやすくなるが、API コストが増加する |

### Reddit API

| 変数名 | デフォルト | 変更必要度 | 説明 |
|--------|-----------|-----------|------|
| `REDDIT_CLIENT_ID` | `your_reddit_client_id` | **必須** | Reddit API のクライアント ID。[Reddit アプリ設定](https://www.reddit.com/prefs/apps) で「script」タイプのアプリを作成して取得する |
| `REDDIT_CLIENT_SECRET` | `your_reddit_client_secret` | **必須** | Reddit API のクライアントシークレット。上記と同じページで取得する |
| `REDDIT_USER_AGENT` | `AI-Daily-Survey/1.0` | 任意 | Reddit API リクエスト時の User-Agent ヘッダー。Reddit の利用規約上、アプリ名を含む識別可能な文字列にする必要がある |

### Qiita API

| 変数名 | デフォルト | 変更必要度 | 説明 |
|--------|-----------|-----------|------|
| `QIITA_ACCESS_TOKEN` | `your_qiita_token_here` | **必須** | Qiita API のアクセストークン。[Qiita トークン発行ページ](https://qiita.com/settings/tokens/new) で `read_qiita` スコープを付けて発行する |

### SMTP（メール通知）

パイプライン完了時にメールで通知を送る機能で使用する。メール通知が不要な場合はデフォルトのままでも起動はできるが、通知送信時にエラーになる。

| 変数名 | デフォルト | 変更必要度 | 説明 |
|--------|-----------|-----------|------|
| `SMTP_HOST` | `smtp.gmail.com` | 任意 | SMTP サーバのホスト名。Gmail 以外を使う場合に変更する |
| `SMTP_PORT` | `587` | 任意 | SMTP サーバのポート番号。TLS (STARTTLS) の標準ポートは 587 |
| `SMTP_USERNAME` | `your_email@gmail.com` | **必須** | SMTP 認証に使うメールアドレス |
| `SMTP_PASSWORD` | `your_app_password` | **必須** | SMTP 認証のパスワード。Gmail の場合は[アプリパスワード](https://myaccount.google.com/apppasswords)を使用する（通常のパスワードでは認証できない） |
| `SMTP_FROM` | `your_email@gmail.com` | **必須** | 通知メールの送信元アドレス。通常は `SMTP_USERNAME` と同じ値にする |
| `SMTP_TO` | `your_email@gmail.com` | **必須** | 通知メールの送信先アドレス。自分のメールアドレスを設定する |

### GitHub API

| 変数名 | デフォルト | 変更必要度 | 説明 |
|--------|-----------|-----------|------|
| `GITHUB_TOKEN` | (空) | 任意 | GitHub Personal Access Token。設定すると GitHub REST API のレートリミットが 60→5000 req/h に緩和される。GitHub Trending 収集時に各リポジトリの正確な総スター数を取得するために使用。[Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens) で発行する（スコープ不要、public repo の読み取りのみ） |

### スケジューラ

| 変数名 | デフォルト | 変更必要度 | 説明 |
|--------|-----------|-----------|------|
| `SCHEDULE_HOUR` | `12` | 任意 | 日次パイプライン実行時刻の「時」（JST）。デフォルトは正午 12 時 |
| `SCHEDULE_MINUTE` | `0` | 任意 | 日次パイプライン実行時刻の「分」（JST）。デフォルトは 0 分 |

> 例: `SCHEDULE_HOUR=7` `SCHEDULE_MINUTE=30` にすると毎朝 7:30 (JST) にパイプラインが実行される。
>
> **正午がデフォルトの理由**: arXiv は新着論文の `submittedDate` インデックス反映に時間がかかり、
> 9 時 (= 00:00 UTC) 実行だと当日分の論文が 0 件になりやすい。3 時間後の正午 (= 03:00 UTC) に
> ずらして索引反映を待つ。万一 0 件でも収集側で遡及日数を自動拡大して再取得する。

### アプリ設定

| 変数名 | デフォルト | 変更必要度 | 説明 |
|--------|-----------|-----------|------|
| `APP_HOST` | `0.0.0.0` | 原則そのまま | uvicorn のバインドアドレス。`0.0.0.0` で全インターフェースからアクセス可能 |
| `APP_PORT` | `8000` | 原則そのまま | uvicorn のポート番号。変更する場合は `docker-compose.yml` のポートマッピングも合わせて変更する必要がある |
| `DATA_DIR` | `data` | 原則そのまま | 日次収集 JSON の保存ディレクトリ。Docker 環境ではボリュームマウントとの整合性に注意 |
| `SUMMARIES_DIR` | `summaries` | 原則そのまま | 日次サマリー Markdown の保存ディレクトリ |
| `DB_PATH` | `db/survey.db` | 原則そのまま | SQLite データベースファイルのパス |
| `LOG_DIR` | `logs` | 原則そのまま | ログファイルの保存ディレクトリ |

## 最低限の設定例

以下の項目だけ設定すればアプリは起動・動作します（メール通知を除く）:

```bash
GEMINI_API_KEY=AIza...         # 必須: Gemini API キー
REDDIT_CLIENT_ID=abc123        # 必須: Reddit クライアント ID
REDDIT_CLIENT_SECRET=xyz789    # 必須: Reddit クライアントシークレット
QIITA_ACCESS_TOKEN=qiita_xxx   # 必須: Qiita トークン
```

メール通知も使う場合は `SMTP_*` の 4 項目（USERNAME, PASSWORD, FROM, TO）を追加で設定してください。
