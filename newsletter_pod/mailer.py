from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class Mailer:
    def send(
        self,
        subject: str,
        body: str,
        *,
        recipients: list[str] | None = None,
    ) -> None:
        raise NotImplementedError


@dataclass
class SMTPMailer(Mailer):
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    default_recipients: list[str] = field(default_factory=list)
    use_tls: bool = True

    def send(
        self,
        subject: str,
        body: str,
        *,
        recipients: list[str] | None = None,
    ) -> None:
        targets = [r for r in (recipients or self.default_recipients) if r]
        if not targets:
            raise RuntimeError("SMTPMailer: no recipients configured")
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = ", ".join(targets)
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)


class NoopMailer(Mailer):
    def send(
        self,
        subject: str,
        body: str,
        *,
        recipients: list[str] | None = None,
    ) -> None:
        logger.info("Noop mailer: %s (recipients=%s)", subject, recipients)
