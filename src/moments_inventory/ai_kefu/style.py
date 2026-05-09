from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Tone = Literal["warm", "neutral"]


@dataclass(frozen=True, slots=True)
class StyleProfile:
    tone: Tone
    uses_modal_particles: bool
    prefers_short_sentences: bool


_WARM_MARKERS = ("亲", "您好", "麻烦", "请", "帮您", "这边", "稍等")
_MODAL_PARTICLES = ("哦", "哈", "呢", "呀", "啦", "嘛", "哟")
_SHORT_SENTENCE_MAX_LENGTH = 8
_SHORT_SENTENCE_RATIO_THRESHOLD = 0.6


def _is_short_sentence(message: str) -> bool:
    core_text = message.strip("，。！？；：、,.!?;: ")
    if not core_text:
        return False
    return len(core_text) <= _SHORT_SENTENCE_MAX_LENGTH


def build_style_profile(messages: list[str]) -> StyleProfile:
    normalized_messages = [message.strip() for message in messages if message and message.strip()]
    if not normalized_messages:
        return StyleProfile(
            tone="neutral",
            uses_modal_particles=False,
            prefers_short_sentences=False,
        )

    warm_message_count = sum(
        1 for message in normalized_messages if any(marker in message for marker in _WARM_MARKERS)
    )
    modal_message_count = sum(
        1
        for message in normalized_messages
        if any(particle in message for particle in _MODAL_PARTICLES)
    )
    short_message_count = sum(1 for message in normalized_messages if _is_short_sentence(message))

    uses_modal_particles = modal_message_count > 0
    prefers_short_sentences = (
        short_message_count / len(normalized_messages)
    ) >= _SHORT_SENTENCE_RATIO_THRESHOLD

    return StyleProfile(
        tone="warm" if warm_message_count > 0 or uses_modal_particles else "neutral",
        uses_modal_particles=uses_modal_particles,
        prefers_short_sentences=prefers_short_sentences,
    )
