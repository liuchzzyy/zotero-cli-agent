from __future__ import annotations

from collections.abc import Callable

from zotero_cli_agent.config import EmbeddingConfig
from zotero_cli_agent.core.embedding_provider import EmbeddingProvider
from zotero_cli_agent.core.providers.jina import JinaProvider
from zotero_cli_agent.core.providers.openai_compatible import OpenAICompatibleEmbeddingProvider


class EmbeddingRouter:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.providers: dict[str, EmbeddingProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        api_key = self.config.api_key
        model = self.config.model

        if self.config.provider == "jina":
            if not api_key:
                return
            jina_url = self.config.url if "jina" in self.config.url else "https://api.jina.ai/v1/embeddings"
            self.providers["jina"] = JinaProvider(
                api_key=api_key,
                model=model,
                url=jina_url,
            )
        elif self.config.provider in {"aliyun", "gitee"}:
            if not api_key:
                return
            api_url = _normalize_embeddings_base_url(
                self.config.url or _default_openai_compatible_base_url(self.config.provider)
            )
            self.providers[self.config.provider] = OpenAICompatibleEmbeddingProvider(
                api_key=api_key,
                model=model,
                base_url=api_url,
                name=self.config.provider,
                batch_size=self.config.batch_size,
            )
        elif self.config.provider == "sentence_transformers":
            from zotero_cli_agent.core.providers.sentence_transformers import SentenceTransformersProvider

            self.providers["sentence_transformers"] = SentenceTransformersProvider(
                model=model,
                batch_size=self.config.batch_size,
                device=self.config.device,
                hf_token=self.config.hf_token,
            )

    def embed(
        self,
        texts: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        if not texts:
            return []

        provider = self._find_provider()
        if provider:
            return provider.embed(texts, progress_callback, input_type=input_type)

        raise RuntimeError("No embedding provider configured")

    def _find_provider(self) -> EmbeddingProvider | None:
        priority = ["sentence_transformers", "gitee", "aliyun", "jina"]
        for name in priority:
            if name in self.providers:
                return self.providers[name]
        return None


def _normalize_embeddings_base_url(url: str) -> str:
    """Return the OpenAI-compatible base URL without the /embeddings suffix."""
    normalized = url.rstrip("/")
    if normalized.endswith("/embeddings"):
        return normalized[: -len("/embeddings")]
    return normalized


def _default_openai_compatible_base_url(provider: str) -> str:
    if provider == "gitee":
        return "https://ai.gitee.com/v1"
    return "https://dashscope.aliyuncs.com/compatible-mode/v1"
