from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import click

from zotero_cli_agent.config import (
    get_data_dir,
    get_prefs_js_path,
    load_config,
    load_embedding_config,
    load_rerank_config,
    resolve_library_id,
)
from zotero_cli_agent.core.rag import (
    bm25_score_chunks,
    build_metadata_chunk,
    chunk_text,
    compute_term_frequencies,
    convert_pdf_to_text,
    convert_pdfs_to_text,
    embed_texts,
    filter_ranked_results_by_pdf_kind,
    infer_pdf_kind,
    reciprocal_rank_fusion,
    semantic_score_chunks,
    tokenize,
)
from zotero_cli_agent.core.rag_index import RagIndex
from zotero_cli_agent.core.reader import ZoteroReader
from zotero_cli_agent.core.rerank import rerank_chunks
from zotero_cli_agent.core.workspace import (
    Workspace,
    delete_workspace,
    list_workspaces,
    load_workspace,
    save_workspace,
    validate_name,
    workspace_exists,
    workspace_index_path,
    workspaces_dir,
)
from zotero_cli_agent.exit_codes import emit_error
from zotero_cli_agent.formatter import format_items, format_workspace_list, format_workspace_query
from zotero_cli_agent.models import Collection, Item

_TEST_PATCH_SEAMS = (convert_pdf_to_text, workspaces_dir)


@click.group("workspace")
def workspace_group() -> None:
    """Manage local workspaces for organizing papers by topic."""
    pass


@workspace_group.command("new")
@click.argument("name")
@click.option("--description", "-d", default="", help="Workspace description (topic context)")
@click.pass_context
def workspace_new(ctx: click.Context, name: str, description: str) -> None:
    """Create a new workspace."""
    json_out = ctx.obj.get("json", False)
    if not validate_name(name):
        emit_error(
            "validation_error",
            f"Invalid workspace name: '{name}'",
            output_json=json_out,
            hint="Use kebab-case (e.g., llm-safety, protein-folding)",
            context="workspace new",
        )
    if workspace_exists(name):
        emit_error(
            "conflict",
            f"Workspace '{name}' already exists",
            output_json=json_out,
            hint=f"Use 'zot workspace show {name}' to view it",
            context="workspace new",
        )
    ws = Workspace(
        name=name,
        created=datetime.now(timezone.utc).isoformat(),
        description=description,
    )
    save_workspace(ws)
    click.echo(f"Workspace created: {name}")


@workspace_group.command("delete")
@click.argument("name")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def workspace_delete(ctx: click.Context, name: str, yes: bool) -> None:
    """Delete a workspace."""
    json_out = ctx.obj.get("json", False)
    if not workspace_exists(name):
        emit_error(
            "not_found",
            f"Workspace '{name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace list' to see available workspaces",
            context="workspace delete",
        )
    no_interaction = ctx.obj.get("no_interaction", False)
    if not yes and not no_interaction:
        if not click.confirm(f"Delete workspace '{name}'?"):
            click.echo("Cancelled.")
            return
    delete_workspace(name)
    click.echo(f"Workspace deleted: {name}")


@workspace_group.command("add")
@click.argument("name")
@click.argument("keys", nargs=-1, required=True)
@click.pass_context
def workspace_add(ctx: click.Context, name: str, keys: tuple[str, ...]) -> None:
    """Add items to a workspace by Zotero key."""
    json_out = ctx.obj.get("json", False)
    if not workspace_exists(name):
        emit_error(
            "not_found",
            f"Workspace '{name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace new' to create it first",
            context="workspace add",
        )

    cfg = load_config(profile=ctx.obj.get("profile"))
    data_dir = get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    library_id = resolve_library_id(db_path, ctx.obj)
    reader = ZoteroReader(db_path, library_id=library_id)
    try:
        ws = load_workspace(name)
        added = 0
        for key in keys:
            item = reader.get_item(key)
            if item is None:
                click.echo(f"Warning: item '{key}' not found in Zotero library, skipped")
                continue
            if ws.add_item(key, item.title):
                added += 1
            else:
                click.echo(f"Skipped: '{key}' already in workspace")
        save_workspace(ws)
        click.echo(f"Added {added} item(s) to workspace '{name}'")
    finally:
        reader.close()


@workspace_group.command("remove")
@click.argument("name")
@click.argument("keys", nargs=-1, required=True)
@click.pass_context
def workspace_remove(ctx: click.Context, name: str, keys: tuple[str, ...]) -> None:
    """Remove items from a workspace by key."""
    json_out = ctx.obj.get("json", False)
    if not workspace_exists(name):
        emit_error(
            "not_found",
            f"Workspace '{name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace list' to see available workspaces",
            context="workspace remove",
        )
    ws = load_workspace(name)
    removed = 0
    for key in keys:
        if ws.remove_item(key):
            removed += 1
    save_workspace(ws)
    click.echo(f"Removed {removed} item(s) from workspace '{name}'")


@workspace_group.command("list")
@click.pass_context
def workspace_list(ctx: click.Context) -> None:
    """List all workspaces."""
    json_out = ctx.obj.get("json", False)
    workspaces = list_workspaces()
    if not workspaces:
        click.echo("No workspaces found. Create one with: zot workspace new <name>")
        return
    click.echo(format_workspace_list(workspaces, output_json=json_out))


