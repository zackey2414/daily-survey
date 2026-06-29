# 要件定義書: AI Daily Survey Web Application

**バージョン**: 1.1
**作成日**: 2026-03-03
**最終更新**: 2026-06-09
**ステータス**: 実装反映済み

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

毎朝 JST 12:00 に自動実行し、前日1日に公開された AI 関連の論文・記事・サービス情報を収集・要約して、1ページで最新の AI 動向をチェックできる個人向け Web アプリケーションを構築する。（実行時刻は `SCHEDULE_HOUR`/`SCHEDULE_MINUTE` で変更可。arXiv の索引反映待ちのため既定は正午）

### 1.2 対象ユーザー

開発者本人のみ（リモートサーバに SSH トンネルでアクセス）。認証機構の実装は不要。

### 1.3 収集対象カテゴリと表示順

| 優先順 | カテゴリ | 概要 |
|--------|----------|------|
| 1 | **CV論文** | arXiv `cs.CV` + OpenReview 対象学会 |
| 2 | **AI全般論文** | arXiv `cs.LG` / `cs.AI` / `cs.CL` |
| 3 | **AI企業動向** | OpenAI, Google, Anthropic, Meta, Amazon, Alibaba |
| 4 | **AI企業動向（その他報道）** | BBC, TechCrunch, The Verge, Wired 等の海外ニュース |
| 5 | **SNS・コミュニティ** | Qiita, Zenn, Reddit |
| 6 | **GitHub Trending** | GitHub Trending（Daily / Weekly / Monthly）スクレイピング |
| 7 | **LLM・AIエージェント動向** | LLM・AI エージェントの公式アップデート・性能ニュース（ai_dev） |

> 上表は**収集**カテゴリ。トップページの**表示**では、CV論文（cs.CV + OpenReview）を独立セクションとして出さず「テーマ別論文」（設定テーマごとのサブトグル）に置き換え、LLM・AIエージェント動向を AI企業動向の上に配置する（実際の表示順は 3.3.1 を参照）。

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
| フロントエンド | **Jinja2 + HTMX + Alpine.js** | Python ベースのテンプレート + 軽量インタラクション |
| CSS フレームワーク | **Tailwind CSS** | CDN 経由（Play CDN） |
| データベース | **SQLite** | チャット履歴のみ |
| データ保存 | **JSON ファイル** | 日次収集データ（再利用性重視） |
| サマリー保存 | **Markdown ファイル** | 日次一面まとめ |
| LLM API | **Google Gemini API** | 個別記事要約・チャット: `gemini-3.1-flash-lite`、一面まとめ生成: `gemini-3-flash-preview`。チャットは Google Search グラウンディング付き |
| スケジューラ | **APScheduler**（FastAPI 組み込み）または **cron**（Docker 内） | JST 12:00 実行（既定。`SCHEDULE_HOUR` / `SCHEDULE_MINUTE` で変更可。arXiv 索引反映待ちのため正午） |
| 通知 | SMTP（メール） | 収集完了時 |

### 2.3 Gemini API モデル選定方針

| 用途 | モデル | 設定変数 | 理由 |
|------|--------|----------|------|
| 個別記事・論文の要約 | `gemini-3.1-flash-lite` | `GEMINI_CHAT_MODEL` | 件数が多く高速処理を優先 |
| 一面まとめ生成（日次ダイジェスト） | `gemini-3-flash-preview` | `GEMINI_SUMMARY_MODEL` | 全体を見渡す高品質な要約が必要 |
| チャット応答 | `gemini-3.1-flash-lite` | `GEMINI_CHAT_MODEL` | 対話的応答はコスト・速度を優先。Google Search グラウンディング付き |

- モデル名は設定ファイル（`.env`）で個別に切り替え可能
- 全ての Gemini 呼び出し（要約・ダイジェスト・テーマキーワード生成・チャット）は `google-genai` SDK（`from google import genai` / `genai.Client`）を使用する
- チャット応答では、RAG コンテキストで不足する場合に Gemini が自動で Google 検索を実行する

