"""Minimal SMTP delivery for verification and password-reset codes."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from config import (
    SMTP_FROM_EMAIL,
    SMTP_FROM_NAME,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USERNAME,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
)


def smtp_configured() -> bool:
    return bool(SMTP_HOST and SMTP_FROM_EMAIL)


def send_action_code(email: str, code: str, purpose: str, expires_minutes: int) -> str:
    """Send a code and return ``smtp`` or ``console`` as delivery channel."""
    label = "验证邮箱" if purpose == "verify_email" else "重置密码"
    if not smtp_configured():
        print(f"[Auth/{purpose}] email={email} code={code} expires={expires_minutes}m")
        return "console"

    message = EmailMessage()
    message["Subject"] = f"{label}验证码：{code}"
    message["From"] = formataddr((SMTP_FROM_NAME, SMTP_FROM_EMAIL))
    message["To"] = email
    message.set_content(
        f"你的{label}验证码是：{code}\n\n"
        f"验证码将在 {expires_minutes} 分钟后失效，请勿转发给他人。\n"
        "如果不是你本人操作，请忽略此邮件。"
    )

    smtp_class = smtplib.SMTP_SSL if SMTP_USE_SSL else smtplib.SMTP
    with smtp_class(SMTP_HOST, SMTP_PORT, timeout=20) as server:
        if SMTP_USE_TLS and not SMTP_USE_SSL:
            server.starttls()
        if SMTP_USERNAME:
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(message)
    return "smtp"

