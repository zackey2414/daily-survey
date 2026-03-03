"""
メール通知モジュール
日次収集完了時にメールを送信する
"""
import logging
from dataclasses import dataclass, field

import aiosmtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CollectionReport:
    date_str: str
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    digest_preview: str = ""


async def send_completion_email(report: CollectionReport) -> None:
    """収集完了メールを送信する"""
    if not settings.smtp_username or not settings.smtp_to:
        logger.warning("SMTP 設定が未完了のため、メール通知をスキップします")
        return

    subject = f"[AI Daily Survey] {report.date_str} の収集完了"
    body = _build_email_body(report)

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = settings.smtp_to
    message["Subject"] = subject
    message.set_content(body)

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            start_tls=True,
        )
        logger.info(f"完了メール送信成功: {settings.smtp_to}")
    except Exception as e:
        logger.error(f"メール送信失敗: {e}")


def _build_email_body(report: CollectionReport) -> str:
    elapsed_min = report.elapsed_seconds / 60

    count_lines = "\n".join(
        f"  - {cat}: {cnt} 件"
        for cat, cnt in report.counts.items()
    )
    total = sum(report.counts.values())

    error_section = ""
    if report.errors:
        error_lines = "\n".join(f"  - {e}" for e in report.errors)
        error_section = f"\n\n■ エラー ({len(report.errors)} 件)\n{error_lines}"

    preview_section = ""
    if report.digest_preview:
        preview_section = f"\n\n■ 一面まとめ（冒頭）\n{report.digest_preview[:500]}..."

    return f"""AI Daily Survey - 日次収集完了通知

■ 収集日: {report.date_str}
■ 処理時間: {elapsed_min:.1f} 分
■ 収集件数合計: {total} 件

{count_lines}
{error_section}
{preview_section}

---
http://localhost:8000
"""