---

## 3. 機能要件

### 3.1 データ収集機能

#### 3.1.1 収集全体仕様

- **実行タイミング**: 毎日 JST 12:00（既定。`SCHEDULE_HOUR`/`SCHEDULE_MINUTE` で変更可）
- **収集期間**: 前日 00:00〜23:59 JST に公開・更新されたもの
- **上限件数**: カテゴリ・ソースごとに異なる（arXiv 各カテゴリ20件/日、OpenReview 全学会合計20件/日、企業動向 各社5件/日（合計最大30件）、その他報道 合計15件/日、コミュニティ 全ソース合計20件/日、GitHub Trending 各期間10件、ai_dev 公式フィード各ソース5件・ニュース合計15件）
- **出力形式**: JSON ファイル（`data/YYYY-MM-DD/` ディレクトリ以下）

#### 3.1.2 CV 論文収集（`cs.CV`）

**ソース1: arXiv**
- API: arXiv API (`https://export.arxiv.org/api/query`)
- カテゴリ: `cs.CV`
- 取得フィールド: タイトル, 著者, アブストラクト, arXiv ID, 公開日, PDF URL
- 上限: 20件/日

**ソース2: OpenReview**
- API: OpenReview API v2 (`https://api2.openreview.net`)
- 対象学会: NeurIPS, ICLR, ICML, CVPR, ICCV, ECCV（OpenReview API v2 の invitation で絞り込み）
  - NeurIPS / ICLR / ICML は OpenReview 上に投稿が公開されており取得可能
  - CVPR / ICCV / ECCV は CV の主要学会だが現状は投稿が非公開のため、将来公開時に備えて invitation テンプレートのみ定義（取得は 0 件）
  - AAAI / ACL / EMNLP / IJCAI および WACV/ICIP/BMVC 等は OpenReview に公開投稿が無く常に 0 件のため対象外（コード未定義）
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
| Anthropic | `https://news.google.com/rss/search?q=site:anthropic.com&hl=en-US&gl=US&ceid=US:en`（公式 RSS `anthropic.com/rss.xml` は廃止＝404 のため Google News RSS で代替） |
| Meta | Meta Engineering ブログ RSS (`https://engineering.fb.com/feed/`)（Meta AI ブログ ai.meta.com/blog/rss が 404 化したため差し替え） |
| Amazon AWS AI | `https://aws.amazon.com/blogs/machine-learning/feed/`（AWS Machine Learning Blog RSS） |
| Alibaba / DAMO Academy | `https://www.alibabacloud.com/blog/feed/tag/ai` |

- 取得フィールド: タイトル, 公開日, 概要, URL
- 上限: 各社 5件/日（合計最大 30件）

#### 3.1.5 AI 企業動向収集（その他報道）

- ソース: 海外大手ニュースサイトの RSS フィード
- 対象メディア:

| メディア | ソース |
|---------|--------|
| BBC | BBC Technology RSS |
| TechCrunch | TechCrunch AI RSS |
| The Verge | The Verge RSS |
| Wired | Wired RSS |

- AI 関連キーワードでフィルタリング
- 取得フィールド: タイトル, 公開日, 概要, URL
- 上限: 合計最大 15件/日

#### 3.1.6 SNS・コミュニティ収集

**Qiita**
- API: Qiita API v2 (`https://qiita.com/api/v2/items`)
- 絞り込み: `tag:AI`, `tag:機械学習`, `tag:LLM` 等のトレンド記事
- 上限: 20件/日

**Zenn**
- ソース: Zenn RSS フィード（API 非公開のため RSS 使用）
- `https://zenn.dev/topics/機械学習/feed`  等
- 上限: 20件/日

