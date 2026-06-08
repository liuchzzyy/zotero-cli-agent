from __future__ import annotations

import contextlib
import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

from zotero_cli_agent.core.providers.sentence_transformers import default_model_cache_dir

DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"


def _import_transformers() -> tuple[Any, Any]:
    try:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError(
            "transformers is not installed. "
            "Install it with: uv sync --dev --extra mcp --extra local-embeddings"
        ) from exc
    return AutoTokenizer, AutoModelForSequenceClassification


def _import_torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError(
            "torch is not installed. Install local embedding dependencies with: "
            "uv sync --dev --extra mcp --extra local-embeddings"
        ) from exc
    return torch


class BgeRerankerProvider:
    def __init__(
        self,
        model: str = DEFAULT_RERANKER_MODEL,
        *,
        cache_dir: Path | None = None,
        batch_size: int = 4,
        max_length: int = 512,
        hf_token: str = "",
    ) -> None:
        self.model_name = model or DEFAULT_RERANKER_MODEL
        self.cache_dir = cache_dir or default_model_cache_dir()
        self.batch_size = batch_size
        self.max_length = max_length
        self.hf_token = hf_token
        self._tokenizer: Any | None = None
        self._model: Any | None = None

    @property
    def name(self) -> str:
        return "bge_reranker"

    def download(self) -> None:
        self._load_model()

    def score(
        self,
        query: str,
        documents: list[str],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[float]:
        if not documents:
            return []

        tokenizer, model = self._load_model()
        torch = _import_torch()
        scores: list[float] = []
        total = len(documents)
        device = next(model.parameters()).device
        for i in range(0, total, self.batch_size):
            batch_docs = documents[i : i + self.batch_size]
            encoded = tokenizer(
                [query] * len(batch_docs),
                batch_docs,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            with torch.no_grad():
                logits = model(**encoded).logits
            scores.extend(_logits_to_scores(logits))
            if progress_callback:
                progress_callback(min(i + self.batch_size, total), total)
        return scores

    def _load_model(self) -> tuple[Any, Any]:
        if self._tokenizer is not None and self._model is not None:
            return self._tokenizer, self._model
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        AutoTokenizer, AutoModelForSequenceClassification = _import_transformers()
        kwargs: dict[str, Any] = {"cache_dir": str(self.cache_dir)}
        if self.hf_token:
            kwargs["token"] = self.hf_token
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, **kwargs)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name, **kwargs)
        self._model.eval()
        return self._tokenizer, self._model


def _logits_to_scores(logits: Any) -> list[float]:
    if len(logits.shape) == 1:
        values = logits
    elif logits.shape[-1] == 1:
        values = logits[:, 0]
    else:
        values = logits[:, -1]
    return [float(value) for value in values.detach().cpu().tolist()]
