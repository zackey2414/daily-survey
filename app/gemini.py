"""
Gemini API クライアント（新 SDK google.genai）の遅延生成ヘルパー。

新 SDK の genai.Client(api_key="") はコンストラクタで即座に ValueError を送出する。
そのためモジュール import 時にクライアントを生成すると、GEMINI_API_KEY 未設定の環境
（CI / シークレット未注入の Docker イメージ等）でアプリ全体の起動が落ちてしまう。
呼び出し時に遅延生成してキャッシュすることで import は常に成功し、実際に Gemini を
呼ぶ時にのみ明示的なエラーを出す（旧 SDK の genai.configure の遅延挙動に合わせる）。
"""

from __future__ import annotations

from google import genai

from app.config import settings

_client: genai.Client | None = None


def get_client() -> genai.Client:
    """共有 Gemini クライアントを返す（初回呼び出し時に遅延生成・キャッシュ）。"""
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY が未設定のため Gemini API を呼び出せません"
            )
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client