@workspace_group.command("show")
@click.argument("name")
@click.pass_context
def workspace_show(ctx: click.Context, name: str) -> None:
    """Show items in a workspace."""
    json_out = ctx.obj.get("json", False)
    detail = ctx.obj.get("detail", "standard")
    limit = ctx.obj.get("limit", 50)

    if not workspace_exists(name):
        emit_error(
            "not_found",
            f"Workspace '{name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace list' to see available workspaces",
            context="workspace show",
        )

    ws = load_workspace(name)
    if not ws.items:
        click.echo(f"Workspace '{name}' is empty. Use 'zot workspace add {name} KEY' to add items.")
        return

    cfg = load_config(profile=ctx.obj.get("profile"))
    data_dir = get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    library_id = resolve_library_id(db_path, ctx.obj)
    reader = ZoteroReader(db_path, library_id=library_id)
    try:
        items = []
        missing = []
        for ws_item in ws.items[:limit]:
            item = reader.get_item(ws_item.key)
            if item is not None:
                items.append(item)
            else:
                missing.append(ws_item.key)
        if items:
            click.echo(format_items(items, output_json=json_out, detail=detail))
        for key in missing:
            click.echo(f"Warning: item '{key}' not found in Zotero library (may have been deleted)")
    finally:
        reader.close()


@workspace_group.command("export")
@click.argument("name")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "markdown", "bibtex"]),
    default="markdown",
    help="Export format (default: markdown)",
)
@click.pass_context
def workspace_export(ctx: click.Context, name: str, fmt: str) -> None:
    """Export workspace items for external use."""
    json_out = ctx.obj.get("json", False)
    if not workspace_exists(name):
        emit_error(
            "not_found",
            f"Workspace '{name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace list' to see available workspaces",
            context="workspace export",
        )

    ws = load_workspace(name)
    if not ws.items:
        click.echo(f"Workspace '{name}' is empty.")
        return

    cfg = load_config(profile=ctx.obj.get("profile"))
    data_dir = get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    library_id = resolve_library_id(db_path, ctx.obj)
    reader = ZoteroReader(db_path, library_id=library_id)
    try:
        items = []
        for ws_item in ws.items:
            item = reader.get_item(ws_item.key)
            if item is not None:
                items.append(item)

        if not items:
            click.echo("No items could be resolved from Zotero library.")
            return

        if fmt == "json":
            click.echo(format_items(items, output_json=True))
        elif fmt == "bibtex":
            entries = []
            for item in items:
                bib = reader.export_citation(item.key, fmt="bibtex")
                if bib:
                    entries.append(bib)
            click.echo("\n\n".join(entries))
        else:
            # markdown (default)
            lines = [f"# Workspace: {name}"]
            desc_part = f" {ws.description}" if ws.description else ""
            lines.append(f"> {desc_part.strip()} ({len(items)} items)")
            lines.append("")
            for i, item in enumerate(items, 1):
                lines.append("---")
                lines.append(f"## {i}. {item.title}")
                authors = ", ".join(c.full_name for c in item.creators[:3])
                if len(item.creators) > 3:
                    authors += " et al."
                year = item.date or "N/A"
                lines.append(f"**Authors:** {authors} | **Year:** {year} | **Key:** {item.key}")
                if item.tags:
                    lines.append(f"**Tags:** {', '.join(item.tags)}")
                if item.abstract:
                    lines.append(f"**Abstract:** {item.abstract}")
                lines.append("")
            click.echo("\n".join(lines))
    finally:
        reader.close()


@workspace_group.command("import")
@click.argument("name")
@click.option("--collection", default=None, help="Import all items from a Zotero collection (name or key)")
@click.option("--tag", default=None, help="Import all items with this tag")
@click.option("--search", "search_query", default=None, help="Import items matching a search query")
@click.pass_context
def workspace_import_cmd(
    ctx: click.Context, name: str, collection: str | None, tag: str | None, search_query: str | None
) -> None:
    """Bulk import items into a workspace from collection, tag, or search."""
    json_out = ctx.obj.get("json", False)
    if not workspace_exists(name):
        emit_error(
            "not_found",
            f"Workspace '{name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace new' to create it first",
            context="workspace import",
        )

    if not collection and not tag and not search_query:
        emit_error(
            "validation_error",
            "Must specify at least one of --collection, --tag, or --search",
            output_json=json_out,
            hint="Example: zot workspace import my-ws --search 'attention'",
            context="workspace import",
        )

    cfg = load_config(profile=ctx.obj.get("profile"))
    data_dir = get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    library_id = resolve_library_id(db_path, ctx.obj)
    reader = ZoteroReader(db_path, library_id=library_id)
    try:
        ws = load_workspace(name)
        items_to_import: list[Item] = []

        if collection:
            # Resolve collection name to key
            col_key = _resolve_collection_key(reader, collection)
            if col_key is None:
                emit_error(
                    "not_found",
                    f"Collection '{collection}' not found",
                    output_json=json_out,
                    hint="Use 'zot collections' to list available collections",
                    context="workspace import",
                )
            items_to_import.extend(reader.get_collection_items(col_key))

        if tag:
            # Search specifically for items with this tag
            result = reader.search(tag, limit=500)
            for item in result.items:
                if tag.lower() in [t.lower() for t in item.tags]:
                    items_to_import.append(item)

        if search_query:
            result = reader.search(search_query, limit=500)
            items_to_import.extend(result.items)

        # Dedup by key
        seen: set[str] = set()
        unique_items: list[Item] = []
        for item in items_to_import:
            if item.key not in seen:
                seen.add(item.key)
                unique_items.append(item)

        added = 0
        skipped = 0
        for item in unique_items:
            if ws.add_item(item.key, item.title):
                added += 1
            else:
                skipped += 1

        save_workspace(ws)
        click.echo(
            f"Imported {added} item(s) into workspace '{name}'"
            + (f" ({skipped} skipped, already present)" if skipped else "")
        )
    finally:
        reader.close()


