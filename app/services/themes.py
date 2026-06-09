"""
検索テーマの管理モジュール
- data/themes.json に登録テーマ（Theme）を永続化する
- Gemini でテーマ名から関連キーワードを自動生成する

永続化パターンは github_trending.py のキーワード管理に倣う。
Gemini クライアントの設定は summarizer.py と同じ（genai はモジュール import 時に configure 済み）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

import google.generativeai as genai
import pytz

from app.config import settings
from app.schemas import Theme

logger = logging.getLogger(__name__)
JST = pytz.timezone("Asia/Tokyo")

THEMES_FILE = "themes.json"
MAX_KEYWORDS = 20  # 1テーマあたりのキーワード上限
MAX_THEMES = 20  # enabled テーマの上限

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# Gemini API の設定（summarizer.py でも設定されるが、import 順に依存しないよう冪等に再設定）
if settings.gemini_api_key:
    genai.configure(api_key=settings.gemini_api_key)


# ── レジストリ管理 ────────────────────────────────────────────


def _themes_path() -> Path:
    return settings.data_dir / THEMES_FILE


def _bak_path() -> Path:
    p = _themes_path()
    return p.parent / (p.name + ".bak")


def load_themes() -> list[Theme]:
    """data/themes.json を読み込む。破損時は .bak から復旧、それも不可なら空リスト。"""
    path = _themes_path()
    for p in (path, _bak_path()):
        if not p.exists():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                logger.warning(f"{p.name} の形式が不正（list でない）")
                continue
            themes = [Theme.model_validate(t) for t in raw]
            if p != path:
                logger.warning("themes.json が壊れていたため .bak から復旧しました")
            return themes
        except Exception as e:
            logger.warning(f"{p.name} 読み込み失敗: {e}")
            continue
    return []


def save_themes(themes: list[Theme]) -> None:
    """テーマ一覧をアトミックに永続化する（直前の正常版は .bak に退避）。

    一時ファイルへ書いてから os.replace で置換することで、書き込み途中の
    クラッシュ・ディスクフルでも本体ファイルが半端な状態にならないようにする。
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = _themes_path()
    payload = json.dumps([t.model_dump() for t in themes], ensure_ascii=False, indent=2)

    # 直前の正常ファイルを .bak に退避（破損時のフォールバック用）
    if path.exists():
        try:
            shutil.copyfile(path, _bak_path())
        except OSError as e:
            logger.warning(f"themes.json の .bak 退避に失敗: {e}")

    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)  # POSIX 上でアトミック


def ensure_default_themes() -> None:
    """初回起動時、themes.json が存在しなければ config のデフォルトテーマを投入する。

    ファイルが既に存在する場合は何もしない（ユーザーが削除したテーマを復活させない）。
    themes.json を手動削除しても .bak が残っていれば「初期化済み」とみなし再シードしない。
    """
    if _themes_path().exists() or _bak_path().exists():
        return
    defaults = getattr(settings, "default_themes", []) or []
    seeded: list[Theme] = []
    for d in defaults:
        name = str(d.get("name", "")).strip()
        if not name:
            continue
        seeded.append(
            Theme(
                id=uuid.uuid4().hex[:12],
                name=name,
                keywords=_dedup_keywords(list(d.get("keywords", [])))[:MAX_KEYWORDS],
                enabled=True,
                created_at=datetime.now(JST).isoformat(),
            )
        )
    if seeded:
        save_themes(seeded)
        logger.info(f"デフォルトテーマを投入しました: {[t.name for t in seeded]}")


def get_theme(theme_id: str) -> Theme | None:
    for t in load_themes():
        if t.id == theme_id:
            return t
    return None


def count_enabled_themes() -> int:
    return sum(1 for t in load_themes() if t.enabled)


def add_theme(name: str, keywords: list[str]) -> Theme:
    """新規テーマを登録して返す。"""
    themes = load_themes()
    theme = Theme(
        id=uuid.uuid4().hex[:12],
        name=name.strip(),
        keywords=_dedup_keywords(keywords)[:MAX_KEYWORDS],
        enabled=True,
        created_at=datetime.now(JST).isoformat(),
    )
    themes.append(theme)
    save_themes(themes)
    return theme


def update_theme_keywords(theme_id: str, keywords: list[str]) -> Theme | None:
    themes = load_themes()
    for t in themes:
        if t.id == theme_id:
            t.keywords = _dedup_keywords(keywords)[:MAX_KEYWORDS]
            save_themes(themes)
            return t
    return None


