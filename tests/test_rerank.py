from __future__ import annotations

from unittest.mock import patch

import pytest

from zotero_cli_agent.config import RerankConfig
from zotero_cli_agent.core.rerank import rerank_chunks


def test_rerank_chunks_sorts_selected_candidates():
    candidates = [
        (1, 0.9, {"content": "weak", "item_key": "A", "source": "metadata"}),
        (2, 0.8, {"content": "strong", "item_key": "B", "source": "metadata"}),
        (3, 0.7, {"content": "outside top_n", "item_key": "C", "source": "metadata"}),
    ]

    class FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def score(self, query, documents, progress_callback=None):
            assert query == "battery"
            assert documents == ["weak", "strong"]
            return [0.1, 0.9]

    with patch("zotero_cli_agent.core.rerank.BgeRerankerProvider", FakeProvider):
        result = rerank_chunks(
            "battery",
            candidates,
            RerankConfig(provider="bge_reranker", model="reranker", hf_token="hf-token"),
            top_n=2,
        )

    assert result is not None
    assert [cid for cid, _score, _chunk in result] == [2, 1, 3]
    assert result[0][1] == pytest.approx(0.9)


def test_rerank_chunks_returns_none_when_not_configured():
    result = rerank_chunks(
        "battery",
        [(1, 0.9, {"content": "text"})],
        RerankConfig(provider="", model=""),
    )
    assert result is None


def test_rerank_chunks_rejects_unknown_provider():
    with pytest.raises(RuntimeError, match="Unsupported reranker provider"):
        rerank_chunks(
            "battery",
            [(1, 0.9, {"content": "text"})],
            RerankConfig(provider="other", model="model"),
        )
