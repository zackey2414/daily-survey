"""app/gemini.py の遅延クライアント生成の回帰テスト。

新 SDK の genai.Client(api_key="") はコンストラクタで即 ValueError を投げる。
モジュール import 時に生成しないこと（＝API キー未設定でも import は落ちない）と、
未設定時は呼び出し時に明示的な RuntimeError になることを保証する。
"""

import importlib

import pytest

import app.gemini as gem


def test_get_client_raises_runtimeerror_without_key(monkeypatch):
    monkeypatch.setattr(gem, "_client", None)
    monkeypatch.setattr(gem.settings, "gemini_api_key", "", raising=False)
    with pytest.raises(RuntimeError):
        gem.get_client()


def test_get_client_caches_instance(monkeypatch):
    monkeypatch.setattr(gem, "_client", None)
    monkeypatch.setattr(gem.settings, "gemini_api_key", "test-key", raising=False)
    c1 = gem.get_client()
    c2 = gem.get_client()
    assert c1 is c2  # 2回目はキャッシュを返す


def test_llm_modules_import_without_eager_client(monkeypatch):
    """API キーが空でも LLM 関連モジュール・アプリ本体が import できる。

    モジュールトップで genai.Client を生成していると空キーで import が落ちる
    （リグレッション）。遅延生成なら import は常に成功する。
    """
    monkeypatch.setattr(gem, "_client", None)
    monkeypatch.setattr(gem.settings, "gemini_api_key", "", raising=False)
    for mod in [
        "app.services.summarizer",
        "app.services.digest",
        "app.services.themes",
        "app.routers.chat",
        "app.routers.daily_chat",
        "app.main",
    ]:
        importlib.import_module(mod)  # 例外が出なければ OK
    # import だけではクライアントは生成されない
    assert gem._client is None