@workspace_group.command("search")
@click.argument("query")
@click.option("--workspace", "ws_name", required=True, help="Workspace to search")
@click.pass_context
def workspace_search(ctx: click.Context, query: str, ws_name: str) -> None:
    """Search items within a workspace by title, author, or abstract."""
    json_out = ctx.obj.get("json", False)
    detail = ctx.obj.get("detail", "standard")
    limit = ctx.obj.get("limit", 50)

    if not workspace_exists(ws_name):
        emit_error(
            "not_found",
            f"Workspace '{ws_name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace list' to see available workspaces",
            context="workspace search",
        )

    ws = load_workspace(ws_name)
    if not ws.items:
        click.echo(f"Workspace '{ws_name}' is empty.")
        return

    cfg = load_config(profile=ctx.obj.get("profile"))
    data_dir = get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    library_id = resolve_library_id(db_path, ctx.obj)
    reader = ZoteroReader(db_path, library_id=library_id)
    try:
        query_lower = query.lower()
        matches = []
        for ws_item in ws.items:
            item = reader.get_item(ws_item.key)
            if item is None:
                continue
            # Case-insensitive substring match across title, authors, abstract, tags
            searchable = " ".join(
                filter(
                    None,
                    [
                        item.title,
                        " ".join(c.full_name for c in item.creators),
                        item.abstract or "",
                        " ".join(item.tags),
                    ],
                )
            ).lower()
            if query_lower in searchable:
                matches.append(item)

        if not matches:
            click.echo("No matching items found.")
            return

        click.echo(format_items(matches[:limit], output_json=json_out, detail=detail))
    finally:
        reader.close()


def _resolve_collection_key(reader: ZoteroReader, name_or_key: str) -> str | None:
    """Resolve a collection name or key to a collection key."""
    collections = reader.get_collections()

    def _search(colls: list[Collection]) -> str | None:
        for c in colls:
            if c.key == name_or_key or c.name.lower() == name_or_key.lower():
                return c.key
            found = _search(c.children)
            if found:
                return found
        return None

    return _search(collections)


