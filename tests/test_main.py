from __future__ import annotations

from newsletter_pod.config import Settings
from newsletter_pod.mailer import SMTPMailer
from newsletter_pod.main import _build_container


def test_build_container_uses_smtp_mailer_for_publish_summaries_only():
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.sources_file = "missing-sources.yml"
    settings.podcast_api_enabled = False
    settings.alert_email_enabled = False
    settings.publish_summary_email_enabled = True
    settings.smtp_host = "smtp.gmail.com"
    settings.smtp_port = 587
    settings.smtp_username = "sender@example.com"
    settings.smtp_password = "app-password"
    settings.alert_email_from = "sender@example.com"
    settings.alert_email_to = "recipient@example.com"

    container = _build_container(settings)

    assert isinstance(container.pipeline.mailer, SMTPMailer)
