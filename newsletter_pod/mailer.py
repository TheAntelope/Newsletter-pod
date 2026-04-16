from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class Mailer:
    def send(self, subject: str, body: str) -> None:
        raise NotImplementedError


@dataclass
class SMTPMailer(Mailer):
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    recipient: str
    use_tls: bool = True

    def send(self, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.sender
        msg["To"] = self.recipient
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(self.host, self.port, timeout=30) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password or "")
            smtp.send_message(msg)


class NoopMailer(Mailer):
    def send(self, subject: str, body: str) -> None:
        logger.info("Noop mailer: %s", subject)