@workspace_group.command("index")
@click.argument("name")
@click.option("--force", is_flag=True, help="Rebuild index from scratch")
@click.option("--extractor", default=None, help="PDF text extractor to use. Defaults to the configured MinerU extractor.")
@click.option("--progress-lines", is_flag=True, help="Write progress as newline records for log-friendly real-time output.")
@click.option("--item-progress", is_flag=True, help="Index and commit one workspace item at a time with per-item progress.")
@click.option("--no-embed", is_flag=True, help="Skip embedding generation during indexing; use workspace embed later.")
@click.pass_context
def workspace_index(
    ctx: click.Context,
    name: str,
    force: bool,
    extractor: str | None,
    progress_lines: bool,
    item_progress: bool,
    no_embed: bool,
) -> None:
    """Build RAG index for a workspace."""
    json_out = ctx.obj.get("json", False)
    if extractor is None:
        from zotero_cli_agent.config import load_pdf_config

        extractor = load_pdf_config().extractor
    if not workspace_exists(name):
        emit_error(
            "not_found",
            f"Workspace '{name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace list' to see available workspaces",
            context="workspace index",
        )

    ws = load_workspace(name)
    if not ws.items:
        click.echo(f"Workspace '{name}' is empty. Add items first with: zot workspace add {name} KEY")
        return

    cfg = load_config(profile=ctx.obj.get("profile"))
    data_dir = get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    library_id = resolve_library_id(db_path, ctx.obj)
    reader = ZoteroReader(db_path, library_id=library_id, prefs_js_path=get_prefs_js_path(cfg))

    idx_path = workspace_index_path(name)
    idx = RagIndex(idx_path)

    try:
        if force:
            idx.clear()

        already_indexed = idx.get_indexed_keys()
        to_index = [item for item in ws.items if item.key not in already_indexed]

        if not to_index:
            click.echo(f"Index for '{name}' is up to date ({len(already_indexed)} item(s) indexed).")
            return

        t0 = time.monotonic()

        def progress_message(phase: str, current: int, total: int, pages: int = 0) -> str:
            percent = (current / total * 100) if total else 0.0
            page_text = f" pages={pages}" if pages else ""
            elapsed = time.monotonic() - t0
            return f"  [{phase}] {current}/{total} ({percent:.1f}%){page_text} elapsed={elapsed:.1f}s"

        def emit_progress_line(phase: str, current: int, total: int, pages: int = 0) -> None:
            click.echo(progress_message(phase, current, total, pages))

        def emit_progress_status(phase: str, current: int, total: int, pages: int = 0) -> None:
            sys.stderr.write(f"\r{' ' * 100}\r{progress_message(phase, current, total, pages)}")
            sys.stderr.flush()

        def emit_progress(phase: str, current: int, total: int, pages: int = 0) -> None:
            if progress_lines:
                emit_progress_line(phase, current, total, pages)
            else:
                emit_progress_status(phase, current, total, pages)

        def clear_progress_status() -> None:
            if not progress_lines:
                sys.stderr.write(f"\r{' ' * 100}\r")
                sys.stderr.flush()

        def update_index_meta() -> None:
            row = idx._conn.execute("SELECT COUNT(*), COALESCE(AVG(doc_len), 1.0) FROM chunks").fetchone()
            total_docs = int(row[0] or 0)
            avg_doc_len = float(row[1] or 1.0)
            idx._conn.executemany(
                "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
                [
                    ("total_docs", str(total_docs)),
                    ("avg_doc_len", str(avg_doc_len)),
                    ("chunk_count", str(total_docs)),
                    ("indexed_at", datetime.now(timezone.utc).isoformat()),
                ],
            )
            idx.commit()

        def compact_title(value: str, limit: int = 90) -> str:
            cleaned = " ".join(value.split())
            return cleaned if len(cleaned) <= limit else cleaned[: limit - 3] + "..."

        if item_progress:
            emb_cfg = None if no_embed else load_embedding_config(apply_env_overrides=True)
            mode_label = "BM25 + embeddings" if emb_cfg and emb_cfg.is_configured else "BM25"
            indexed_items = 0
            total_chunks = 0
            pdf_error_count = 0

            click.echo(f"  Indexing {len(to_index)} item(s) one by one with {extractor}...")

            for item_idx, ws_item in enumerate(to_index, 1):
                item_t0 = time.monotonic()
                item = reader.get_item(ws_item.key)
                if item is None:
                    click.echo(f"  [item:skip] {item_idx}/{len(to_index)} key={ws_item.key} reason=not_found")
                    continue

                click.echo(
                    f"  [item:start] {item_idx}/{len(to_index)} key={ws_item.key} title=\"{compact_title(item.title)}\"",
                )

                local_pdf_refs: list[tuple[str, str, Path]] = []
                for att in reader.get_pdf_attachments(ws_item.key):
                    if att.path is None or not att.path.exists():
                        continue
                    local_pdf_refs.append((att.key, att.filename or att.key, att.path))

                note_refs: list[tuple[str, str]] = []
                for note in reader.get_notes(ws_item.key):
                    if note.content.strip():
                        note_refs.append((note.key, note.content))

                pdf_texts: dict[Path, str | Exception] = {}
                unique_paths = list(dict.fromkeys(path for _, _, path in local_pdf_refs))
                if unique_paths:

                    def item_pdf_progress(phase: str, current: int, total: int, pages: int) -> None:
                        emit_progress(f"item:{item_idx}:extract:{phase}", current, total, pages)

                    pdf_texts.update(convert_pdfs_to_text(unique_paths, extractor, item_pdf_progress))
                    clear_progress_status()

                item_chunks: list[tuple[str, str, str, int]] = []
                authors = ", ".join(c.full_name for c in item.creators)
                meta_text = build_metadata_chunk(item.title, authors, item.abstract, item.tags)
                item_chunks.append((ws_item.key, "metadata", meta_text, len(tokenize(meta_text))))

                for note_key, note_content in note_refs:
                    note_text = f"Title: {item.title}\nNote Key: {note_key}\nContent:\n{note_content}"
                    item_chunks.append((ws_item.key, f"note:{note_key}", note_text, len(tokenize(note_text))))

                item_pdf_errors = 0
                for att_key, pdf_name, pdf_path in local_pdf_refs:
                    pdf_text_or_err = pdf_texts.get(pdf_path)
                    if isinstance(pdf_text_or_err, Exception):
                        pdf_error_count += 1
                        item_pdf_errors += 1
                        click.echo(f"  [item:pdf-error] key={ws_item.key} pdf=\"{pdf_name}\" error={pdf_text_or_err}")
                        continue
                    if not isinstance(pdf_text_or_err, str) or not pdf_text_or_err.strip():
                        continue
                    pdf_kind = infer_pdf_kind(pdf_text_or_err, pdf_name)
                    labeled_title = f"{item.title} | PDF: {pdf_name} | Attachment: {att_key} | Kind: {pdf_kind}"
                    for chunk_content in chunk_text(pdf_text_or_err, labeled_title):
                        item_chunks.append(
                            (
                                ws_item.key,
                                f"pdf:{pdf_kind}:{att_key}:{pdf_name}",
                                chunk_content,
                                len(tokenize(chunk_content)),
                            )
                        )

                chunk_texts = [content for _, _, content, _ in item_chunks]
                vectors: list[list[float]] = []
                item_mode_label = "BM25"
                if emb_cfg and emb_cfg.is_configured and chunk_texts:

                    def item_emb_progress(done: int, total: int) -> None:
                        emit_progress(f"item:{item_idx}:embed", done, total)

                    try:
                        vectors = embed_texts(chunk_texts, emb_cfg, item_emb_progress) or []
                        if vectors:
                            item_mode_label = "BM25 + embeddings"
                    except Exception as e:
                        click.echo(f"  [WARN] Embedding failed for {ws_item.key}: {e}", err=True)
                    clear_progress_status()

                chunk_ids: list[int] = []
                for key, chunk_type, content, doc_len in item_chunks:
                    chunk_id = idx.insert_chunk_no_commit(key, chunk_type, content, doc_len)
                    idx.insert_bm25_terms_no_commit(chunk_id, compute_term_frequencies(tokenize(content)))
                    chunk_ids.append(chunk_id)
                if vectors:
                    idx.set_embeddings_bulk_no_commit(chunk_ids, vectors)
                idx.commit()
                update_index_meta()

                indexed_items += 1
                total_chunks += len(item_chunks)
                click.echo(
                    "  [item:done] "
                    f"{item_idx}/{len(to_index)} key={ws_item.key} chunks={len(item_chunks)} "
                    f"pdfs={len(local_pdf_refs)} pdf_errors={item_pdf_errors} mode={item_mode_label} "
                    f"item_elapsed={time.monotonic() - item_t0:.1f}s elapsed={time.monotonic() - t0:.1f}s",
                )

            elapsed = time.monotonic() - t0
            click.echo(
                f"Indexed {indexed_items} item(s) ({total_chunks} chunks, {pdf_error_count} PDF errors) "
                f"in {elapsed:.1f}s [{mode_label}]"
            )
            return

        item_map: dict[str, Item] = {}
        pdf_refs: dict[str, list[tuple[str, str, Path]]] = {}
        unique_pdf_paths: dict[Path, None] = {}
        notes_map: dict[str, list[tuple[str, str]]] = {}

        for ws_item in to_index:
            item = reader.get_item(ws_item.key)
            if item is None:
                click.echo(f"Warning: item '{ws_item.key}' not found in Zotero, skipped")
                continue
            item_map[ws_item.key] = item
            pdf_attachments = reader.get_pdf_attachments(ws_item.key)
            if pdf_attachments:
                refs: list[tuple[str, str, Path]] = []
                for att in pdf_attachments:
                    if att.path is None or not att.path.exists():
                        continue
                    refs.append((att.key, att.filename or att.key, att.path))
                    unique_pdf_paths[att.path] = None
                if refs:
                    pdf_refs[ws_item.key] = refs

            batch_note_refs: list[tuple[str, str]] = []
            for note in reader.get_notes(ws_item.key):
                if note.content.strip():
                    batch_note_refs.append((note.key, note.content))
            if batch_note_refs:
                notes_map[ws_item.key] = batch_note_refs

        batch_pdf_texts: dict[Path, str | Exception] = {}
        pdf_errors: list[tuple[str, str, Exception]] = []

        if unique_pdf_paths:
            unique_paths = list(unique_pdf_paths.keys())
            click.echo(f"  Extracting {len(unique_paths)} PDF attachment(s) with {extractor}...")

            def batch_progress(phase: str, current: int, total: int, pages: int) -> None:
                emit_progress(f"extract:{phase}", current, total, pages)

            if len(unique_paths) == 1:
                single_path = unique_paths[0]
                try:
                    batch_pdf_texts[single_path] = convert_pdf_to_text(single_path, extractor, batch_progress)
                except Exception as e:
                    batch_pdf_texts[single_path] = e
            else:
                batch_results = convert_pdfs_to_text(unique_paths, extractor, batch_progress)
                batch_pdf_texts.update(batch_results)
            clear_progress_status()

        # PHASE 2 — Chunk all texts
        click.echo(f"  Chunking {len(to_index)} item(s)...")

        all_chunks: list[tuple[str, str, str, int]] = []  # (key, type, content, doc_len)

        for ws_item in to_index:
            item = item_map.get(ws_item.key)
            if item is None:
                continue

            authors = ", ".join(c.full_name for c in item.creators)
            meta_text = build_metadata_chunk(item.title, authors, item.abstract, item.tags)
            meta_tokens = len(tokenize(meta_text))
            all_chunks.append((ws_item.key, "metadata", meta_text, meta_tokens))

            for note_key, note_content in notes_map.get(ws_item.key, []):
                note_text = f"Title: {item.title}\nNote Key: {note_key}\nContent:\n{note_content}"
                note_tokens = len(tokenize(note_text))
                all_chunks.append((ws_item.key, f"note:{note_key}", note_text, note_tokens))

            for att_key, pdf_name, pdf_path in pdf_refs.get(ws_item.key, []):
                pdf_text_or_err = batch_pdf_texts.get(pdf_path)
                if isinstance(pdf_text_or_err, Exception):
                    pdf_errors.append((ws_item.key, pdf_name, pdf_text_or_err))
                    continue
                if not isinstance(pdf_text_or_err, str) or not pdf_text_or_err.strip():
                    continue
                pdf_kind = infer_pdf_kind(pdf_text_or_err, pdf_name)
                labeled_title = f"{item.title} | PDF: {pdf_name} | Attachment: {att_key} | Kind: {pdf_kind}"
                for chunk_content in chunk_text(pdf_text_or_err, labeled_title):
                    chunk_tokens = len(tokenize(chunk_content))
                    all_chunks.append((ws_item.key, f"pdf:{pdf_kind}:{att_key}:{pdf_name}", chunk_content, chunk_tokens))

        # PHASE 3 — Index all chunks (bulk insert, single commit)
        click.echo(f"  Indexing {len(all_chunks)} chunk(s)...")

        all_chunk_ids: list[int] = []
        all_chunk_texts: list[str] = []

        for i, (key, chunk_type, content, doc_len) in enumerate(all_chunks, 1):
            if i % 500 == 0 or i == len(all_chunks):
                emit_progress("index", i, len(all_chunks))

            chunk_id = idx.insert_chunk_no_commit(key, chunk_type, content, doc_len)
            tfs = compute_term_frequencies(tokenize(content))
            idx.insert_bm25_terms_no_commit(chunk_id, tfs)
            all_chunk_ids.append(chunk_id)
            all_chunk_texts.append(content)

        idx.commit()
        clear_progress_status()

        # Report extraction errors at end
        if pdf_errors:
            click.echo(f"\nWarning: {len(pdf_errors)} PDF extraction(s) failed:")
            for key, pdf_name, exc in pdf_errors:
                click.echo(f"  - {key} ({pdf_name}): {exc}")

        total_chunks = len(all_chunks)
        all_indexed_chunks = idx.get_all_chunks()
        total_docs = len(all_indexed_chunks)
        if total_docs > 0:
            total_len = sum(c.get("doc_len", 0) or len(tokenize(c["content"])) for c in all_indexed_chunks)
            avg_doc_len = total_len / total_docs
        else:
            avg_doc_len = 1.0
        idx.set_meta("total_docs", str(total_docs))
        idx.set_meta("avg_doc_len", str(avg_doc_len))
        idx.set_meta("chunk_count", str(total_docs))
        idx.set_meta("indexed_at", datetime.now(timezone.utc).isoformat())

        # Embeddings if configured
        mode_label = "BM25"
        emb_cfg = None if no_embed else load_embedding_config(apply_env_overrides=True)
        if emb_cfg and emb_cfg.is_configured and all_chunk_texts:
            click.echo("  Generating embeddings...")

            def emb_progress(done: int, total: int) -> None:
                emit_progress("embed", done, total)

            try:
                bulk_vectors = embed_texts(all_chunk_texts, emb_cfg, emb_progress)
                if bulk_vectors:
                    idx.set_embeddings_bulk(all_chunk_ids, bulk_vectors)
                    mode_label = "BM25 + embeddings"
            except Exception as e:
                click.echo(f"  [WARN] Embedding failed: {e}", err=True)
            clear_progress_status()

        elapsed = time.monotonic() - t0
        click.echo(f"Indexed {len(to_index)} item(s) ({total_chunks} chunks) in {elapsed:.1f}s [{mode_label}]")
    finally:
        idx.close()
        reader.close()


