from __future__ import annotations

from dataclasses import dataclass


SCRIPT_INPUT_PRICE_PER_MILLION = 0.75
SCRIPT_OUTPUT_PRICE_PER_MILLION = 4.50
TTS_INPUT_PRICE_PER_MILLION = 0.60
TTS_PRICE_PER_MINUTE = 0.015
ELEVENLABS_PRICE_PER_MILLION_CHARS = 180.0
DEFAULT_INFRA_RESERVE_USD = 0.01


@dataclass
class CostEstimate:
    text_input_tokens_estimate: int
    text_output_tokens_estimate: int
    tts_input_tokens_estimate: int
    tts_output_minutes_estimate: float
    openai_cost_usd: float
    infra_reserve_cost_usd: float
    total_cost_usd: float


def estimate_generation_cost(
    prompt_text: str,
    transcript_text: str,
    show_notes_text: str,
    duration_seconds: int | None,
    infra_reserve_usd: float = DEFAULT_INFRA_RESERVE_USD,
    tts_provider: str = "openai",
) -> CostEstimate:
    text_input_tokens = estimate_text_tokens(prompt_text)
    text_output_tokens = estimate_text_tokens(transcript_text) + estimate_text_tokens(show_notes_text)
    tts_input_tokens = estimate_text_tokens(transcript_text)
    tts_minutes = max((duration_seconds or 0) / 60.0, 0.0)

    script_cost = (
        (text_input_tokens / 1_000_000) * SCRIPT_INPUT_PRICE_PER_MILLION
        + (text_output_tokens / 1_000_000) * SCRIPT_OUTPUT_PRICE_PER_MILLION
    )
    if tts_provider.strip().lower() == "elevenlabs":
        tts_cost = (len(transcript_text) / 1_000_000) * ELEVENLABS_PRICE_PER_MILLION_CHARS
    else:
        tts_cost = (
            (tts_input_tokens / 1_000_000) * TTS_INPUT_PRICE_PER_MILLION
            + (tts_minutes * TTS_PRICE_PER_MINUTE)
        )
    openai_cost = round(script_cost + tts_cost, 6)
    total_cost = round(openai_cost + infra_reserve_usd, 6)

    return CostEstimate(
        text_input_tokens_estimate=text_input_tokens,
        text_output_tokens_estimate=text_output_tokens,
        tts_input_tokens_estimate=tts_input_tokens,
        tts_output_minutes_estimate=round(tts_minutes, 4),
        openai_cost_usd=openai_cost,
        infra_reserve_cost_usd=round(infra_reserve_usd, 6),
        total_cost_usd=total_cost,
    )


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, round(len(text) / 4))