**Reddit**
- API: Reddit 公開 JSON API（praw 不使用・httpx で直接取得）。エンドポイントは `https://www.reddit.com/r/{sub}/new.json?limit=25`
- 対象サブレディット: `r/MachineLearning`, `r/artificial`, `r/LocalLLaMA`
- 上限: Reddit は全サブレディット横断で合計 10件/日（サブレディットごとの個別上限なし）。さらにコミュニティ全ソース（Qiita / Zenn / Reddit）合計で 20件（`community_max_results`）に制限

#### 3.1.7 GitHub Trending 収集

- ソース: GitHub Trending（全言語、HTML スクレイピング `BeautifulSoup`） + GitHub REST API（正確なスター数取得）
- 期間: daily / weekly / monthly の3期間を収集
- フィルタ: AI/ML 関連キーワード（`github_trending_keywords`）でフィルタリング（不足時は非マッチ・他期間から補填）
- 上限: 各期間 10件（`github_trending_max_results`）
- スマート再収集: 過去調査済みリポジトリは 30日（`github_trending_stale_days`）以内なら前回カードを再利用
- 出力: `papers_github_trending.json`

#### 3.1.8 LLM・AIエージェント動向収集（`ai_dev` カテゴリ）

- Pass A（公式アップデート）: コーディングAI ツール・LLM ベンダーの公式 RSS（`ai_dev_rss_feeds`、7ソース: Claude Code / OpenAI Codex / Cursor / GitHub Copilot / Mistral / Hugging Face / Google DeepMind）。1ソースあたり上限5件（`ai_dev_max_per_source`）、プレリリースは除外
- Pass B（ニュース）: 実務寄りニュース源 RSS（`ai_dev_news_feeds`、3ソース: Simon Willison / VentureBeat AI / Import AI）を `ai_dev_filter_keywords` でフィルタ。上限15件（`ai_dev_news_max_results`）
- 前日（JST）公開分のみ対象。`id` で重複除去（公式優先）
- 出力: `papers_ai_dev.json`

> 旧「Python 情報収集」（PyPI RSS / Python.org RSS）は現行パイプラインで稼働していない（`collect_python_news` は実装は残るが `pipeline.py` から import されない）。

---

### 3.2 要約・LLM 処理機能

#### 3.2.1 個別記事の要約

- 使用モデル: Gemini API（`gemini-3.1-flash-lite`）— 件数が多く高速処理を優先
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
- コミュニティ・GitHub Trending 記事の場合に含める内容（`article` 要約）:
  - 概要（何が発表・議論されているか）
  - ポイント（3点）
  - 元記事リンク
- LLM・AIエージェント動向（ai_dev）・企業動向その他報道（industry_news）の場合に含める内容（`industry` 要約）:
  - 概要（何が発表されたか）
  - ポイント（3点）
  - **定量指標**（ベンチマーク名・スコア・従来手法比など）
  - 元記事リンク

#### 3.2.2 一面まとめ生成（新聞一面）

- トリガー: 全カテゴリの収集・要約完了後に自動生成
- 使用モデル: Gemini API（`gemini-3-flash-preview`）— 全カテゴリを俯瞰する高品質な要約が必要
- 入力: 全カテゴリの要約データ（JSON）
- 出力形式: **Markdown**（`summaries/YYYY-MM-DD.md`）
- 出力内容:
  - 日付とタイトル
  - 本日の主要トピック（ハイライト）
  - 各カテゴリの注目情報（2〜3点ずつ）
  - 全体的な AI 動向の所感
- 文字数: 最大 2000文字
- 表示言語: 日本語

#### 3.2.3 一面まとめ 英語版（英語多読）