@workspace_group.command("embed")
@click.argument("name")
@click.option("--batch-size", default=100, show_default=True, help="Number of existing chunks to attempt per commit.")
@click.option("--limit", default=0, show_default=True, help="Maximum chunks to attempt in this run; 0 means all missing.")
@click.option("--max-retries", default=5, show_default=True, help="Retry a failed provider batch this many times.")
@click.option("--retry-sleep", default=10.0, show_default=True, help="Initial seconds to sleep between batch retries.")
@click.option(
    "--heartbeat-seconds",
    default=15.0,
    show_default=True,
    help="Seconds between provider wait progress lines when --progress-lines is set; 0 disables wait heartbeats.",
)
@click.option(
    "--device",
    default="",
    help="Override local sentence-transformers device, e.g. cpu, cuda, cuda:0, or auto.",
)
@click.option("--progress-lines", is_flag=True, help="Write progress as newline records for log-friendly real-time output.")
@click.pass_context
def workspace_embed(
    ctx: click.Context,
    name: str,
    batch_size: int,
    limit: int,
    max_retries: int,
    retry_sleep: float,
    heartbeat_seconds: float,
    device: str,
    progress_lines: bool,
) -> None:
    """Backfill embeddings for an existing workspace RAG index."""
    json_out = ctx.obj.get("json", False)
    if not workspace_exists(name):
        emit_error(
            "not_found",
            f"Workspace '{name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace list' to see available workspaces",
            context="workspace embed",
        )

    idx_path = workspace_index_path(name)
    if not idx_path.exists():
        emit_error(
            "not_found",
            f"No index found for workspace '{name}'",
            output_json=json_out,
            hint=f"Run 'zot workspace index {name}' first",
            context="workspace embed",
        )

    if batch_size <= 0:
        emit_error(
            "validation_error",
            "--batch-size must be greater than 0",
            output_json=json_out,
            context="workspace embed",
        )
    if limit < 0:
        emit_error(
            "validation_error",
            "--limit must be 0 or greater",
            output_json=json_out,
            context="workspace embed",
        )
    if max_retries < 0:
        emit_error(
            "validation_error",
            "--max-retries must be 0 or greater",
            output_json=json_out,
            context="workspace embed",
        )
    if retry_sleep < 0:
        emit_error(
            "validation_error",
            "--retry-sleep must be 0 or greater",
            output_json=json_out,
            context="workspace embed",
        )
    if heartbeat_seconds < 0:
        emit_error(
            "validation_error",
            "--heartbeat-seconds must be 0 or greater",
            output_json=json_out,
            context="workspace embed",
        )

    emb_cfg = load_embedding_config(apply_env_overrides=True)
    if device:
        emb_cfg.device = device
    if not emb_cfg.is_configured:
        emit_error(
            "configuration_error",
            "Embedding provider is not configured",
            output_json=json_out,
            hint="Set [embedding].api_key in .zot/config.toml or ZOT_EMBEDDING_KEY",
            context="workspace embed",
        )

    idx = RagIndex(idx_path)
    t0 = time.monotonic()
    try:
        missing = idx.count_missing_embeddings()
        if missing == 0:
            click.echo(f"Embeddings for '{name}' are already complete.")
            return

        target = min(missing, limit) if limit else missing
        attempted = 0
        stored = 0
        skipped = 0
        after_id = 0
        expected_dim: int | None = None

        click.echo(
            f"Backfilling embeddings for '{name}': missing={missing} target={target} "
            f"provider={emb_cfg.provider} model={emb_cfg.model} "
            f"device={emb_cfg.device} provider_batch_size={emb_cfg.batch_size}"
        )

        def emit_progress_line(message: str, *, err: bool = False) -> None:
            click.echo(message, err=err)
            (sys.stderr if err else sys.stdout).flush()

        def emit_status(done: int, total: int, last_id: int) -> None:
            elapsed = time.monotonic() - t0
            rate = done / elapsed if elapsed > 0 else 0.0
            remaining = max(total - done, 0)
            eta = remaining / rate if rate > 0 else 0.0
            message = (
                f"  [embed] attempted={done}/{total} stored={stored} skipped={skipped} "
                f"last_id={last_id} rate={rate:.2f}/s eta={eta:.1f}s"
            )
            if progress_lines:
                emit_progress_line(message)
            else:
                sys.stderr.write(f"\r{' ' * 140}\r{message}")
                sys.stderr.flush()

        def run_with_wait_heartbeat(
            call: Callable[[], list[list[float]] | None],
            *,
            event: str,
            chunk_ids: list[int],
            count: int,
            attempt_no: int,
            attempt_total: int,
        ) -> tuple[list[list[float]] | None, float]:
            first_id = chunk_ids[0]
            last_id = chunk_ids[-1]
            started = time.monotonic()
            if progress_lines:
                emit_progress_line(
                    f"  [{event}:start] attempted={attempted}/{target} stored={stored} skipped={skipped} "
                    f"first_chunk_id={first_id} last_chunk_id={last_id} count={count} "
                    f"attempt={attempt_no}/{attempt_total}"
                )

            result_holder: dict[str, list[list[float]] | None] = {}
            exception_holder: dict[str, BaseException] = {}

            def worker() -> None:
                try:
                    result_holder["result"] = call()
                except BaseException as exc:
                    exception_holder["exception"] = exc

            worker_thread = threading.Thread(
                target=worker,
                name=f"zot-{event}-provider",
                daemon=True,
            )
            worker_thread.start()

            if progress_lines and heartbeat_seconds > 0:
                while worker_thread.is_alive():
                    worker_thread.join(timeout=heartbeat_seconds)
                    if worker_thread.is_alive():
                        elapsed = time.monotonic() - started
                        emit_progress_line(
                            f"  [{event}:wait] attempted={attempted}/{target} stored={stored} skipped={skipped} "
                            f"first_chunk_id={first_id} last_chunk_id={last_id} count={count} "
                            f"attempt={attempt_no}/{attempt_total} provider_elapsed={elapsed:.1f}s"
                        )
            else:
                worker_thread.join()

            if "exception" in exception_holder:
                raise exception_holder["exception"]

            elapsed = time.monotonic() - started
            return result_holder.get("result"), elapsed

        def embed_batch_with_retries(texts: list[str], chunk_ids: list[int]) -> list[list[float]]:
            for attempt_no in range(max_retries + 1):
                provider_attempt = attempt_no + 1

                def provider_progress(done: int, provider_total: int) -> None:
                    if progress_lines:
                        emit_progress_line(
                            f"  [embed:provider] attempted={attempted}/{target} stored={stored} skipped={skipped} "
                            f"first_chunk_id={chunk_ids[0]} provider_done={done}/{provider_total} "
                            f"attempt={provider_attempt}/{max_retries + 1}"
                        )

                vectors_or_none, provider_elapsed = run_with_wait_heartbeat(
                    lambda: embed_texts(texts, emb_cfg, provider_progress),
                    event="embed",
                    chunk_ids=chunk_ids,
                    count=len(texts),
                    attempt_no=provider_attempt,
                    attempt_total=max_retries + 1,
                )
                if vectors_or_none is not None:
                    if len(vectors_or_none) < len(texts):
                        vectors_or_none.extend([[] for _ in range(len(texts) - len(vectors_or_none))])
                    if progress_lines:
                        emit_progress_line(
                            f"  [embed:done] first_chunk_id={chunk_ids[0]} last_chunk_id={chunk_ids[-1]} "
                            f"count={len(texts)} returned={len(vectors_or_none)} elapsed={provider_elapsed:.1f}s "
                            f"attempt={provider_attempt}/{max_retries + 1}"
                        )
                    return vectors_or_none[: len(texts)]
                if attempt_no < max_retries:
                    delay = retry_sleep * (attempt_no + 1)
                    click.echo(
                        f"  [embed:retry] first_chunk_id={chunk_ids[0]} "
                        f"attempt={attempt_no + 1}/{max_retries} sleep={delay:.1f}s",
                        err=True,
                    )
                    time.sleep(delay)

            if len(texts) == 1:
                return [[]]

            click.echo(
                f"  [embed:fallback] first_chunk_id={chunk_ids[0]} count={len(texts)} trying individual chunks",
                err=True,
            )
            vectors: list[list[float]] = []
            for chunk_id, text in zip(chunk_ids, texts):
                single_vectors: list[list[float]] | None = None
                for attempt_no in range(max_retries + 1):
                    provider_attempt = attempt_no + 1
                    single_vectors, _provider_elapsed = run_with_wait_heartbeat(
                        lambda: embed_texts([text], emb_cfg),
                        event="embed:single",
                        chunk_ids=[chunk_id],
                        count=1,
                        attempt_no=provider_attempt,
                        attempt_total=max_retries + 1,
                    )
                    if single_vectors is not None:
                        break
                    if attempt_no < max_retries and retry_sleep > 0:
                        time.sleep(retry_sleep)
                if single_vectors and single_vectors[0]:
                    vectors.append(single_vectors[0])
                else:
                    click.echo(f"  [embed:skip] chunk_id={chunk_id} reason=provider_failed", err=True)
                    vectors.append([])
            return vectors

        while attempted < target:
            rows = idx.get_chunks_missing_embeddings(after_id=after_id, limit=min(batch_size, target - attempted))
            if not rows:
                break

            chunk_ids = [int(row["id"]) for row in rows]
            texts = [str(row["content"]) for row in rows]
            vectors = embed_batch_with_retries(texts, chunk_ids)

            valid_ids: list[int] = []
            valid_vectors: list[list[float]] = []
            for chunk_id, vector in zip(chunk_ids, vectors):
                if not vector:
                    skipped += 1
                    continue
                if expected_dim is None:
                    expected_dim = len(vector)
                if len(vector) != expected_dim:
                    skipped += 1
                    continue
                valid_ids.append(chunk_id)
                valid_vectors.append(vector)

            if valid_ids:
                idx.set_embeddings_bulk_no_commit(valid_ids, valid_vectors)
                stored += len(valid_ids)

            attempted += len(rows)
            after_id = chunk_ids[-1]
            idx._conn.executemany(
                "INSERT OR REPLACE INTO index_meta (key, value) VALUES (?, ?)",
                [
                    ("embedding_provider", emb_cfg.provider),
                    ("embedding_model", emb_cfg.model),
                    ("embedding_dim", str(expected_dim or "")),
                    ("embedding_backfilled_at", datetime.now(timezone.utc).isoformat()),
                ],
            )
            idx.commit()
            emit_status(attempted, target, after_id)

        if not progress_lines:
            sys.stderr.write(f"\r{' ' * 140}\r")
            sys.stderr.flush()
        elapsed = time.monotonic() - t0
        remaining_missing = idx.count_missing_embeddings()
        click.echo(
            f"Backfilled embeddings for '{name}': attempted={attempted}, stored={stored}, "
            f"skipped={skipped}, remaining_missing={remaining_missing}, elapsed={elapsed:.1f}s"
        )
    finally:
        idx.close()


