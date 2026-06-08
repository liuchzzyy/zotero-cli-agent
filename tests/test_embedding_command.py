from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from zotero_cli_agent.cli import main
from zotero_cli_agent.exit_codes import EXIT_OK

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _run(args, env=None):
    runner = CliRunner()
    base_env = {"ZOT_DATA_DIR": str(FIXTURES_DIR), "ZOT_FORMAT": ""}
    if env:
        base_env.update(env)
    return runner.invoke(main, args, env=base_env)


def test_embedding_download_dry_run_json():
    result = _run(["embedding", "download", "--dry-run"])
    assert result.exit_code == EXIT_OK
    env = json.loads(result.output)
    assert env["ok"] is True
    assert env["dry_run"] is True
    assert env["data"]["provider"] == "sentence_transformers"
    assert env["data"]["model"] == "BAAI/bge-m3"


def test_embedding_download_calls_provider(tmp_path):
    with patch("zotero_cli_agent.commands.embedding.SentenceTransformersProvider.download") as download:
        result = _run(
            ["embedding", "download", "local-model", "--cache-dir", str(tmp_path)],
            env={"ZOT_EMBEDDING_PROVIDER": "sentence_transformers", "ZOT_EMBEDDING_HF_TOKEN": "hf-secret"},
        )

    assert result.exit_code == EXIT_OK
    download.assert_called_once()
    env = json.loads(result.output)
    assert env["data"]["model"] == "local-model"
    assert env["data"]["cache_dir"] == str(tmp_path.resolve())
    assert env["data"]["hf_token_set"] is True
    assert "hf-secret" not in result.output


def test_embedding_download_schema_visible():
    result = _run(["schema", "embedding", "download"])
    assert result.exit_code == EXIT_OK
    env = json.loads(result.output)
    assert env["data"]["name"] == "embedding download"
    assert env["data"]["safety_tier"] == "read"
