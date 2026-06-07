from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from pyzotero import zotero

from zotero_cli_agent.commands.add import _resolve_metadata, _resolved_summary
from zotero_cli_agent.config import get_data_dir, load_config, resolve_library_id, resolve_write_credentials
from zotero_cli_agent.core.reader import ZoteroReader
from zotero_cli_agent.core.writer import SYNC_REMINDER, ZoteroWriteError, ZoteroWriter
from zotero_cli_agent.models import Collection

INBOX_UNSORTED_COLLECTION = "00_INBOX/00_UNSORTED"
AUTHOR_WATCH_ROOT_COLLECTION = "00_INBOX/10_AUTHOR_WATCH"


@dataclass
class DoiImportListRow:
    doi: str
    title: str
    journal: str | None
    entry_uids: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    tracked_authors: list[str] = field(default_factory=list)
    source_links: list[str] = field(default_factory=list)

    def merge_entry(self, entry: dict[str, Any]) -> None:
        self.entry_uids.extend(_as_unique_strings([entry.get("entry_uid")], self.entry_uids))
        self.topics.extend(_as_unique_strings([entry.get("topic")], self.topics))
        self.keywords.extend(_as_unique_strings(entry.get("keywords") or [], self.keywords))
        self.tags.extend(_as_unique_strings(entry.get("tags") or [], self.tags))
        self.tracked_authors.extend(_as_unique_strings(_extract_tracked_authors(entry.get("tags") or []), self.tracked_authors))
        self.source_links.extend(_as_unique_strings([_nested_get(entry, "source", "link")], self.source_links))

    @property
    def alert_type(self) -> str:
        return "author" if self.tracked_authors else "general"

    @property
    def target_collections(self) -> list[str]:
        if not self.tracked_authors:
            return [INBOX_UNSORTED_COLLECTION]
        targets = [INBOX_UNSORTED_COLLECTION]
        targets.extend(f"{AUTHOR_WATCH_ROOT_COLLECTION}/{author}" for author in self.tracked_authors)
        return targets

    def to_dict(self, *, already_in_library: bool) -> dict[str, Any]:
        return {
            "doi": self.doi,
            "title": self.title,
            "journal": self.journal,
            "alert_type": self.alert_type,
            "tracked_authors": self.tracked_authors,
            "target_collections": self.target_collections,
            "already_in_library": already_in_library,
            "entry_uids": self.entry_uids,
            "topics": self.topics,
            "keywords": self.keywords,
            "tags": self.tags,
            "source_links": self.source_links,
        }


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _normalize_author_name(raw: str) -> str:
    return " ".join(raw.strip().split())


def _extract_tracked_authors(tags: list[Any]) -> list[str]:
    authors: list[str] = []
    has_author_alert = any(str(tag).strip() == "alert_type:author" for tag in tags)
    for tag in tags:
        text = str(tag).strip()
        if text.startswith("tracked_author:"):
            name = _normalize_author_name(text.split(":", 1)[1])
            if name and name not in authors:
                authors.append(name)
    if not authors and has_author_alert:
        for tag in tags:
            text = str(tag).strip()
            if text.startswith("alert_key:"):
                name = _normalize_author_name(text.split(":", 1)[1])
                if name and name not in authors:
                    authors.append(name)
    return authors


def _as_unique_strings(values: list[Any], existing: list[str]) -> list[str]:
    existing_set = set(existing)
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in existing_set:
            continue
        existing_set.add(text)
        out.append(text)
    return out