def add_keyword(theme_id: str, keyword: str) -> Theme | None:
    t = get_theme(theme_id)
    if t is None:
        return None
    kw = keyword.strip()
    if kw and kw.lower() not in {k.lower() for k in t.keywords}:
        if len(t.keywords) >= MAX_KEYWORDS:
            return t  # 上限に達していたら無視
        t.keywords.append(kw)
        return update_theme_keywords(theme_id, t.keywords)
    return t


def remove_keyword(theme_id: str, keyword: str) -> Theme | None:
    t = get_theme(theme_id)
    if t is None:
        return None
    new_keywords = [k for k in t.keywords if k != keyword]
    return update_theme_keywords(theme_id, new_keywords)


def remove_keyword_at(theme_id: str, index: int) -> Theme | None:
    """インデックス指定でキーワードを削除する（URL エンコード問題を回避）。"""
    t = get_theme(theme_id)
    if t is None:
        return None
    if 0 <= index < len(t.keywords):
        new_keywords = [k for i, k in enumerate(t.keywords) if i != index]
        return update_theme_keywords(theme_id, new_keywords)
    return t


def set_theme_enabled(theme_id: str, enabled: bool) -> Theme | None:
    themes = load_themes()
    for t in themes:
        if t.id == theme_id:
            t.enabled = enabled
            save_themes(themes)
            return t
    return None


def delete_theme(theme_id: str) -> bool:
    themes = load_themes()
    new_themes = [t for t in themes if t.id != theme_id]
    if len(new_themes) == len(themes):
        return False
    save_themes(new_themes)
    return True


# ── Gemini キーワード生成 ─────────────────────────────────────


def _load_template(name: str) -> str:
    path = _PROMPTS_DIR / name
    if path.exists():
        return path.read_text(encoding="utf-8")
    logger.warning(f"プロンプトテンプレートが見つかりません: {path}")
    return ""


def _call_gemini(prompt: str) -> str:
    model = genai.GenerativeModel(settings.gemini_chat_model)
    response = model.generate_content(prompt)
    # safety ブロック等で candidate が無いと response.text は None を返しうる
    return (getattr(response, "text", None) or "").strip()


def _call_gemini_with_retry(prompt: str, max_retries: int = 3) -> str:
    """一時的な Gemini エラー（quota/429/5xx/ネットワーク）をバックオフ付きでリトライ。"""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return _call_gemini(prompt)
        except Exception as e:  # noqa: BLE001 — 種別を問わず一時障害として扱う
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))  # 2s, 4s
    assert last_exc is not None
    raise last_exc


def _parse_keywords(text: str) -> list[str]:
    """Gemini 出力（1行1キーワード想定）をパースする。

    番号・箇条書き記号・引用符・見出しを除去し、大小無視で重複除去。
    """
    keywords: list[str] = []
    for line in text.splitlines():
        kw = line.strip()
        if not kw:
            continue
        # 箇条書き記号・番号プレフィックスを除去（例: "- ", "* ", "1. ", "1) "）
        kw = kw.lstrip("-*・•# ").strip()
        if kw and kw[0].isdigit():
            for sep in (". ", ") ", "．", "、"):
                if sep in kw[:4]:
                    kw = kw.split(sep, 1)[1].strip()
                    break
        kw = kw.strip("\"'`「」『』 ")
        if not kw or kw.lower() in {"キーワード", "keywords"}:
            continue
        keywords.append(kw)
    return _dedup_keywords(keywords)[:MAX_KEYWORDS]


def _dedup_keywords(keywords: list[str]) -> list[str]:
    """大小無視・順序維持で重複除去（空文字も除去）。"""
    seen: set[str] = set()
    result: list[str] = []
    for kw in keywords:
        kw = kw.strip()
        key = kw.lower()
        if kw and key not in seen:
            seen.add(key)
            result.append(kw)
    return result


async def generate_keywords(theme_name: str) -> list[str]:
    """テーマ名から Gemini で関連キーワードを生成する。

    失敗時は空リストを返す（呼び出し側で [theme_name] にフォールバック）。
    """
    name = theme_name.strip()
    if not name:
        return []
    template = _load_template("theme_keywords.md")
    if not template:
        return []
    prompt = template.format(theme_name=name)
    try:
        text = await asyncio.get_event_loop().run_in_executor(
            None, _call_gemini_with_retry, prompt
        )
    except Exception as e:
        logger.error(f"テーマ '{name}' のキーワード生成失敗（リトライ後）: {e}")
        return []
    keywords = _parse_keywords(text)
    # テーマ名自身を先頭に含める（重複しない場合）
    if name.lower() not in {k.lower() for k in keywords}:
        keywords = [name] + keywords
    return keywords[:MAX_KEYWORDS]
