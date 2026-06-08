from __future__ import annotations

import contextlib
import io
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zotero_cli_agent.config import project_root
from zotero_cli_agent.core.embedding_provider import EmbeddingProvider

DEFAULT_MODEL = "BAAI/bge-m3"


def default_model_cache_dir() -> Path:
    return project_root() / ".workspace" / "_models"


def _import_sentence_transformer() -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed. "
            "Install it with: uv sync --dev --extra mcp --extra local-embeddings"
        ) from exc
    return SentenceTransformer


class SentenceTransformersProvider(EmbeddingProvider):
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        cache_dir: Path | None = None,
        batch_size: int = 8,
        normalize_embeddings: bool = True,
        device: str | None = None,
        query_prompt_name: str = "query",
        hf_token: str = "",
    ) -> None:
        self.model_name = model or DEFAULT_MODEL
        self.cache_dir = cache_dir or default_model_cache_dir()
        self.batch_size = batch_size
        self.normalize_embeddings = normalize_embeddings
        self.device = device or os.environ.get("ZOT_EMBEDDING_DEVICE", "")
        self.query_prompt_name = query_prompt_name
        self.hf_token = hf_token
        self._model: Any | None = None

    @property
    def name(self) -> str:
        return "sentence_transformers"

    def download(self) -> None:
        self._load_model()

    def embed(
        self,
        texts: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
        *,
        input_type: str = "document",
    ) -> list[list[float]]:
        if not texts:
            return []

        model = self._load_model()
        all_embeddings: list[list[float]] = []
        total = len(texts)
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            kwargs: dict[str, Any] = {
                "batch_size": self.batch_size,
                "normalize_embeddings": self.normalize_embeddings,
                "show_progress_bar": False,
            }
            if input_type == "query" and self.query_prompt_name:
                prompts = getattr(model, "prompts", {})
                if isinstance(prompts, dict) and self.query_prompt_name in prompts:
                    kwargs["prompt_name"] = self.query_prompt_name
            embeddings = model.encode(batch, **kwargs)
            all_embeddings.extend(_to_list(embeddings))
            if progress_callback:
                progress_callback(min(i + self.batch_size, total), total)
        return all_embeddings

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        SentenceTransformer = _import_sentence_transformer()
        kwargs: dict[str, Any] = {"cache_folder": str(self.cache_dir)}
        if self.device:
            kwargs["device"] = self.device
        if self.hf_token:
            kwargs["token"] = self.hf_token
        # Some model loaders emit tqdm/status text during weight loading. Keep
        # stdout/stderr clean so JSON CLI output remains parseable.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self._model = SentenceTransformer(self.model_name, **kwargs)
        return self._model


def _to_list(embeddings: Any) -> list[list[float]]:
    if hasattr(embeddings, "tolist"):
        data = embeddings.tolist()
    else:
        data = embeddings
    return [[float(value) for value in row] for row in data]