- 目的: 一面の内容理解ではなく、**英文を読む・理解すること自体を目的**とした英語学習用コンテンツ。
- トリガー: 日次パイプラインで日本語ダイジェスト生成後に自動生成（best-effort。失敗してもパイプラインは継続）。過去日は `/admin/generate-english` でオンデマンド生成可。
- 使用モデル: Gemini API（`gemini-3.1-flash-lite`）— コスト最小化のため安価な flash-lite を使用。LLM 呼び出しは **1日1回のみ**、入力は候補を「タイトル＋短縮要約」に絞る。文章生成以外（候補整形・JSON 検証・保存・描画）はすべてプログラムで実装する。
- 入力: その日の収集データ（論文を優先した候補リスト）。
- 処理: 候補から**その日の最重要トピック1本**を選び、有名論文のような明瞭な学術英語（約 350〜500 語、3〜5 分で読了）に書き起こす。各文に全訳（文単位）とチャンク単位（意味のまとまり）の語義を付与する。
- 出力形式: **構造化 JSON**（`summaries/YYYY-MM-DD.en.json`、スキーマは `EnglishDigest`）。引用リンク（`[ref:]`）は付けない。
- 表示: `/archive/YYYY-MM-DD/en`。英文は通しで読め、**赤シート式（既定は非表示・触れると表示）**で語義・全訳を確認できる。一面まとめヘッダー右上の「英語版 →」から遷移。語義・全訳はそれぞれ一括表示トグルあり。
- 音声（リスニング）: 英文全体を **ローカル TTS（Kokoro-82M / `kokoro-onnx`, API 不使用＝課金なし）** で mp3 に合成し、`summaries/YYYY-MM-DD.en.mp3` に保存。ページ上部に MP3 プレーヤーを表示する。生成は**バックグラウンド非同期**（日次パイプライン後に自動 + ページの「音声を生成」ボタンでオンデマンド）。配信は `GET /archive/YYYY-MM-DD/en/audio`。モデルは `models/` に初回自動ダウンロードしてキャッシュ（音素化 espeak-ng は `espeakng-loader` がバンドル、mp3 化は `soundfile` 同梱 libsndfile で行うため OS への追加インストール不要）。

---

### 3.3 Web アプリケーション機能

#### 3.3.1 メインページ（今日の一面）

- URL: `/` または `/today`
- 表示内容（上から順に）:
  1. 一面まとめセクション（Markdown レンダリング）
  2. テーマ別論文セクション（設定テーマごとのサブトグル。その日のテーマ検索結果。0 件のテーマは非表示）
  3. AI 全般論文セクション（cs.LG / cs.AI / cs.CL 各サブセクション）
  4. LLM・AIエージェント動向（ai_dev）セクション
  5. AI 企業動向セクション（自社発表 / その他報道 各サブセクション）
  6. SNS・コミュニティセクション（Qiita / Zenn / Reddit）
  7. GitHub Trending セクション

> 旧「CV 関連論文」セクション（cs.CV + OpenReview）はトップ表示から廃止し、テーマ別論文に置き換えた。cs.CV / OpenReview の収集は継続し、テーマにマッチした論文はテーマ別論文に現れる。

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
- チャット応答の参照範囲: 対象記事の全文・要約データ（RAG コンテキストとして Gemini API に渡す）
- **Google Search グラウンディング**: RAG コンテキストだけでは回答できない質問に対して、Gemini が自動で Google 検索を実行し、検索結果を根拠に回答を生成する
  - 検索が使われた場合、回答にインライン引用 `[1][2]` が付与され、ソースリンクが折りたたみ表示される
  - `GEMINI_SEARCH_THRESHOLD` 環境変数で検索頻度を制御可能
- チャットタイトル: 初回メッセージをもとに **LLM が自動生成**（最大 30文字程度）
- チャット履歴の保存: **SQLite**（後述のデータモデル参照）
- セッションをまたいでも続きから回答可能

**チャット検索機能**
- URL: `/chat/search`
- 全チャット一覧表示
- キーワード検索（タイトル・本文対象）
- 記事タイトルでフィルタリング

#### 3.3.3 タグ機能