@workspace_group.command("query")
@click.argument("question")
@click.option("--workspace", "ws_name", required=True, help="Workspace to query")
@click.option("--top-k", default=5, help="Number of results (default: 5)")
@click.option(
    "--mode",
    type=click.Choice(["auto", "bm25", "semantic", "hybrid"]),
    default="auto",
    help="Retrieval mode",
)
@click.option(
    "--pdf-kind",
    type=click.Choice(["any", "main", "supplementary"]),
    default="any",
    help="Restrict PDF results to main paper or supplementary PDF chunks",
)
@click.option("--rerank", is_flag=True, help="Rerank fused retrieval candidates with the configured local reranker.")
@click.option(
    "--rerank-top-n",
    type=click.IntRange(min=1),
    default=50,
    show_default=True,
    help="Number of fused candidates to rerank.",
)
@click.pass_context
def workspace_query(
    ctx: click.Context,
    question: str,
    ws_name: str,
    top_k: int,
    mode: str,
    pdf_kind: str,
    rerank: bool,
    rerank_top_n: int,
) -> None:
    """Query workspace papers with natural language."""
    json_out = ctx.obj.get("json", False)
    if not workspace_exists(ws_name):
        emit_error(
            "not_found",
            f"Workspace '{ws_name}' not found",
            output_json=json_out,
            hint="Use 'zot workspace list' to see available workspaces",
            context="workspace query",
        )

    idx_path = workspace_index_path(ws_name)
    if not idx_path.exists():
        emit_error(
            "not_found",
            f"No index found for workspace '{ws_name}'",
            output_json=json_out,
            hint=f"Run 'zot workspace index {ws_name}' first",
            context="workspace query",
        )

    idx = RagIndex(idx_path)
    if not json_out:
        sys.stderr.write("\r    [loading index]")
        sys.stderr.flush()
    try:
        # Determine effective mode (cheap check instead of loading all embeddings)
        row = idx._conn.execute("SELECT 1 FROM chunks WHERE embedding IS NOT NULL LIMIT 1").fetchone()
        has_embeddings = row is not None
        if mode == "auto":
            effective_mode = "hybrid" if has_embeddings else "bm25"
        else:
            effective_mode = mode

        bm25_results: list[tuple[int, float, dict]] = []
        semantic_results: list[tuple[int, float, dict]] = []

        if effective_mode in ("bm25", "hybrid"):
            if json_out:
                bm25_results = bm25_score_chunks(idx, question, None)
            else:

                def bm25_progress(done: int, total: int) -> None:
                    sys.stderr.write(f"\r{' ' * 60}\r    [bm25] [{done}/{total}]")
                    sys.stdout.flush()

                bm25_results = bm25_score_chunks(idx, question, bm25_progress)

        if effective_mode in ("semantic", "hybrid") and has_embeddings:
            emb_cfg = load_embedding_config(apply_env_overrides=True)
            if emb_cfg.is_configured:
                try:
                    q_vecs = embed_texts([question], emb_cfg, input_type="query")
                    if q_vecs:
                        if json_out:
                            semantic_results = semantic_score_chunks(idx, q_vecs[0], None)
                        else:

                            def sem_progress(done: int, total: int) -> None:
                                sys.stderr.write(f"\r{' ' * 60}\r    [semantic] [{done}/{total}]")
                                sys.stdout.flush()

                            semantic_results = semantic_score_chunks(idx, q_vecs[0], sem_progress)
                except Exception:
                    pass

        if not json_out:
            sys.stderr.write(f"\r{' ' * 60}\r")
            sys.stdout.flush()

        # Merge results
        if effective_mode == "hybrid" and bm25_results and semantic_results:
            merged = reciprocal_rank_fusion(bm25_results, semantic_results)
        elif semantic_results and effective_mode in ("semantic", "hybrid"):
            merged = semantic_results
        else:
            merged = bm25_results

        filtered = filter_ranked_results_by_pdf_kind(merged, pdf_kind)
        if rerank and filtered:
            rerank_cfg = load_rerank_config(apply_env_overrides=True)
            if not rerank_cfg.is_configured:
                emit_error(
                    "configuration_error",
                    "Reranker provider is not configured",
                    output_json=json_out,
                    hint="Set [rerank].provider and [rerank].model in .zot/config.toml",
                    context="workspace query",
                )
            if not json_out:
                sys.stderr.write("\r    [rerank]")
                sys.stderr.flush()

            def rerank_progress(done: int, total: int) -> None:
                if not json_out:
                    sys.stderr.write(f"\r{' ' * 60}\r    [rerank] [{done}/{total}]")
                    sys.stderr.flush()

            reranked = rerank_chunks(
                question,
                filtered,
                rerank_cfg,
                top_n=rerank_top_n,
                progress_callback=rerank_progress if not json_out else None,
            )
            if reranked:
                filtered = reranked
                effective_mode = f"{effective_mode}+rerank"
            if not json_out:
                sys.stderr.write(f"\r{' ' * 60}\r")
                sys.stderr.flush()
        top = filtered[:top_k]

        if not top:
            if json_out:
                click.echo("[]")
            else:
                click.echo("No results found.")
            return

        click.echo(format_workspace_query(top, mode=effective_mode, output_json=json_out))
    finally:
        idx.close()
