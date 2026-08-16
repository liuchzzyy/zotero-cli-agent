from __future__ import annotations

from typing import Any

from openai import OpenAI

from zotero_cli_agent.config import AiNoteConfig


class AiClient:
    """Minimal OpenAI-compatible chat client for AI note generation."""

    def __init__(self, config: AiNoteConfig) -> None:
        self.config = config
        self._client = OpenAI(base_url=config.base_url, api_key=config.api_key)

    def chat(self, prompt: str) -> str:
        create_kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        response = self._client.chat.completions.create(**create_kwargs)
        content = response.choices[0].message.content
        return (content or "").strip()