- **AI 生成タグ**: LLM が要約時に生成する `hashtags` フィールドのタグ
- **ユーザータグ**: ユーザーが手動で記事に付与するタグ（追加・削除可能）
- タグ一覧ページ（`/tags/`）:
  - AI 生成タグとユーザータグを別セクションで表示
  - タグクラウド形式（出現回数に応じてサイズ・色の濃さが変化）
- タグ別記事ページ（`/tags/{tag_name}`）:
  - 指定タグを持つ記事を全期間・全カテゴリから横断検索
- ユーザータグの保存: **SQLite**（`user_tags` テーブル）

#### 3.3.3.1 お気に入り機能

- 各記事カードの ★ ボタンで、記事をお気に入り登録/解除（トグル、HTMX）
- お気に入りページ（`/favorites/`）:
  - 登録した記事を全期間・全カテゴリ（テーマ別論文を含む）から横断表示
  - タグ別記事ページと同じカテゴリ別レイアウト
- お気に入りの保存: **SQLite**（`favorites` テーブル、`article_id` でユニーク）

#### 3.3.4 日次サマリーフィードページ

- URL: `/summaries?page=N`
- 全一面まとめを**日付降順**で表示（最新が先頭）
- **ページネーション**: 1ページ10件、`?page=N` クエリで切り替え
- 各カードにタイトル・冒頭プレビュー（200文字）・「続きを読む」リンクを表示
- 各日付のカードをクリックすると、その日のまとめページに遷移（`/summaries/YYYY-MM-DD`）
- サマリーは Markdown ファイルをレンダリングして表示

#### 3.3.5 過去日付の記事ページ

- URL: `/archive/YYYY-MM-DD`
- 特定日の全収集データを表示（JSON から読み込み）
- メインページと同じレイアウト

#### 3.3.6 検索テーマ機能

- URL: `/themes`, `/themes/{theme_id}`, `/admin/themes/*`
- 任意のカスタムキーワード群（テーマ）を登録し、日付を横断して該当論文・記事を収集・表示する
- **キーワード自動生成**: テーマ名から Gemini（`GEMINI_CHAT_MODEL`）が関連キーワード（同義語・略語・関連技術用語）を生成。生成後に手動で追加・削除可能
- **毎日自動収集**: 有効化したテーマは日次パイプライン内で「全ソース横断」検索され、結果を `data/{date}/themes/{theme_id}.json` に蓄積
- **総括要約**: 日次パイプラインで全テーマの収集論文を俯瞰する総括を LLM 生成し `data/{date}/theme_overview.md` に保存。トップ/アーカイブの「テーマ別論文」親トグルを開いた最上部に表示（引用リンク付き）
- **ハイブリッド検索**: arXiv は専用の全文検索クエリ、その他ソースは当日収集済みアイテムを単語境界マッチでフィルタ
- **オンデマンド検索**: 収集日範囲（最大31日）を指定してその場で過去日付の検索を実行
- 上限: 有効テーマ・キーワードともに最大 20（`MAX_THEMES` / `MAX_KEYWORDS`）。登録テーマは `data/themes.json` に永続化
- デフォルトテーマ（初回起動時に投入）: 「画像検索」「物体中心画像検索」「エッジクラウド協調AI」（`config.py` の `default_themes`）

#### 3.3.7 一面まとめチャット（日次チャット）

