"""テーマ別論文の総括（theme_overview）の LLM 非依存部分のテスト。

コンテキスト構築・保存/読込を検証する（LLM 生成自体は実 API を要するため対象外）。
"""

from app.schemas import ArticleItem, ThemeCollection
from app.services import theme_search as ts


def _tc(name: str, items: list[ArticleItem]) -> ThemeCollection:
    return ThemeCollection(
        theme_id="t-" + name,
        theme_name=name,
        date="2026-06-09",
        collection_date="2026-06-10",
        items=items,
    )


def test_build_overview_context_includes_ref_and_skips_empty():
    item = ArticleItem(
        id="arxiv:2606.12345v1",
        title_ja="日本語タイトル",
        summary_ja="これは要約です。",
    )
    collections = [_tc("画像検索", [item]), _tc("空テーマ", [])]
    ctx = ts._build_overview_context(collections)
    # ref:safe_id（: と . が - に変換）が埋め込まれる
    assert "[ref:arxiv-2606-12345v1]" in ctx
    assert "### テーマ: 画像検索" in ctx
    assert "日本語タイトル" in ctx
    # items が空のテーマはセクションに出ない
    assert "空テーマ" not in ctx


def test_save_and_load_theme_overview_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ts.settings, "data_dir", tmp_path, raising=False)
    assert ts.load_theme_overview("2026-06-10") is None  # 無ければ None
    ts.save_theme_overview("2026-06-10", "# テーマ別論文まとめ\n\n本文。")
    loaded = ts.load_theme_overview("2026-06-10")
    assert loaded is not None
    assert loaded.startswith("# テーマ別論文まとめ")
    assert (tmp_path / "2026-06-10" / "theme_overview.md").exists()
