# GitHub Trending 収集機能

全言語の GitHub Trending ページから AI/LLM 関連リポジトリを収集し、4つのランキング軸で表示する機能。

---

## 概要

GitHub Trending の3つの期間ページ（Daily / Weekly / Monthly）をスクレイピングし、AI/LLM 関連のキーワードでフィルタリングして収集する。各期間のページには異なるリポジトリが掲載されるため、**4つの独立したランキングビュー**として表示する。

| ランキング | データソース | 表示内容 |
|-----------|------------|---------|
| **Daily ★** | `github.com/trending?since=daily` | 直近1日のスター増加数で注目されているリポ |
| **Weekly ★** | `github.com/trending?since=weekly` | 直近1週間のスター増加数で注目されているリポ |
| **Monthly ★** | `github.com/trending?since=monthly` | 直近1ヶ月のスター増加数で注目されているリポ |
| **Total ★** | GitHub REST API | 全期間の累計スター数順（全リポ統合） |

---

## 収集フロー

```
1. Trending ページスクレイピング（3期間を直列・リトライ付き）
   └─ daily → 10秒待機 → weekly → 10秒待機 → monthly

2. キーワードフィルタリング（AI/LLM 関連のみ抽出）
   └─ 10件未満の場合は非マッチリポジトリから補填

3. 各期間上限10件に絞り込み

4. URL をキーに3期間のデータをマージ

5. GitHub REST API で正確な総スター数を取得（直列・リトライ付き）

6. スマート再収集判定（過去データの再利用 or 新規要約生成）

7. JSON 保存 → LLM 要約 → ダイジェスト統合
```

### 信頼性の仕組み

arXiv 収集と同様に、確実なデータ取得を優先した設計:

- **単一 httpx クライアント**で全リクエストを直列実行
- **ページ間待機**: 10秒（`_INTER_PAGE_DELAY`）
- **API 間待機**: 2秒（`_INTER_API_DELAY`）
- **リトライ**: 最大3回、429/5xx 時は指数バックオフ + `Retry-After` ヘッダー対応
- **GitHub API レートリミット**: 403 時は60秒待機、`GITHUB_TOKEN` 設定で 60→5000 req/h に緩和

---

## 設定

### 環境変数

| 変数名 | デフォルト | 変更必要度 | 説明 |
|--------|-----------|-----------|------|
| `GITHUB_TOKEN` | (空) | 任意 | GitHub Personal Access Token。設定するとレートリミットが 60→5000 req/h に緩和される。[Settings > Developer settings > Personal access tokens](https://github.com/settings/tokens) で発行（スコープ不要、public repo の読み取りのみ） |

### `app/config.py` の設定値

| 設定 | デフォルト | 説明 |
|------|-----------|------|
| `github_trending_max_results` | `10` | 各期間あたりの取得上限（各タブ10件表示） |
| `github_trending_stale_days` | `30` | スマート再収集の閾値（日数）。この日数以内に調査済みで description 変更なしなら前回のカードを再利用する |
| `github_trending_keywords` | AI, LLM, ML, ... | デフォルトのフィルタキーワード一覧（約30語） |

### キーワードフィルタのカスタマイズ

フィルタキーワードは**2つの方法**で変更できる:

#### 1. Web UI から変更（推奨）

GitHub Trending セクションの **⚙️ フィルタ設定** ボタンからキーワードの追加・削除ができる。変更は `data/github_trending_keywords.json` に即座に保存される。

#### 2. JSON ファイルを直接編集

```bash
# data/github_trending_keywords.json を作成または編集
cat data/github_trending_keywords.json
```

```json
[
  "AI", "LLM", "ML", "deep learning", "machine learning",
  "GPT", "transformer", "neural", "NLP", "agent",
  "RAG", "diffusion", "fine-tuning", "inference", "embedding"
]
```

JSON ファイルが存在する場合はそちらが優先され、存在しない場合は `config.py` のデフォルト値が使われる。

---

## スマート再収集

毎日のトレンドには同じリポジトリが繰り返し登場する。要約の重複生成を避けるため、**スマート再収集**で過去のカードを再利用する。

### 判定ロジック

```
リポジトリの URL をキーに github_trending_index.json を参照
  ├─ 初出 → 新規要約生成
  ├─ description が変更 → 新規要約生成
  ├─ 最終調査から 30日以上経過 → 新規要約生成
  └─ 上記以外 → 前回のカードを再利用（reused_from タグ付与）
```

### インデックスファイル

`data/github_trending_index.json` に各リポジトリの調査状況を記録:

```json
{
  "repos": {
    "https://github.com/owner/repo": {
      "last_seen_date": "2026-04-01",
      "last_surveyed_date": "2026-03-28",
      "description_hash": "a1b2c3d4e5f6g7h8"
    }
  }
}
```

---

## 表示仕様

### ランキングタブ

GitHub Trending セクションには Daily / Weekly / Monthly / Total の4つのタブがあり、Alpine.js で切り替える。各タブは独立したランキングで、**そのタブに該当するリポジトリのみ**が表示される。

### カード表示

各カードには以下の情報が表示される:

- **ランキング順位** (`#1`, `#2`, ...)
- **該当期間のスター増加数** — 表示中のタブに対応する期間のスター数のみ（例: Daily タブなら `★ N today`）
- **累計スター数** — GitHub API から取得した正確な値（全タブ共通で表示）
- **初回調査日** — スマート再収集で再利用された場合、元の調査日を表示

> 各期間のスター増加数はその期間のトレンドページに掲載されたリポジトリでのみ取得可能なため、タブに応じた値だけを表示する設計にしている。

### データの保存形式

ランキング情報は `ArticleItem.tags` フィールドに以下の規約で格納:

| タグ形式 | 例 | 説明 |
|---------|-----|------|
| `ranking:{period}` | `ranking:daily` | そのリポがどの期間のトレンドページに掲載されていたか |
| `stars_{period}:{count}` | `stars_daily:1234` | 各期間のスター増加数 |
| `rank_{period}:{position}` | `rank_daily:3` | 各期間でのランキング順位 |
| `reused_from:{date}` | `reused_from:2026-03-28` | スマート再収集で再利用された元の調査日 |

---

## 管理エンドポイント

| メソッド | エンドポイント | 説明 |
|---------|--------------|------|
| GET | `/admin/github-trending-keywords` | 現在のフィルタキーワード一覧を取得 |
| POST | `/admin/github-trending-keywords?keyword=xxx` | キーワードを追加 |
| DELETE | `/admin/github-trending-keywords/{keyword}` | キーワードを削除 |

HTMX リクエスト（`hx-request` ヘッダー付き）の場合は HTML フラグメントを返し、通常リクエストの場合は JSON を返す。

---

## 関連ファイル

| ファイル | 役割 |
|---------|------|
| `app/services/collector/github_trending.py` | 収集ロジック本体（スクレイピング・API・マージ・再収集） |
| `app/config.py` | `github_token`, `github_trending_*` 設定 |
| `app/routers/archive.py` | ランキングソート・フィルタ（`_sort_gt_items`） |
| `app/templates/components/article/github_trending_section.html` | セクション UI（タブ・キーワード管理） |
| `app/templates/components/article/card.html` | カード内のスター表示ロジック |
| `app/main.py` | キーワード管理エンドポイント |
| `data/github_trending_index.json` | スマート再収集インデックス |
| `data/github_trending_keywords.json` | カスタムフィルタキーワード |