- URL: `/daily-chat/{date}/*`
- その日の全カテゴリ記事の要約を結合した RAG コンテキストを根拠に、複数記事を横断して質問できる日次チャット
- `article_id` が NULL の `ChatSession` として SQLite に保存（記事チャットと区別）。Google Search グラウンディング付き、初回メッセージからタイトルを自動生成
- トップ/アーカイブページの「💬 今日のチャット」ボタンから開く

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
│  [今日] [まとめ] [タグ] [テーマ] [★お気に入り] [チャット履歴] │
├──────────────────────────────────────────────────────┤
│ ▼ 本日の一面まとめ                                    │
│  ─────────────────────────────────────────────────── │
│  （Markdown レンダリング / 2000文字以内）              │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ テーマ別論文（設定テーマごとにサブトグル）           │
│   ▼ テーマA（その日のテーマ検索結果）        [N件]   │
│   ▼ テーマB                                  [M件]   │
│   （0件のテーマは非表示。/themes で管理）             │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ AI 全般論文                                        │
│   ▼ cs.LG（機械学習）                       [20件]   │
│   ▼ cs.AI（人工知能）                       [20件]   │
│   ▼ cs.CL（自然言語処理）                   [20件]   │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ LLM・AIエージェント動向                             │
│   公式アップデート + 性能・ベンチマークニュース        │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ AI 企業動向                                        │
│   ▼ 自社発表    OpenAI / Google / Anthropic /        │
│                 Meta / Amazon / Alibaba              │
│   ▼ その他報道  BBC / TechCrunch / The Verge / Wired │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ SNS・コミュニティ                                   │
│   Qiita / Zenn / Reddit                              │
│                                                      │
├──────────────────────────────────────────────────────┤
│ ▼ GitHub Trending                                    │
│   日次 / 週次 / 月次 / 累計（スター数降順タブ）         │
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
  "collected_at": "2026-03-03T12:00:00+09:00",
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
      "meta_learning_ja": "メタ的な学び（問題定式化・手法・評価の観点）...",
      "key_points_ja": ["ポイント1", "ポイント2", "ポイント3"],
      "quantitative_metrics_ja": "定量指標（ベンチマーク名・スコア・改善率など）...",
      "published_date": "2026-03-02",
      "url": "https://arxiv.org/abs/2603.12345",
      "pdf_url": "https://arxiv.org/pdf/2603.12345",
      "source_type": "arxiv",
      "source_name": "arXiv",
      "tags": ["cs.CV"],
      "hashtags": ["深層学習", "物体検出"],
      "summarized": true
    }
  ]
}
```

**ファイル一覧（1日分）**:
```
data/YYYY-MM-DD/
├── papers_cv.json              # cs.CV（arXiv）
├── papers_openreview.json      # OpenReview（6学会）
├── papers_lg.json              # cs.LG
├── papers_ai.json              # cs.AI
├── papers_cl.json              # cs.CL
├── papers_industry.json        # 企業動向（自社発表）
├── papers_industry_news.json   # 企業動向（その他報道）
├── papers_community.json       # SNS・コミュニティ
├── papers_github_trending.json # GitHub Trending
└── papers_ai_dev.json          # LLM・AIエージェント動向
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
    category    TEXT NOT NULL,      -- "cv", "openreview", "lg", "ai", "cl", "industry", "industry_news", "community", "github_trending", "ai_dev"
    title_ja    TEXT NOT NULL,
    url         TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- チャットセッションテーブル
CREATE TABLE chat_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT REFERENCES articles(id),  -- NULLABLE: 記事チャットでセット
    date        VARCHAR(10),                    -- 日毎チャット（一面まとめ）用: "YYYY-MM-DD"
    title       TEXT NOT NULL DEFAULT '新しいチャット',  -- LLM が自動生成
    rag_context TEXT,               -- キャッシュされた RAG コンテキスト
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- article_id がセットされていれば記事チャット、article_id IS NULL かつ date NOT NULL なら日毎チャット（is_daily）。
-- SQLite は ALTER COLUMN 不可のため、既存 DB は migrate_db() がテーブルを再作成して article_id の NOT NULL 制約を解除する。

-- チャットメッセージテーブル
CREATE TABLE chat_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES chat_sessions(id),
    role            TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    used_search     BOOLEAN DEFAULT 0,   -- Google Search グラウンディング使用フラグ
    search_sources  TEXT,                 -- 検索ソース JSON ([{"title": "...", "uri": "..."}])
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ユーザータグテーブル（手動付与）
CREATE TABLE user_tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id),
    tag         TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(article_id, tag)
);

