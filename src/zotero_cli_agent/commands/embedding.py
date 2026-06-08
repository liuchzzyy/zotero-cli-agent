from __future__ import annotations

import json
from pathlib import Path

import click

from zotero_cli_agent.config import load_embedding_config
from zotero_cli_agent.core.providers.sentence_transformers import DEFAULT_MODEL, SentenceTransformersProvider
from zotero_cli_agent.exit_codes import emit_error
from zotero_cli_agent.formatter import envelope_ok


@click.group("embedding")
def embedding_group() -> None:
    """Manage local embedding models."""
    pass


@embedding_group.command("download")
@click.argument("model", required=False)
@click.option("--cache-dir", type=click.Path(file_okay=False), default=None, help="Directory for local model cache.")
@click.option("--dry-run", is_flag=True, help="Show what would be downloaded without writing model files.")
@click.pass_context
def embedding_download(ctx: click.Context, model: str | None, cache_dir: str | None, dry_run: bool) -> None:
    """Download a sentence-transformers model into the local cache."""
    output_json = ctx.obj.get("json", False) if ctx.obj else False
    cfg = load_embedding_config(apply_env_overrides=True)
    configured_local_model = cfg.model if cfg.provider == "sentence_transformers" else ""
    model_name = model or configured_local_model or DEFAULT_MODEL
    resolved_cache = Path(cache_dir).expanduser().resolve() if cache_dir else None
    provider = SentenceTransformersProvider(model=model_name, cache_dir=resolved_cache, hf_token=cfg.hf_token)
    data = {
        "provider": "sentence_transformers",
        "model": model_name,
        "cache_dir": str(provider.cache_dir),
        "hf_token_set": bool(cfg.hf_token),
        "dry_run": dry_run,
    }

    if dry_run:
        if output_json:
            click.echo(json.dumps(envelope_ok(data, extra={"dry_run": True}), indent=2, ensure_ascii=False))
        else:
            click.echo(f"Would download model: {model_name}")
            click.echo(f"Cache dir: {provider.cache_dir}")
        return

    try:
        provider.download()
    except RuntimeError as exc:
        emit_error(
            "configuration_error",
            str(exc),
            output_json=output_json,
            hint=(
                "Install local embedding dependencies with: "
                "uv sync --dev --extra mcp --extra local-embeddings-cpu "
                "or --extra local-embeddings-gpu"
            ),
            context="embedding download",
        )
    except Exception as exc:
        emit_error(
            "network_error",
            f"Could not download model '{model_name}': {exc}",
            output_json=output_json,
            retryable=True,
            context="embedding download",
        )

    if output_json:
        click.echo(json.dumps(envelope_ok(data), indent=2, ensure_ascii=False))
    else:
        click.echo(f"Downloaded model: {model_name}")
        click.echo(f"Cache dir: {provider.cache_dir}")
