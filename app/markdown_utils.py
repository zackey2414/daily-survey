"""
Markdown 前処理ユーティリティ

Python-Markdown は CommonMark と異なり、段落の直後（空行なし）に始まる
箇条書き/番号付きリストをリストとして認識せず、段落の続きと見なす。
LLM（要約・ダイジェスト）出力は「説明文。\\n- 箇条書き」のように空行なしで
リストを続けることが多く、階層付きの箇条書きが <ul> にならず素の段落として
描画される原因になっていた。

normalize_markdown() はリスト開始行の直前に空行を補ってこれを解消する。
リスト途中の項目や継続行を誤って分割しないよう、リスト状態を追跡する。
fenced code block (``` / ~~~) の内部は対象外。
"""

from __future__ import annotations

import re

# 行頭（インデント可）の箇条書き/番号付きリスト項目: "- x" "* x" "+ x" "1. x"
_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+\.)[ \t]+\S")
# fenced code block の開始/終了フェンス
_FENCE_RE = re.compile(r"^[ \t]*(?:```|~~~)")


def normalize_markdown(text: str) -> str:
    """段落の直後（空行なし）に始まるリストの前に空行を挿入して返す。"""
    if not text or (
        "-" not in text and "*" not in text and "+" not in text and "." not in text
    ):
        return text

    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    in_list = False
    prev_blank = True  # 文頭は「空行の後」とみなす

    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            in_list = False
            out.append(line)
            prev_blank = False
            continue

        if in_fence:
            out.append(line)
            prev_blank = line.strip() == ""
            continue

        is_blank = line.strip() == ""
        is_item = bool(_LIST_ITEM_RE.match(line))

        if is_item:
            # 段落 → リスト の遷移（リスト外 かつ 直前が非空）でのみ空行を補う
            if not in_list and not prev_blank:
                out.append("")
            in_list = True
        elif is_blank:
            pass  # loose list の途中かもしれないのでリスト状態は維持
        else:
            # 非空・非リスト行
            if in_list and not line[:1].isspace() and prev_blank:
                # 空行を挟んだ非インデント段落 → リスト終了
                in_list = False
            # それ以外（インデント継続行・lazy 継続行）はリスト内のまま

        out.append(line)
        prev_blank = is_blank

    return "\n".join(out)
