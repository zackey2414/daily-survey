"""
英語版（一面まとめ）の音声合成モジュール（ローカル TTS）。

Kokoro-82M を onnxruntime（kokoro-onnx）で実行し、英文全体を mp3 に合成して
`summaries/{date}.en.mp3` に保存する。**API は使わずローカル実行**のためトークン課金は無い。

- モデル(.onnx / .bin)は初回に GitHub リリースから `models/` へダウンロードしてキャッシュする。
- 音素化(espeak-ng)は `espeakng-loader` がバンドルするため OS 側のインストールは不要。
- mp3 書き出しは `soundfile`（同梱 libsndfile）が直接対応するため ffmpeg は不要。
- 合成は重い CPU 処理のため、必ずバックグラウンド（run_in_executor / spawn）で実行する。
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.request
from pathlib import Path

from app.config import settings
from app.services.english_digest import load_english_digest

# 注: numpy / soundfile / kokoro_onnx は tts グループ依存のため、モジュール import 時には
# 読み込まず、実際に合成する _synthesize_sync 内で遅延 import する（依存未導入の環境でも
# このモジュール（audio_path 等）を import できるようにするため）。

logger = logging.getLogger(__name__)

_MODEL_BASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)
_ONNX_NAME = "kokoro-v1.0.onnx"
_VOICES_NAME = "voices-v1.0.bin"

# 文の切れ目は段落ごとにまとめて合成し Kokoro の自然な間に任せる（人工的な文間無音は
# 入れない＝ブツ切れにならない）。段落の境目だけ短い無音を挟む。
_PARAGRAPH_GAP_S = 0.25


def audio_path(date_str: str) -> Path:
    return settings.summaries_dir / f"{date_str}.en.mp3"


def english_audio_exists(date_str: str) -> bool:
    """その日の英語版音声(mp3)が生成済みか。"""
    p = audio_path(date_str)
    return p.exists() and p.stat().st_size > 0


def _ensure_model() -> tuple[Path, Path]:
    """Kokoro のモデルファイルが無ければ GitHub リリースから取得して返す。"""
    models_dir = settings.models_dir
    models_dir.mkdir(parents=True, exist_ok=True)
    onnx = models_dir / _ONNX_NAME
    voices = models_dir / _VOICES_NAME
    for path, name in ((onnx, _ONNX_NAME), (voices, _VOICES_NAME)):
        if path.exists() and path.stat().st_size > 0:
            continue
        url = f"{_MODEL_BASE}/{name}"
        logger.info(f"Kokoro モデルをダウンロード中: {url}")
        tmp = path.with_suffix(path.suffix + ".tmp")
        urllib.request.urlretrieve(url, tmp)  # noqa: S310 — 固定の信頼できる URL
        os.replace(tmp, path)
    return onnx, voices


def _paragraph_texts(eng) -> list[str]:
    """段落ごとに文を1つの文字列へ連結して返す（空段落は除外）。

    段落単位で合成することで、文の切れ目は Kokoro が自然な長さの間で読み上げる。
    文ごとに人工無音を挟まないため、意味のまとまりごとにブツ切れに聞こえる問題を防ぐ。
    """
    paras: list[str] = []
    for para in eng.paragraphs:
        text = " ".join(s.en.strip() for s in para.sentences if s.en.strip())
        if text:
            paras.append(text)
    return paras


def _synthesize_sync(date_str: str) -> str | None:
    """同期実行の本体（executor から呼ぶ）。mp3 パスを返す。"""
    eng = load_english_digest(date_str)
    if eng is None:
        logger.info(f"音声合成: 英語版が無いためスキップ ({date_str})")
        return None
    paras = _paragraph_texts(eng)
    if not paras:
        logger.info(f"音声合成: 英文が空のためスキップ ({date_str})")
        return None

    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    onnx, voices = _ensure_model()
    kokoro = Kokoro(str(onnx), str(voices))

    sr: int | None = None
    pieces: list[np.ndarray] = []
    for i, text in enumerate(paras):
        samples, sample_rate = kokoro.create(
            text,
            voice=settings.kokoro_voice,
            speed=settings.kokoro_speed,
            lang="en-us",
        )
        sr = sample_rate
        pieces.append(samples)
        # 段落間だけ短い無音を挟む（最後の段落以外）。文間は Kokoro の自然な間に任せる。
        if i < len(paras) - 1:
            pieces.append(np.zeros(int(sr * _PARAGRAPH_GAP_S), dtype=samples.dtype))

    if sr is None or not pieces:
        return None
    audio = np.concatenate(pieces)

    out = audio_path(date_str)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    sf.write(str(tmp), audio, sr, format="MP3")
    os.replace(tmp, out)  # アトミック置換
    logger.info(f"音声合成完了: {out} ({len(audio) / sr:.1f}s)")
    return str(out)


async def synthesize_english_audio(date_str: str) -> str | None:
    """英語版の英文全体を mp3 に合成して保存する（失敗時 None・非致命）。

    重い CPU 処理のため executor（別スレッド）で実行する。
    """
    try:
        return await asyncio.get_event_loop().run_in_executor(
            None, _synthesize_sync, date_str
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"音声合成失敗 ({date_str}): {e}")
        return None