def _load_selected_items(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected a top-level JSON array in {path}")
    items: list[dict[str, Any]] = []
    for row in payload:
        if isinstance(row, dict):
            items.append(row)
    return items


def _build_doi_rows(items: list[dict[str, Any]]) -> dict[str, DoiImportListRow]:
    doi_rows: dict[str, DoiImportListRow] = {}
    for entry in items:
        doi = _normalize_doi(entry.get("doi"))
        if doi is None:
            continue
        row = doi_rows.get(doi)
        if row is None:
            row = DoiImportListRow(
                doi=doi,
                title=str(entry.get("title") or "").strip(),
                journal=(str(entry.get("journal")).strip() if entry.get("journal") else None),
            )
            doi_rows[doi] = row
        row.merge_entry(entry)
    return doi_rows


def _load_library_dois_from_export(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        raise ValueError(f"Expected export JSON to contain a list under 'data': {path}")
    dois: set[str] = set()
    for row in data:
        if not isinstance(row, dict):
            continue
        doi = _normalize_doi(row.get("doi"))
        if doi:
            dois.add(doi)
    return dois


def _export_current_library(repo_root: Path, export_path: Path) -> None:
    cmd = ["uv", "run", "zot", "--json", "--detail", "full", "summarize-all"]
    result = subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to export current Zotero library via summarize-all.\n"
            f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"
        )
    export_path.write_text(result.stdout, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_rss_zotero_items_outputs(
    *,
    selected_json: Path,
    output_dir: Path,
    repo_root: Path,
    zotero_export_json: Path | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    export_path = zotero_export_json or output_dir / "zotero_before.json"
    if zotero_export_json is None:
        _export_current_library(repo_root, export_path)

    selected_items = _load_selected_items(selected_json)
    doi_rows = _build_doi_rows(selected_items)
    library_dois = _load_library_dois_from_export(export_path)

    all_doi_rows: list[dict[str, Any]] = []
    new_doi_rows: list[dict[str, Any]] = []
    root_only_dois: list[str] = []
    author_routes: dict[str, list[str]] = defaultdict(list)

    for doi in sorted(doi_rows):
        row = doi_rows[doi]
        already_in_library = doi in library_dois
        row_dict = row.to_dict(already_in_library=already_in_library)
        all_doi_rows.append(row_dict)
        if already_in_library:
            continue
        new_doi_rows.append(row_dict)
        if row.tracked_authors:
            for author in row.tracked_authors:
                author_routes[author].append(doi)
        else:
            root_only_dois.append(doi)

    all_doi_entries_path = output_dir / "all_doi_entries.json"
    new_doi_entries_path = output_dir / "new_doi_entries.json"
    new_dois_path = output_dir / "new_dois.txt"
    import_list_path = output_dir / "import_list.json"
    summary_path = output_dir / "summary.json"

    _write_json(all_doi_entries_path, all_doi_rows)
    _write_json(new_doi_entries_path, new_doi_rows)
    new_dois_path.write_text("\n".join(row["doi"] for row in new_doi_rows) + ("\n" if new_doi_rows else ""), encoding="utf-8")

    import_list = {
        "root_collection": INBOX_UNSORTED_COLLECTION,
        "root_only_dois": root_only_dois,
        "author_collections": [
            {
                "author": author,
                "collection_path": ["00_INBOX", "10_AUTHOR_WATCH", author],
                "dois": sorted(dois),
            }
            for author, dois in sorted(author_routes.items())
        ],
        "entries": new_doi_rows,
    }
    _write_json(import_list_path, import_list)

    summary = {
        "selected_json": str(selected_json),
        "zotero_export_json": str(export_path),
        "total_selected_rows": len(selected_items),
        "unique_selected_dois": len(all_doi_rows),
        "already_in_library": len(all_doi_rows) - len(new_doi_rows),
        "new_dois": len(new_doi_rows),
        "root_only_new_dois": len(root_only_dois),
        "author_routed_new_dois": sum(len(dois) for dois in author_routes.values()),
        "author_collection_count": len(author_routes),
        "output_files": {
            "all_doi_entries": str(all_doi_entries_path),
            "new_doi_entries": str(new_doi_entries_path),
            "new_dois": str(new_dois_path),
            "import_list": str(import_list_path),
            "summary": str(summary_path),
        },
    }
    _write_json(summary_path, summary)
    return summary


@dataclass
class ImportEntry:
    doi: str
    title: str
    target_collections: list[str]
    tracked_authors: list[str]


@dataclass
class KnownItemKey:
    key: str
    collections: set[str] = field(default_factory=set)
    date_added: str | None = None
    sources: set[str] = field(default_factory=set)


def _parse_library(library: str) -> dict[str, Any]:
    if library == "user":
        return {"library_type": "user", "group_id": None}
    if library.startswith("group:") and library[6:].isdigit():
        return {"library_type": "group", "group_id": library[6:]}
    raise ValueError(f"Invalid --library value: {library}. Use 'user' or 'group:<id>'.")


def _normalize_doi(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text.lower()


def _parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_import_entries(import_list_path: Path, *, limit: int | None = None) -> tuple[str, list[ImportEntry]]:
    payload = json.loads(import_list_path.read_text(encoding="utf-8"))
    root_collection = str(payload["root_collection"])
    raw_entries = payload.get("entries", [])
    entries: list[ImportEntry] = []
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        doi = _normalize_doi(raw.get("doi"))
        if not doi:
            continue
        entry = ImportEntry(
            doi=doi,
            title=str(raw.get("title") or "").strip(),
            target_collections=[str(x) for x in raw.get("target_collections") or [] if str(x).strip()],
            tracked_authors=[str(x) for x in raw.get("tracked_authors") or [] if str(x).strip()],
        )
        entries.append(entry)
        if limit is not None and len(entries) >= limit:
            break
    return root_collection, entries


def _get_reader_and_library_id(profile: str | None, library_ctx: dict[str, Any]) -> tuple[ZoteroReader, Path, int]:
    cfg = load_config(profile=profile)
    data_dir = get_data_dir(cfg)
    db_path = data_dir / "zotero.sqlite"
    library_id = resolve_library_id(db_path, library_ctx)
    return ZoteroReader(db_path, library_id=library_id), db_path, library_id


def _flatten_collections(collections: list[Collection], prefix: list[str] | None = None) -> dict[str, str]:
    prefix = prefix or []
    out: dict[str, str] = {}
    for collection in collections:
        path_parts = prefix + [collection.name]
        path = "/".join(path_parts)
        out[path] = collection.key
        out.update(_flatten_collections(collection.children, path_parts))
    return out


def _load_local_collection_paths(profile: str | None, library_ctx: dict[str, Any]) -> dict[str, str]:
    reader, _, _ = _get_reader_and_library_id(profile, library_ctx)
    try:
        collections = reader.get_collections()
        return _flatten_collections(collections)
    finally:
        reader.close()


def _build_writer(profile: str | None, library_ctx: dict[str, Any]) -> ZoteroWriter:
    cfg = load_config(profile=profile)
    library_type = library_ctx["library_type"]
    library_id, api_key = resolve_write_credentials(
        cfg,
        library_type=library_type,
        group_id=library_ctx.get("group_id"),
    )
    if not library_id or not api_key:
        raise RuntimeError("Write credentials are missing. Run 'zot config init' or fill in .zot/config.toml.")
    return ZoteroWriter(library_id=library_id, api_key=api_key, library_type=library_type)


def _build_client(profile: str | None, library_ctx: dict[str, Any]) -> zotero.Zotero:
    cfg = load_config(profile=profile)
    library_type = library_ctx["library_type"]
    library_id, api_key = resolve_write_credentials(
        cfg,
        library_type=library_type,
        group_id=library_ctx.get("group_id"),
    )
    if not library_id:
        raise RuntimeError("Read credentials are missing. Run 'zot config init' or fill in .zot/config.toml.")
    client = zotero.Zotero(library_id, library_type, api_key)
    if client.client is not None:
        client.client.timeout = httpx.Timeout(300.0)
    return client


def _ensure_collection_path(
    writer: ZoteroWriter,
    known_paths: dict[str, str],
    collection_path: str,
    *,
    apply: bool,
    created_paths: list[dict[str, str]],
) -> str:
    if collection_path in known_paths:
        return known_paths[collection_path]

    parts = [part for part in collection_path.split("/") if part]
    current_parts: list[str] = []
    parent_key: str | None = None
    for part in parts:
        current_parts.append(part)
        path = "/".join(current_parts)
        if path in known_paths:
            parent_key = known_paths[path]
            continue
        if not apply:
            key = f"DRYRUN::{path}"
        else:
            key = writer.create_collection(part, parent_key=parent_key)
        known_paths[path] = key
        created_paths.append({"path": path, "key": key})
        parent_key = key
    return known_paths[collection_path]


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"items": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"items": {}}
    if not isinstance(payload, dict):
        return {"items": {}}
    items = payload.get("items")
    if not isinstance(items, dict):
        payload["items"] = {}
    return payload


def _update_checkpoint(
    checkpoint: dict[str, Any],
    checkpoint_path: Path,
    *,
    doi: str,
    status: str,
    key: str | None = None,
    completed_collections: list[str] | None = None,
    target_collections: list[str] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    items = checkpoint.setdefault("items", {})
    entry = items.get(doi)
    if not isinstance(entry, dict):
        entry = {"doi": doi}
        items[doi] = entry
    entry["doi"] = doi
    entry["status"] = status
    if key:
        entry["key"] = key
    if completed_collections is not None:
        entry["completed_collections"] = list(completed_collections)
    if target_collections is not None:
        entry["target_collections"] = list(target_collections)
    if error is not None:
        entry["error"] = error
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint["updated_at"] = entry["updated_at"]
    _write_json_atomic(checkpoint_path, checkpoint)


def _serialize_known_items(known_items: dict[str, dict[str, KnownItemKey]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for doi in sorted(known_items):
        key_payloads = []
        union_collections: set[str] = set()
        union_sources: set[str] = set()
        for key in sorted(known_items[doi]):
            slot = known_items[doi][key]
            union_collections.update(slot.collections)
            union_sources.update(slot.sources)
            key_payloads.append(
                {
                    "key": key,
                    "collections": sorted(slot.collections),
                    "date_added": slot.date_added,
                    "sources": sorted(slot.sources),
                }
            )
        out[doi] = {
            "doi": doi,
            "keys": key_payloads,
            "all_collections": sorted(union_collections),
            "all_sources": sorted(union_sources),
        }
    return out


def _record_known_item(
    known_items: dict[str, dict[str, KnownItemKey]],
    *,
    doi: str,
    key: str,
    collections: list[str] | set[str] | None,
    date_added: str | None,
    source: str,
) -> None:
    slot = known_items.setdefault(doi, {}).get(key)
    if slot is None:
        slot = KnownItemKey(key=key)
        known_items[doi][key] = slot
    if collections:
        slot.collections.update(path for path in collections if path)
    if date_added and not slot.date_added:
        slot.date_added = date_added
    slot.sources.add(source)


def _choose_best_known_key(known_for_doi: dict[str, KnownItemKey], target_collections: list[str]) -> str:
    target_set = set(target_collections)

    def _score(item: tuple[str, KnownItemKey]) -> tuple[int, datetime, str]:
        key, meta = item
        matched = len(meta.collections & target_set)
        date_added = _parse_iso_datetime(meta.date_added) or datetime.min.replace(tzinfo=timezone.utc)
        return matched, date_added, key

    return max(known_for_doi.items(), key=_score)[0]


def _build_server_collection_maps(
    client: zotero.Zotero,
) -> tuple[dict[str, str], dict[str, str]]:
    collections = client.everything(client.collections(limit=100))
    by_key: dict[str, dict[str, str | None]] = {}
    for collection in collections:
        data = collection.get("data", {})
        key = str(collection.get("key") or data.get("key") or "")
        name = str(data.get("name") or "")
        parent_raw = data.get("parentCollection")
        parent = str(parent_raw) if parent_raw else None
        if key and name:
            by_key[key] = {"name": name, "parent": parent}

    key_to_path: dict[str, str] = {}

    def _resolve_path(key: str) -> str:
        cached = key_to_path.get(key)
        if cached is not None:
            return cached
        node = by_key[key]
        parent = node["parent"]
        if parent and parent in by_key:
            path = f"{_resolve_path(parent)}/{node['name']}"
        else:
            path = str(node["name"])
        key_to_path[key] = path
        return path

    path_to_key: dict[str, str] = {}
    for key in by_key:
        path_to_key[_resolve_path(key)] = key
    return path_to_key, key_to_path


def _collect_collection_items(
    client: zotero.Zotero,
    collection_key: str,
) -> list[dict[str, Any]]:
    last_error: Exception | None = None
    for _ in range(3):
        try:
            return client.everything(client.collection_items(collection_key, sort="dateAdded", direction="desc", limit=100))
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return []


def _collect_import_server_state(
    *,
    client: zotero.Zotero,
    entries: list[ImportEntry],
    root_collection: str,
    path_to_key: dict[str, str],
    key_to_path: dict[str, str],
) -> tuple[dict[str, dict[str, KnownItemKey]], dict[str, Any], datetime | None]:
    needed_paths = {root_collection}
    for entry in entries:
        needed_paths.update(entry.target_collections)

    known_items: dict[str, dict[str, KnownItemKey]] = {}
    collection_scan: list[dict[str, Any]] = []
    root_dates: list[datetime] = []

    for path in sorted(needed_paths):
        collection_key = path_to_key.get(path)
        if not collection_key:
            collection_scan.append({"path": path, "collection_key": None, "exists": False, "item_count": 0})
            continue
        items = _collect_collection_items(client, collection_key)
        collection_scan.append(
            {
                "path": path,
                "collection_key": collection_key,
                "exists": True,
                "item_count": len(items),
            }
        )
        for item in items:
            data = item.get("data", {})
            doi = _normalize_doi(data.get("DOI"))
            if not doi:
                continue
            collections = [path]
            collections.extend(key_to_path.get(key, key) for key in data.get("collections") or [] if key)
            _record_known_item(
                known_items,
                doi=doi,
                key=str(item.get("key") or ""),
                collections=collections,
                date_added=str(data.get("dateAdded") or ""),
                source=f"collection:{path}",
            )
            if path == root_collection:
                parsed = _parse_iso_datetime(str(data.get("dateAdded") or ""))
                if parsed is not None:
                    root_dates.append(parsed)

    auto_recent_cutoff = min(root_dates) - timedelta(minutes=10) if root_dates else None
    return known_items, {"collections": collection_scan}, auto_recent_cutoff


def _collect_recent_matching_items(
    *,
    client: zotero.Zotero,
    doi_filter: set[str],
    key_to_path: dict[str, str],
    cutoff: datetime,
    max_pages: int = 100,
) -> tuple[dict[str, dict[str, KnownItemKey]], dict[str, Any]]:
    known_items: dict[str, dict[str, KnownItemKey]] = {}
    pages_scanned = 0
    matched_items = 0
    examined_items = 0
    oldest_seen: str | None = None

    items = client.top(sort="dateAdded", direction="desc", limit=100)
    while True:
        pages_scanned += 1
        if not items:
            break
        page_oldest: datetime | None = None
        for item in items:
            data = item.get("data", {})
            examined_items += 1
            if data.get("itemType") in {"attachment", "note", "annotation"}:
                continue
            date_added_raw = str(data.get("dateAdded") or "")
            parsed = _parse_iso_datetime(date_added_raw)
            if parsed is not None and (page_oldest is None or parsed < page_oldest):
                page_oldest = parsed
                oldest_seen = date_added_raw
            doi = _normalize_doi(data.get("DOI"))
            if not doi or doi not in doi_filter:
                continue
            matched_items += 1
            collections = [key_to_path.get(key, key) for key in data.get("collections") or [] if key]
            _record_known_item(
                known_items,
                doi=doi,
                key=str(item.get("key") or ""),
                collections=collections,
                date_added=date_added_raw,
                source="recent-top-scan",
            )
        if page_oldest is not None and page_oldest < cutoff:
            break
        if pages_scanned >= max_pages or not client.links or not client.links.get("next"):
            break
        items = client.follow()

    diagnostics = {
        "cutoff_utc": cutoff.isoformat(),
        "pages_scanned": pages_scanned,
        "items_examined": examined_items,
        "matched_items": matched_items,
        "oldest_seen": oldest_seen,
    }
    return known_items, diagnostics


def _merge_known_maps(
    base: dict[str, dict[str, KnownItemKey]],
    incoming: dict[str, dict[str, KnownItemKey]],
) -> None:
    for doi, by_key in incoming.items():
        for key, slot in by_key.items():
            _record_known_item(
                base,
                doi=doi,
                key=key,
                collections=slot.collections,
                date_added=slot.date_added,
                source=",".join(sorted(slot.sources)),
            )


def _merge_checkpoint_state(
    *,
    checkpoint: dict[str, Any],
    known_items: dict[str, dict[str, KnownItemKey]],
) -> None:
    items = checkpoint.get("items")
    if not isinstance(items, dict):
        return
    for doi, raw in items.items():
        if not isinstance(raw, dict):
            continue
        key = raw.get("key")
        if not key:
            continue
        completed = raw.get("completed_collections") or []
        if not isinstance(completed, list):
            completed = []
        _record_known_item(
            known_items,
            doi=str(doi),
            key=str(key),
            collections=[str(path) for path in completed if str(path).strip()],
            date_added=None,
            source=f"checkpoint:{raw.get('status') or 'unknown'}",
        )


def _write_progress_files(
    *,
    output_dir: Path,
    processed_results: list[dict[str, Any]],
    failed_results: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    _write_json_atomic(output_dir / "imported_results.json", processed_results)
    _write_json_atomic(output_dir / "failed_results.json", failed_results)
    _write_json_atomic(output_dir / "import_summary.json", summary)


def import_rss_zotero_items(
    *,
    import_list: Path,
    output_dir: Path,
    profile: str | None,
    library: str,
    limit: int | None,
    apply: bool,
    recent_cutoff_utc: str | None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    library_ctx = _parse_library(library)
    root_collection, all_entries = _load_import_entries(import_list, limit=limit)
    needed_paths = {root_collection}
    for entry in all_entries:
        needed_paths.update(entry.target_collections)

    checkpoint_path = output_dir / "checkpoint.json"
    checkpoint = _load_checkpoint(checkpoint_path)

    processed_results: list[dict[str, Any]] = []
    failed_results: list[dict[str, Any]] = []
    counts = {
        "created_new": 0,
        "reused_existing": 0,
        "already_routed": 0,
        "collection_repairs": 0,
        "failed": 0,
    }

    def _current_summary() -> dict[str, Any]:
        return {
            "import_list": str(import_list),
            "apply": bool(apply),
            "total_entries_considered": len(all_entries),
            "created_new": counts["created_new"],
            "reused_existing": counts["reused_existing"],
            "already_routed": counts["already_routed"],
            "collection_repairs": counts["collection_repairs"],
            "failed": counts["failed"],
            "created_collections": [],
            "checkpoint_path": str(checkpoint_path),
            "sync_reminder": "",
            "phase": "preflight",
            "output_files": {
                "preview": str(output_dir / "import_preview.json"),
                "resume_state": str(output_dir / "resume_state.json"),
                "checkpoint": str(checkpoint_path),
                "imported_results": str(output_dir / "imported_results.json"),
                "failed_results": str(output_dir / "failed_results.json"),
                "summary": str(output_dir / "import_summary.json"),
            },
        }

    _write_progress_files(
        output_dir=output_dir,
        processed_results=processed_results,
        failed_results=failed_results,
        summary=_current_summary(),
    )

    if not all_entries:
        checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
        _write_json_atomic(checkpoint_path, checkpoint)
        empty_preview = {
            "import_list": str(import_list),
            "apply": apply,
            "total_entries_considered": 0,
            "existing_items_detected": 0,
            "pending_import": 0,
            "entries_needing_collection_repair": 0,
            "root_collection": root_collection,
            "server_existing_collection_paths": [],
            "server_missing_collection_paths": [],
            "local_existing_collection_paths": [],
            "local_missing_collection_paths": [],
            "sample_pending_dois": [],
            "sample_collection_repairs": [],
            "checkpoint_path": str(checkpoint_path),
            "server_state_files": {
                "resume_state": str(output_dir / "resume_state.json"),
                "preview": str(output_dir / "import_preview.json"),
            },
            "diagnostics": {
                "collection_scan": {"collections": []},
                "recent_scan": {"enabled": False},
                "auto_recent_cutoff_utc": None,
            },
        }
        _write_json_atomic(output_dir / "import_preview.json", empty_preview)
        _write_json_atomic(
            output_dir / "resume_state.json",
            {
                "known_items": {},
                "collection_diagnostics": {"collections": []},
                "recent_diagnostics": {"enabled": False},
                "checkpoint_path": str(checkpoint_path),
            },
        )
        if not apply:
            return empty_preview
        summary = _current_summary()
        summary["phase"] = "apply"
        _write_progress_files(
            output_dir=output_dir,
            processed_results=processed_results,
            failed_results=failed_results,
            summary=summary,
        )
        return summary

    client = _build_client(profile, library_ctx)
    local_collection_paths = _load_local_collection_paths(profile, library_ctx)
    server_path_to_key, server_key_to_path = _build_server_collection_maps(client)

    known_items, collection_diagnostics, auto_recent_cutoff = _collect_import_server_state(
        client=client,
        entries=all_entries,
        root_collection=root_collection,
        path_to_key=server_path_to_key,
        key_to_path=server_key_to_path,
    )
    _merge_checkpoint_state(checkpoint=checkpoint, known_items=known_items)

    cutoff_dt = _parse_iso_datetime(recent_cutoff_utc) if recent_cutoff_utc else auto_recent_cutoff
    recent_diagnostics: dict[str, Any] = {"enabled": False}
    if cutoff_dt is not None:
        recent_known, recent_diagnostics = _collect_recent_matching_items(
            client=client,
            doi_filter={entry.doi for entry in all_entries},
            key_to_path=server_key_to_path,
            cutoff=cutoff_dt,
        )
        recent_diagnostics["enabled"] = True
        _merge_known_maps(known_items, recent_known)

    entries_with_existing_item = 0
    entries_needing_collection_repair = 0
    pending_import_entries: list[ImportEntry] = []
    repair_entries: list[dict[str, Any]] = []

    for entry in all_entries:
        known_for_doi = known_items.get(entry.doi)
        if not known_for_doi:
            pending_import_entries.append(entry)
            continue
        entries_with_existing_item += 1
        chosen_key = _choose_best_known_key(known_for_doi, entry.target_collections)
        existing_collections = set(known_for_doi[chosen_key].collections)
        missing = [path for path in entry.target_collections if path not in existing_collections]
        if missing:
            entries_needing_collection_repair += 1
            repair_entries.append(
                {
                    "doi": entry.doi,
                    "key": chosen_key,
                    "missing_collections": missing,
                    "known_keys": sorted(known_for_doi),
                }
            )

    preview = {
        "import_list": str(import_list),
        "apply": apply,
        "total_entries_considered": len(all_entries),
        "existing_items_detected": entries_with_existing_item,
        "pending_import": len(pending_import_entries),
        "entries_needing_collection_repair": entries_needing_collection_repair,
        "root_collection": root_collection,
        "server_existing_collection_paths": sorted(path for path in needed_paths if path in server_path_to_key),
        "server_missing_collection_paths": sorted(path for path in needed_paths if path not in server_path_to_key),
        "local_existing_collection_paths": sorted(path for path in needed_paths if path in local_collection_paths),
        "local_missing_collection_paths": sorted(path for path in needed_paths if path not in local_collection_paths),
        "sample_pending_dois": [entry.doi for entry in pending_import_entries[:10]],
        "sample_collection_repairs": repair_entries[:10],
        "checkpoint_path": str(checkpoint_path),
        "server_state_files": {
            "resume_state": str(output_dir / "resume_state.json"),
            "preview": str(output_dir / "import_preview.json"),
        },
        "diagnostics": {
            "collection_scan": collection_diagnostics,
            "recent_scan": recent_diagnostics,
            "auto_recent_cutoff_utc": auto_recent_cutoff.isoformat() if auto_recent_cutoff else None,
        },
    }
    _write_json_atomic(output_dir / "import_preview.json", preview)
    _write_json_atomic(
        output_dir / "resume_state.json",
        {
            "known_items": _serialize_known_items(known_items),
            "collection_diagnostics": collection_diagnostics,
            "recent_diagnostics": recent_diagnostics,
            "checkpoint_path": str(checkpoint_path),
        },
    )
    if not apply:
        return preview

    writer = _build_writer(profile, library_ctx)
    created_paths: list[dict[str, str]] = []
    mutable_server_paths = dict(server_path_to_key)
    for path in sorted(needed_paths, key=lambda value: (value.count("/"), value)):
        _ensure_collection_path(writer, mutable_server_paths, path, apply=True, created_paths=created_paths)

    def _current_summary() -> dict[str, Any]:
        return {
            "import_list": str(import_list),
            "apply": True,
            "total_entries_considered": len(all_entries),
            "created_new": counts["created_new"],
            "reused_existing": counts["reused_existing"],
            "already_routed": counts["already_routed"],
            "collection_repairs": counts["collection_repairs"],
            "failed": counts["failed"],
            "created_collections": created_paths,
            "checkpoint_path": str(checkpoint_path),
            "sync_reminder": SYNC_REMINDER if counts["created_new"] or counts["collection_repairs"] else "",
            "phase": "apply",
            "output_files": {
                "preview": str(output_dir / "import_preview.json"),
                "resume_state": str(output_dir / "resume_state.json"),
                "checkpoint": str(checkpoint_path),
                "imported_results": str(output_dir / "imported_results.json"),
                "failed_results": str(output_dir / "failed_results.json"),
                "summary": str(output_dir / "import_summary.json"),
            },
        }

    _write_progress_files(
        output_dir=output_dir,
        processed_results=processed_results,
        failed_results=failed_results,
        summary=_current_summary(),
    )

    for index, entry in enumerate(all_entries, 1):
        failure_key: str | None = None
        failure_completed_collections: list[str] = []
        try:
            known_for_doi = known_items.get(entry.doi)
            if known_for_doi:
                key = _choose_best_known_key(known_for_doi, entry.target_collections)
                failure_key = key
                target_paths = list(entry.target_collections)
                completed_paths = set(known_for_doi[key].collections)
                failure_completed_collections = sorted(completed_paths)
                moved_to: list[str] = []
                for collection_path in target_paths:
                    collection_key = _ensure_collection_path(
                        writer,
                        mutable_server_paths,
                        collection_path,
                        apply=True,
                        created_paths=created_paths,
                    )
                    if collection_path in completed_paths:
                        continue
                    writer.move_to_collection(key, collection_key)
                    completed_paths.add(collection_path)
                    failure_completed_collections = sorted(completed_paths)
                    moved_to.append(collection_path)
                    known_for_doi[key].collections.add(collection_path)
                    _update_checkpoint(
                        checkpoint,
                        checkpoint_path,
                        doi=entry.doi,
                        status="routing-existing",
                        key=key,
                        completed_collections=sorted(completed_paths),
                        target_collections=target_paths,
                    )
                action = "already_routed"
                if moved_to:
                    action = "reused_existing"
                    counts["collection_repairs"] += 1
                    counts["reused_existing"] += 1
                else:
                    counts["already_routed"] += 1
                _update_checkpoint(
                    checkpoint,
                    checkpoint_path,
                    doi=entry.doi,
                    status=action,
                    key=key,
                    completed_collections=sorted(completed_paths),
                    target_collections=target_paths,
                )
                processed_results.append(
                    {
                        "index": index,
                        "action": action,
                        "doi": entry.doi,
                        "key": key,
                        "title": entry.title,
                        "target_collections": target_paths,
                        "moved_to": moved_to,
                        "tracked_authors": entry.tracked_authors,
                        "known_keys": sorted(known_for_doi),
                    }
                )
                _write_progress_files(
                    output_dir=output_dir,
                    processed_results=processed_results,
                    failed_results=failed_results,
                    summary=_current_summary(),
                )
                continue

            extra_fields, resolve_warning = _resolve_metadata(entry.doi)
            key = writer.add_item(doi=entry.doi, extra_fields=extra_fields)
            failure_key = key
            _record_known_item(
                known_items,
                doi=entry.doi,
                key=key,
                collections=[],
                date_added=None,
                source="created-this-run",
            )
            completed_paths: list[str] = []
            _update_checkpoint(
                checkpoint,
                checkpoint_path,
                doi=entry.doi,
                status="created",
                key=key,
                completed_collections=completed_paths,
                target_collections=entry.target_collections,
            )
            for collection_path in entry.target_collections:
                collection_key = _ensure_collection_path(
                    writer,
                    mutable_server_paths,
                    collection_path,
                    apply=True,
                    created_paths=created_paths,
                )
                writer.move_to_collection(key, collection_key)
                completed_paths.append(collection_path)
                failure_completed_collections = list(completed_paths)
                known_items[entry.doi][key].collections.add(collection_path)
                _update_checkpoint(
                    checkpoint,
                    checkpoint_path,
                    doi=entry.doi,
                    status="routing-new",
                    key=key,
                    completed_collections=completed_paths,
                    target_collections=entry.target_collections,
                )
            row: dict[str, Any] = {
                "index": index,
                "action": "created_new",
                "doi": entry.doi,
                "key": key,
                "title": entry.title,
                "target_collections": list(entry.target_collections),
                "tracked_authors": entry.tracked_authors,
            }
            if extra_fields:
                row["resolved"] = _resolved_summary(extra_fields)
            elif resolve_warning is not None:
                row["resolve_warning"] = resolve_warning
            processed_results.append(row)
            counts["created_new"] += 1
            _update_checkpoint(
                checkpoint,
                checkpoint_path,
                doi=entry.doi,
                status="created_new",
                key=key,
                completed_collections=completed_paths,
                target_collections=entry.target_collections,
            )
        except ZoteroWriteError as exc:
            failure = {
                "index": index,
                "doi": entry.doi,
                "title": entry.title,
                "target_collections": entry.target_collections,
                "tracked_authors": entry.tracked_authors,
                "key": failure_key,
                "completed_collections": failure_completed_collections,
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "retryable": exc.retryable,
                },
            }
            failed_results.append(failure)
            counts["failed"] += 1
            _update_checkpoint(
                checkpoint,
                checkpoint_path,
                doi=entry.doi,
                status="failed",
                key=failure_key,
                completed_collections=failure_completed_collections,
                target_collections=entry.target_collections,
                error=failure["error"],
            )
        except Exception as exc:
            failure = {
                "index": index,
                "doi": entry.doi,
                "title": entry.title,
                "target_collections": entry.target_collections,
                "tracked_authors": entry.tracked_authors,
                "key": failure_key,
                "completed_collections": failure_completed_collections,
                "error": {
                    "code": "unexpected_exception",
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "retryable": True,
                },
            }
            failed_results.append(failure)
            counts["failed"] += 1
            _update_checkpoint(
                checkpoint,
                checkpoint_path,
                doi=entry.doi,
                status="failed",
                key=failure_key,
                completed_collections=failure_completed_collections,
                target_collections=entry.target_collections,
                error=failure["error"],
            )
        _write_progress_files(
            output_dir=output_dir,
            processed_results=processed_results,
            failed_results=failed_results,
            summary=_current_summary(),
        )

    _write_json_atomic(
        output_dir / "resume_state.json",
        {
            "known_items": _serialize_known_items(known_items),
            "collection_diagnostics": collection_diagnostics,
            "recent_diagnostics": recent_diagnostics,
            "checkpoint_path": str(checkpoint_path),
        },
    )
    return _current_summary()


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Build RSS DOI import lists and import matching Zotero items."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser(
        "build-list",
        help="Build import_list.json from an RSS selected JSON export.",
    )
    build_parser.add_argument("--selected-json", type=Path, required=True, help="Path to the RSS selected JSON array.")
    build_parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "log" / "rss_doi_import_list",
        help="Directory for generated import list files.",
    )
    build_parser.add_argument(
        "--zotero-export-json",
        type=Path,
        default=None,
        help="Optional existing summarize-all JSON export. If omitted, the script runs 'uv run zot --json --detail full summarize-all'.",
    )

    import_parser = subparsers.add_parser(
        "import-list",
        help="Import DOI entries from import_list.json into Zotero.",
    )
    import_parser.add_argument(
        "--import-list",
        type=Path,
        required=True,
        help="Path to import_list.json generated by the build-list subcommand.",
    )
    import_parser.add_argument(
        "--output-dir",
        type=Path,
        default=repo_root / "log" / "rss_doi_import",
        help="Directory for import preview/results.",
    )
    import_parser.add_argument("--profile", default=None, help="Optional zot profile name.")
    import_parser.add_argument("--library", default="user", help="Library: 'user' or 'group:<id>'.")
    import_parser.add_argument("--limit", type=int, default=None, help="Optionally limit the number of DOI entries.")
    import_parser.add_argument(
        "--recent-cutoff-utc",
        default=None,
        help="Optional ISO timestamp in UTC for recent top-item orphan scan, e.g. 2026-05-25T09:00:00Z.",
    )
    import_parser.add_argument("--apply", action="store_true", help="Actually import and route items. Default is dry-run only.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    if args.command == "build-list":
        summary = build_rss_zotero_items_outputs(
            selected_json=args.selected_json.resolve(),
            output_dir=args.output_dir.resolve(),
            repo_root=repo_root,
            zotero_export_json=(args.zotero_export_json.resolve() if args.zotero_export_json else None),
        )
    elif args.command == "import-list":
        summary = import_rss_zotero_items(
            import_list=args.import_list.resolve(),
            output_dir=args.output_dir.resolve(),
            profile=args.profile,
            library=args.library,
            limit=args.limit,
            apply=args.apply,
            recent_cutoff_utc=args.recent_cutoff_utc,
        )
    else:
        raise ValueError(f"Unsupported command: {args.command}")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