-- お気に入りテーブル（1記事につき1件）
CREATE TABLE favorites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  TEXT NOT NULL REFERENCES articles(id),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(article_id)
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
│   ├── main.py                   # FastAPI エントリポイント・lifespan・管理エンドポイント
│   ├── config.py                 # 全設定（Settings クラス、.env 読み込み）
│   ├── schemas.py                # Pydantic モデル（ArticleItem, DailyCollection）
│   ├── jinja.py                  # Jinja2 テンプレートエンジン設定（カスタムフィルタ含む）
│   ├── scheduler.py              # APScheduler（JST 12:00 自動実行）
│   ├── static/                   # 静的ファイル（/static にマウント、js/chat.js）
│   ├── routers/
│   │   ├── main_page.py          # GET / , /today（当日アーカイブへリダイレクト）
│   │   ├── archive.py            # GET /archive/{date_str}（トップページ本体を描画）
│   │   ├── summaries.py          # GET /summaries, /summaries/{date_str}
│   │   ├── chat.py               # 記事チャット API（RAG + Google Search グラウンディング）
│   │   ├── daily_chat.py         # 一面まとめチャット API（/daily-chat/{date_str}/...）
│   │   ├── themes.py             # 検索テーマ管理（GET /themes, /themes/{id}, /admin/themes/* CRUD）
│   │   ├── tags.py               # GET /tags/, /tags/{tag_name}
│   │   ├── user_tags.py          # POST/DELETE /user-tags/{article_id}
│   │   └── favorites.py          # GET /favorites/ , POST /favorites/{article_id}（トグル）
│   ├── services/
│   │   ├── collector/
│   │   │   ├── arxiv.py          # arXiv API（cs.CV / cs.LG / cs.AI / cs.CL）
│   │   │   ├── openreview.py     # OpenReview API v2（NeurIPS/ICLR/ICML/CVPR/ICCV/ECCV の6学会）
│   │   │   ├── industry.py       # 企業公式ブログ RSS（自社発表）
│   │   │   ├── industry_news.py  # 海外ニュースメディア RSS（その他報道）
│   │   │   ├── ai_dev.py         # LLM・AIエージェント動向 RSS（公式アップデート + 性能ニュース）
│   │   │   ├── community.py      # Qiita API / Zenn RSS / Reddit JSON API
│   │   │   ├── github_trending.py # GitHub Trending 全言語 スクレイピング + GitHub API
│   │   │   └── python_news.py    # （現行パイプライン未使用・legacy）
│   │   ├── summarizer.py         # Gemini API 要約処理
│   │   ├── digest.py             # 一面まとめ生成・Markdown 保存
│   │   ├── rag.py                # チャット用 URL フェッチ・RAG コンテキスト構築
│   │   ├── themes.py             # 検索テーマ管理（data/themes.json 永続化・Gemini キーワード自動生成）
│   │   ├── theme_search.py       # 検索テーマのハイブリッド収集（arXiv 全文検索等）
│   │   ├── tasks.py              # fire-and-forget バックグラウンドタスク spawn ユーティリティ
│   │   └── notifier.py           # SMTP メール通知
│   ├── db/
│   │   ├── database.py           # SQLAlchemy async セッション・init_db・migrate_db
│   │   └── models.py             # ORM モデル（Article, ChatSession, ChatMessage, UserTag, Favorite）
│   └── templates/                # Jinja2 テンプレート
│       ├── base.html             # 共通レイアウト（ナビ・スティッキーバー JS）
│       ├── pages/
│       │   ├── index.html
│       │   ├── summaries.html
│       │   ├── summary_detail.html
│       │   ├── tags_list.html
│       │   ├── tags.html
│       │   ├── favorites.html
│       │   ├── chat_search.html
│       │   ├── themes_list.html
│       │   ├── theme_detail.html
│       │   └── error.html
│       └── components/
│           ├── article/          # 記事カード・要約表示・GitHub Trending セクション
│           ├── chat/             # チャットパネル（記事/一面まとめ）・メッセージ
│           ├── tags/             # タグ管理 UI
│           ├── favorite/         # お気に入りスター（HTMX トグル）
│           └── theme/            # テーマ管理 UI（一覧・キーワード編集）
│
├── data/                         # 日次収集 JSON データ（永続化）
│   ├── themes.json               # 登録テーマ（Theme）の永続化
│   ├── github_trending_index.json    # GitHub Trending 調査済みリポジトリのインデックス
│   ├── github_trending_keywords.json # GitHub Trending カスタムキーワード（設定時のみ）
│   └── YYYY-MM-DD/
│       ├── papers_cv.json
│       ├── papers_openreview.json
│       ├── papers_lg.json
│       ├── papers_ai.json
│       ├── papers_cl.json
│       ├── papers_industry.json
│       ├── papers_industry_news.json
│       ├── papers_community.json
│       ├── papers_github_trending.json
│       ├── papers_ai_dev.json
│       └── themes/
│           └── {theme_id}.json    # テーマ別収集結果（ThemeCollection）
│
├── summaries/                    # 日次一面まとめ（Markdown）
│   └── YYYY-MM-DD.md
│
├── db/
│   └── survey.db                 # SQLite データベース
│
├── logs/
│   └── app.log                   # アプリログ
│
└── docs/
    ├── requirements.md           # 要件定義書（本ドキュメント）
    ├── implementation.md         # 実装詳細
    ├── article_format.md         # 記事フォーマット定義
    ├── env.md                    # 環境変数の設定ガイド
    └── github_trending.md        # GitHub Trending 収集機能の詳細
