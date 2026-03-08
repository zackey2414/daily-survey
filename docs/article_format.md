# 記事フォーマット定義書

LLM 要約の出力フォーマット仕様。`app/services/summarizer.py` の `_build_prompt()` で使用するプロンプトの構造定義。

使用モデル: **`gemini-2.5-flash`**（個別記事・論文の要約。件数が多く高速処理を優先）
※ 一面まとめ生成（`digest.py`）は **`gemini-2.5-pro`** を使用する。

---

## 1. 論文（arXiv / OpenReview）

`category: "paper"` のアイテムに適用。

```
【日本語タイトル】
（論文タイトルの自然な日本語訳）

【概要】
（何をした研究か、2〜3文で説明）

【新規性・貢献】
（既存研究との違いや本論文の貢献を具体的に説明。
  番号付き箇条書きで主な貢献を列挙し、最後に全体的まとめを1〜2文）

【メタ的な学び】
（論文の内容自体ではなく、以下の観点からメタレベルの学びを2〜3文で記述）
- 問題の定式化の仕方（何を入力・出力とし何を最適化しているか）
- アプローチの独自性（既存手法の組み合わせ方、着眼点）
- 評価手法・指標の選択から学べること

【手法の概要】
（提案手法を簡潔に説明）

【実験結果のポイント】
（主な実験結果や性能向上の数値など）

【タグ】
（スペース区切り、7個程度）
ルール:
1. タスク名を必ず最初に1つ含める（例: 画像検索・物体検知・テキスト分類 等）
2. 技術的固有名詞（モデル名・手法名・データセット名）を必ず含める
3. LLM・VLM・拡散モデル等のカテゴリに該当する場合、モデル名とカテゴリ名を両方含める
例: 画像検索 CLIP マルチモーダル 物体中心 ベンチマーク 自己教師あり学習 ViT
```

### フィールドマッピング（ArticleItem）

| セクション | フィールド |
|---|---|
| 【日本語タイトル】 | `title_ja` |
| 【概要】 | `summary_ja` |
| 【新規性・貢献】 | `novelty_ja` |
| 【メタ的な学び】 | `meta_learning_ja` |
| 【タグ】 | `hashtags` |

---

## 2. AI企業動向記事（RSS: 自社発表・その他報道）

`category: "industry"` のアイテムに適用（`papers_industry.json` / `papers_industry_news.json`）。
pipeline.py では `summarize_items(industry_items, "industry")` として呼び出される。

```
【日本語タイトル】
（タイトルの自然な日本語訳。日本語の場合はそのまま）

【概要】
（何が発表・議論されているか、2〜3文で説明）

【ポイント】
- （重要ポイント1）
- （重要ポイント2）
- （重要ポイント3）

【定量指標】
記事内に性能・技術に関する定量的な数値がある場合は以下の形式で列挙。なければ「なし」。
- ベンチマーク名: スコア（従来手法比 +XX% / 従来: YY → 新: ZZ 等）
例:
- MMLU: 92.3%（GPT-4比 +3.1%）
- 推論速度: 従来比 2.4倍高速化
- コンテキスト長: 1M トークン（従来の8倍）

【タグ】
（スペース区切り、5個程度）
ルール:
1. 内容を表すキーワードを5個程度
2. 技術的固有名詞（モデル名・サービス名・フレームワーク名）を必ず含める
3. LLM・VLM・画像生成等のカテゴリに該当する場合、モデル名とカテゴリ名を両方含める
例: Claude3.5 LLM Anthropic APIリリース マルチモーダル
```

### フィールドマッピング（ArticleItem）

| セクション | フィールド |
|---|---|
| 【日本語タイトル】 | `title_ja` |
| 【概要】 | `summary_ja` |
| 【ポイント】 | `key_points_ja`（リスト） |
| 【定量指標】 | `quantitative_metrics_ja`（文字列、「なし」の場合は空文字） |
| 【タグ】 | `hashtags` |

---

## 3. Web記事（RSS / Qiita / Zenn / Reddit）

`category: "article"` のアイテムに適用（コミュニティ記事・Python 情報）。

```
【日本語タイトル】
（タイトルの自然な日本語訳。日本語の場合はそのまま）

【概要】
（何が発表・議論されているか、2〜3文で説明）

【ポイント】
- （重要ポイント1）
- （重要ポイント2）
- （重要ポイント3）

【タグ】
（スペース区切り、5個程度）
ルール:
1. 内容を表すキーワードを5個程度
2. 技術的固有名詞（モデル名・サービス名・フレームワーク名）を必ず含める
3. LLM・VLM・画像生成等のカテゴリに該当する場合、モデル名とカテゴリ名を両方含める
例: Claude3.5 LLM Anthropic APIリリース マルチモーダル
```

### フィールドマッピング（ArticleItem）

| セクション | フィールド |
|---|---|
| 【日本語タイトル】 | `title_ja` |
| 【概要】 | `summary_ja` |
| 【ポイント】 | `key_points_ja`（リスト） |
| 【タグ】 | `hashtags` |

---

## 4. GitHub Trending

`source_type: "github_trending"` のアイテムに適用（Python 情報）。
記事フォーマットと同じプロンプトを使用するが、ポイントは2箇条を目安とする。

```
【日本語タイトル】
（リポジトリ名と用途の自然な日本語表現）

【概要】
（何のリポジトリか、用途を1〜2文で説明）

【ポイント】
- （特徴・用途ポイント1）
- （特徴・用途ポイント2）

【タグ】
（スペース区切り、5個程度）
```

### フィールドマッピング（ArticleItem）

論文フォーマットと同じ（`key_points_ja` に格納）。

---

## 注意事項

- 各セクションは `【見出し】` 形式で必ず出力すること（Markdown の `###` や `**` で装飾されていても `_parse_result()` が正規表現で対応）
- タグは `#` プレフィックスなしでスペース区切り（パーサーが自動で `#` を除去）
- `meta_learning_ja` は論文（`category="paper"`）のみに出力し、記事・GitHub Trending には出力しない
- `quantitative_metrics_ja` は企業動向（`category="industry"`）のみに出力し、数値がない場合は「なし」と出力（パーサーが自動で空文字に変換）

## カテゴリと summarize_items 呼び出しの対応

| JSON ファイル | pipeline.py 呼び出し | プロンプト種別 |
|---|---|---|
| `papers_cv.json` | `summarize_items(items, "paper")` | 論文 |
| `papers_openreview.json` | `summarize_items(items, "paper")` | 論文 |
| `papers_lg/ai/cl.json` | `summarize_items(items, "paper")` | 論文 |
| `papers_industry.json` | `summarize_items(items, "industry")` | 企業動向（定量指標あり） |
| `papers_industry_news.json` | `summarize_items(items, "industry")` | 企業動向（定量指標あり） |
| `papers_community.json` | `summarize_items(items, "article")` | 記事 |
| `papers_python.json` | `summarize_items(items, "article")` | 記事 |
