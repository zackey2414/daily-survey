"""normalize_markdown の回帰テスト。

段落直後に空行なしで始まるリストの前に空行を補い、Python-Markdown が
リスト（ネスト含む）として描画できるようにする処理を検証する。
"""

import markdown as md

from app.markdown_utils import normalize_markdown

_EXT = ["fenced_code", "tables", "nl2br"]


def _render(src: str) -> str:
    return md.markdown(normalize_markdown(src), extensions=_EXT, tab_length=2)


def test_paragraph_followed_by_list_becomes_list():
    # 空行なしで段落→箇条書きが続くケース（実際の LLM 出力パターン）
    src = "説明文。\n- 親A\n  - 子A1\n  - 子A2\n- 親B\n"
    html = _render(src)
    # 外側リスト + 親A 配下のネストリスト = <ul> 2、項目は 親A/子A1/子A2/親B = 4
    assert html.count("<ul>") == 2
    assert html.count("<li>") == 4
    assert "<p>説明文。</p>" in html
    # 親A の中に子リストがネストしている
    assert "親A<ul>" in html


def test_multiline_item_not_split():
    # 項目の継続行（インデント）でリストが分割されないこと
    src = "導入。\n- 親項目の1行目\n  同じ項目の続き\n- 次の親\n"
    html = _render(src)
    assert html.count("<ul>") == 1
    assert html.count("<li>") == 2


def test_fenced_code_block_untouched():
    src = "前文。\n```\n- これはコード\n- リストではない\n```\n本文。\n- 本物のリスト\n"
    html = _render(src)
    # コードブロック内はリスト化されず、後続の本物のリストのみ <ul> 化
    assert html.count("<ul>") == 1
    assert "<code>" in html or "<pre>" in html


def test_numbered_list():
    src = "貢献は以下。\n1. 提案\n2. 達成\n"
    html = _render(src)
    assert html.count("<ol>") == 1
    assert html.count("<li>") == 2


def test_already_blank_line_not_doubled():
    # すでに空行がある場合は二重に挿入しない
    src = "段落。\n\n- 項目\n"
    normalized = normalize_markdown(src)
    assert "\n\n\n" not in normalized
    assert _render(src).count("<ul>") == 1


def test_empty_and_plain_text():
    assert normalize_markdown("") == ""
    assert normalize_markdown("ただの文章。改行のみ。\n次の行。") == (
        "ただの文章。改行のみ。\n次の行。"
    )