```

---

## 7. 外部API・収集ソース一覧

### 7.1 API キー・認証が必要なもの

| サービス | 認証方式 | 備考 |
|----------|----------|------|
| Google Gemini API | API キー | `.env` に保存 |
| Reddit | 認証不要（公開 JSON API） | `https://www.reddit.com/r/{subreddit}/new.json` を httpx で直接取得。praw は使用していない（pyproject に依存として残るが未使用）。User-Agent ヘッダのみ設定 |
| Qiita API | アクセストークン（任意） | 未認証でも一部利用可能 |

### 7.2 認証不要（RSS / 公開 API）

| サービス | エンドポイント |
|----------|---------------|
| arXiv API | `https://export.arxiv.org/api/query` |
| OpenReview API v2 | `https://api2.openreview.net/notes` |
| Zenn RSS | `https://zenn.dev/topics/{topic}/feed`（machinelearning / deeplearning / llm / ai） |
| PyPI RSS（現行未使用・legacy） | `https://pypi.org/rss/updates.xml`（旧 Python 情報収集用。現行パイプラインでは未使用） |
| 各社公式 RSS | 各社ブログの RSS URL（設定ファイルで管理） |

### 7.3 スクレイピングが必要なもの

| サービス | 備考 |
|----------|------|
| GitHub Trending | 非公式、HTML スクレイピング（`BeautifulSoup`）でトレンド一覧を取得し、各リポジトリの正確な総スター数は GitHub REST API（`https://api.github.com/repos/{owner}/{name}`）で補完。`GITHUB_TOKEN`（任意）でレートリミットを 60→5000 req/h に緩和 |

---

## 8. 非機能要件

### 8.1 スケジューリング

- 実行タイミング: 毎日 JST 12:00（`Asia/Tokyo`、既定。`SCHEDULE_HOUR`/`SCHEDULE_MINUTE` で変更可）
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

*本ドキュメントは要件定義書であり、現行実装の状態を反映している。最終更新: 2026-06-09（実行時刻 12:00 化、Python 情報 → GitHub Trending / LLM・AIエージェント動向、OpenReview 6学会、企業 RSS、Reddit JSON API、テーマ検索・一面まとめチャット、ルート・スキーマを現行コードに整合）。*
