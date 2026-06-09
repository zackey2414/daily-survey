"""
fire-and-forget なバックグラウンドタスクのユーティリティ

asyncio.create_task は (1) 参照が無いと GC で途中キャンセルされうる、
(2) タスク内で送出された例外が誰にも観測されず黙殺される、という落とし穴がある。
spawn() は強参照を保持しつつ完了時に例外をログへ出すことで、無人運用中の
「タスクが静かに消える / 例外が握り潰される」状況を防ぐ。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

# 完了まで強参照を保持する（GC による途中キャンセル防止）
_background_tasks: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str) -> asyncio.Task:
    """コルーチンをバックグラウンド実行する。例外は完了時にログへ出す。"""
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        _background_tasks.discard(t)
        if t.cancelled():
            logger.warning(f"バックグラウンドタスク '{name}' はキャンセルされました")
            return
        exc = t.exception()
        if exc is not None:
            logger.error(
                f"バックグラウンドタスク '{name}' が例外終了しました: {exc}",
                exc_info=exc,
            )

    task.add_done_callback(_on_done)
    return task
