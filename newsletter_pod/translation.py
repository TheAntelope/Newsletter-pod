from __future__ import annotations

from typing import Optional

import requests


OPENAI_DEFAULT_BASE_URL = "https://api.openai.com"


class TranslationError(RuntimeError):
    pass


def translate_to_english(
    text: str,
    *,
    api_key: Optional[str],
    text_model: str,
    base_url: Optional[str] = None,
    timeout_seconds: int = 30,
    locale_hint: Optional[str] = None,
) -> str:
    """Translate user-submitted feedback to English. If the input is already
    English (or close enough), the model is instructed to return it unchanged."""
    if not api_key:
        raise TranslationError("OpenAI API key is not configured")
    if not text.strip():
        return text

    instruction_lines = [
        "You translate short user feedback messages into English.",
        "If the input is already in English, return it verbatim with no changes.",
        "Preserve the user's tone, wording choices, and any product or feature names.",
        "Return ONLY the translated text — no commentary, prefixes, or quotation marks.",
    ]
    if locale_hint:
        instruction_lines.append(f"The submitter's reported locale is {locale_hint}.")

    payload = {
        "model": text_model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": "\n".join(instruction_lines)}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": text}],
            },
        ],
    }

    endpoint = _build_endpoint(base_url)
    response = requests.post(
        endpoint,
        json=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    return _extract_output_text(response.json())


def _build_endpoint(base_url: Optional[str]) -> str:
    base = (base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
    if base.endswith("/v1"):
        return f"{base}/responses"
    return f"{base}/v1/responses"


def _extract_output_text(data: dict) -> str:
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])
    text = "".join(parts).strip()
    if not text:
        raise TranslationError("OpenAI response did not include output_text")
    return text
