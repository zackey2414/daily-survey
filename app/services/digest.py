"""
日次一面まとめ（ダイジェスト）生成モジュール
全カテゴリのデータを元に Gemini で 2000文字のサマリーを生成し
Markdown ファイルとして保存する
プロンプトテンプレートは prompts/digest.md から読み込む
"""

import logging
import re
from pathlib import Path

import google.generativeai as genai

from app.config import settings
from app.schemas import ArticleItem

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

genai.configure(api_key=settings.gemini_api_key)

CITATION_RE = re.compile(r"\[ref:([a-z0-9_\-]+(?:,\s*ref:[a-z0-9_\-]+)*)\]")


def _get_model() -> genai.GenerativeModel:
    return genai.GenerativeModel(settings.gemini_summary_model)


def inject_citations(text: str, date_str: str, is_archive: bool) -> str:
    """[ref:safe_id] や [ref:id1, ref:id2] をMarkdownリンクに変換する"""

    def _make_link(safe_id: str) -> str:
        if is_archive:
            href = f"#article-{safe_id}"
        else:
            href = f"/archive/{date_str}#article-{safe_id}"
        return f"[↗]({href})"

    def replace(m: re.Match) -> str:
        ids = re.split(r",\s*ref:", m.group(1))
        return " ".join(_make_link(sid) for sid in ids)

    return CITATION_RE.sub(replace, text)


async def generate_digest(
    date_str: str,
    cv_papers: list[ArticleItem],
    lg_papers: list[ArticleItem],
    ai_papers: list[ArticleItem],
    cl_papers: list[ArticleItem],
    industry_news: list[ArticleItem],
    community_items: list[ArticleItem],
    github_trending_items: list[ArticleItem],
    ai_dev_items: list[ArticleItem] | None = None,
    *,
    target_date_str: str | None = None,
) -> str:
    """
    全カテゴリのデータを受け取り、日本語ダイジェストを生成して
    Markdown ファイルに保存する。保存パスを返す。
    """
    import asyncio

    # 要約コンテキストを構築
    context = _build_context(
        cv_papers,
        lg_papers,
        ai_papers,
        cl_papers,
        industry_news,
        community_items,
        github_trending_items,
        ai_dev_items or [],
    )

    coverage_date = target_date_str or date_str

    # テンプレート読み込み
    template_path = _PROMPTS_DIR / "digest.md"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        logger.warning(f"ダイジェストテンプレートが見つかりません: {template_path}")
        template = (
            "以下は {coverage_date} の AI 関連の最新情報です。\n"
            "日本語のサマリーを Markdown 形式で作成してください。\n\n"
            "## 収集情報\n{context}"
        )
    prompt = template.format(coverage_date=coverage_date, context=context)

    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _get_model().generate_content(prompt).text
        )
    except Exception as e:
        logger.error(f"ダイジェスト生成失敗: {e}")
        result = f"# {date_str} AI 動向まとめ\n\nダイジェストの生成に失敗しました。\n\nエラー: {e}"

    # Markdown ファイルに保存
    save_path = _save_digest(date_str, result)
    logger.info(f"ダイジェスト保存完了: {save_path}")
    return save_path


def _build_context(
    cv_papers: list[ArticleItem],
    lg_papers: list[ArticleItem],
    ai_papers: list[ArticleItem],
    cl_papers: list[ArticleItem],
    industry_news: list[ArticleItem],
    community_items: list[ArticleItem],
    github_trending_items: list[ArticleItem],
    ai_dev_items: list[ArticleItem] | None = None,
) -> str:
    sections = []

    def add_section(
        title: str, items: list[ArticleItem], is_paper: bool = True
    ) -> None:
        if not items:
            return
        lines = [f"### {title} ({len(items)} 件)"]
        for item in items[:5]:  # コンテキスト長削減のため上位5件
            t = item.title_ja or item.title_en
            s = item.summary_ja or item.abstract_en[:200]
            safe_id = item.id.replace(":", "-").replace("/", "-").replace(".", "-")
            lines.append(f"- [ref:{safe_id}] **{t}**: {s[:150]}")
        sections.append("\n".join(lines))

    add_section("CV 論文 (cs.CV)", cv_papers)
    add_section("機械学習論文 (cs.LG)", lg_papers)
    add_section("AI 論文 (cs.AI)", ai_papers)
    add_section("自然言語処理論文 (cs.CL)", cl_papers)
    add_section("AI 企業動向", industry_news, is_paper=False)
    add_section("SNS・コミュニティ", community_items, is_paper=False)
    add_section("GitHub Trending", github_trending_items, is_paper=False)
    add_section("LLM・AIエージェント動向", ai_dev_items or [], is_paper=False)

    return "\n\n".join(sections)


def _save_digest(date_str: str, content: str) -> str:
    summaries_dir = settings.summaries_dir
    summaries_dir.mkdir(parents=True, exist_ok=True)
    file_path = summaries_dir / f"{date_str}.md"
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)


def load_digest(date_str: str) -> str | None:
    """保存済みダイジェストを読み込む"""
    file_path = settings.summaries_dir / f"{date_str}.md"
    if not file_path.exists():
        return None
    return file_path.read_text(encoding="utf-8")


def list_digests() -> list[str]:
    """保存済みダイジェストの日付一覧（降順）を返す"""
    summaries_dir = settings.summaries_dir
    if not summaries_dir.exists():
        return []
    dates = sorted(
        [f.stem for f in summaries_dir.glob("*.md") if f.stem.count("-") == 2],
        reverse=True,
    )
    return dates
